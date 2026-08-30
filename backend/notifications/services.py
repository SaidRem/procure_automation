"""Публичный сервисный слой приложения notifications (ADR-005, ADR-010).

Единственная точка проекта, знающая о задаче отправки писем. Доменные
сервисы вызывают только эти функции и не импортируют Celery-задачи
напрямую: цепочка вызова — `<app>.services` -> `notifications.services`
-> Celery task.

Фасады уведомлений принимают идентификаторы, а не объекты: аргументы
доходят до Celery-задачи сериализованными, и инстанс модели к моменту
выполнения устарел бы.

О домене заказов модуль знает намеренно: `notifications` — верхний
уровень цепочки зависимостей и опирается на `orders`
(`docs/database.md`), а ADR-005 прямо относит подтверждение заказа и
накладную администратору к функциям `notifications.services`. Обратной
зависимости нет: `orders` вызывает только этот модуль и не импортирует
ни задачи, ни Celery. Модели `users`, `catalog` и `suppliers` не
импортируются — всё, что нужно письму, доступно через сам заказ.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from notifications.tasks import send_email
from orders.models import Order, OrderItem

logger = logging.getLogger(__name__)


def send_email_async(*, subject: str, body: str, recipient: str) -> None:
    """Поставить письмо в очередь после успешного коммита транзакции.

    Постановка через `transaction.on_commit` (ADR-005): письмо не должно
    уходить, если транзакция, породившая событие, откатилась —
    пользователь получил бы подтверждение регистрации, которой не было.

    Сбой постановки не прерывает вызывающую операцию. Коллбэк
    выполняется уже после коммита, и исключение из него отменило бы
    ответ на запрос, ничего не откатив: пользователь был бы создан, а
    клиент получил бы ошибку. Недоступность брокера — причина не
    отправить письмо, а не причина считать регистрацию неудавшейся,
    поэтому она логируется и на результат операции не влияет.
    """
    logger.info("Email queued: subject=%r recipient=%s", subject, recipient)
    transaction.on_commit(lambda: _enqueue(subject, body, recipient))


def _enqueue(subject: str, body: str, recipient: str) -> None:
    """Отправить задачу в очередь, не прерывая вызывающую операцию."""
    try:
        send_email.delay(subject=subject, body=body, recipient=recipient)
    except Exception:
        logger.exception(
            "Email task was not queued: subject=%r recipient=%s", subject, recipient
        )


def send_order_confirmation(order_id: int) -> None:
    """Отправить покупателю подтверждение приёма заказа.

    Письмо ставится в очередь после коммита транзакции, оформившей
    заказ (ADR-005): до коммита заказа ещё нет, и подтверждение
    несуществующего заказа ушло бы при откате.
    """
    transaction.on_commit(_deferred(_send_order_confirmation, order_id))


def send_new_order_notification(order_id: int) -> None:
    """Отправить администратору накладную по оформленному заказу."""
    transaction.on_commit(_deferred(_send_new_order_notification, order_id))


def _deferred(action: Callable[[int], None], order_id: int) -> Callable[[], None]:
    """Обернуть отправку так, чтобы её сбой не прерывал операцию.

    Коллбэк выполняется уже после коммита: исключение из него отменило
    бы ответ на запрос, ничего не откатив, — заказ был бы оформлен, а
    покупатель получил бы ошибку. Недоступность почты не делает заказ
    неоформленным, поэтому она логируется и на результат не влияет.
    """

    def run() -> None:
        try:
            action(order_id)
        except Exception:
            logger.exception("Order notification failed: order_id=%s", order_id)

    return run


def _send_order_confirmation(order_id: int) -> None:
    """Собрать и поставить письмо покупателю."""
    order = _load_order(order_id)
    body = _customer_body(order)

    _enqueue(f"Заказ №{order.pk} принят", body, order.user.email)


def _send_new_order_notification(order_id: int) -> None:
    """Собрать и поставить накладную администратору."""
    order = _load_order(order_id)
    body = _admin_body(order)

    _enqueue(f"Новый заказ №{order.pk}", body, settings.ORDER_ADMIN_EMAIL)


def _load_order(order_id: int) -> Order:
    """Прочитать заказ вместе с покупателем и позициями.

    `select_related` и `prefetch_related` обязательны: письмо обходит
    все позиции заказа, и без предзагрузки это даёт N+1
    (`coding_rules.md`).
    """
    return (
        Order.objects.select_related("user").prefetch_related("items").get(pk=order_id)
    )


def _customer_body(order: Order) -> str:
    """Текст письма покупателю: состав заказа и адрес доставки."""
    return "\n".join(
        (
            f"Заказ №{order.pk} принят.",
            f"Дата: {_format_date(order)}",
            "",
            "Состав заказа:",
            *_item_lines(order),
            "",
            f"Итого: {_format_money(_order_total(order))}",
            "",
            "Адрес доставки:",
            _recipient_line(order),
            _address_line(order),
            "",
            "Спасибо за заказ.",
        )
    )


def _admin_body(order: Order) -> str:
    """Текст накладной администратору: кто заказал и что отгружать."""
    return "\n".join(
        (
            f"Оформлен заказ №{order.pk}.",
            f"Дата: {_format_date(order)}",
            f"Покупатель: {order.user.email}",
            "",
            "Доставка:",
            _recipient_line(order),
            _address_line(order),
            "",
            "Позиции:",
            *_item_lines(order),
            "",
            f"Итого: {_format_money(_order_total(order))}",
        )
    )


def _item_lines(order: Order) -> list[str]:
    """Строки позиций по snapshot заказа (ADR-003).

    Источник — зафиксированные при оформлении наименование, магазин и
    цена, а не текущий каталог: к моменту отправки письма прайс мог
    измениться, а письмо обязано описывать заказанное.
    """
    return [
        f"- {item.product_name} ({item.shop_name}): "
        f"{item.quantity} x {_format_money(item.price)} = "
        f"{_format_money(_item_total(item))}"
        for item in order.items.all()
    ]


def _recipient_line(order: Order) -> str:
    """Получатель из snapshot заказа (ADR-024, ADR-027)."""
    name = " ".join(
        part
        for part in (
            order.delivery_last_name,
            order.delivery_first_name,
            order.delivery_middle_name,
        )
        if part
    )
    contacts = ", ".join(
        part for part in (order.delivery_phone, order.delivery_email) if part
    )

    return f"{name}, {contacts}" if contacts else name


def _address_line(order: Order) -> str:
    """Адрес из snapshot заказа, без пустых частей."""
    parts = (
        (order.delivery_city, ""),
        (order.delivery_street, "ул. "),
        (order.delivery_house, "д. "),
        (order.delivery_structure, "корп. "),
        (order.delivery_building, "стр. "),
        (order.delivery_apartment, "кв. "),
    )

    return ", ".join(f"{prefix}{value}" for value, prefix in parts if value)


def _item_total(item: OrderItem) -> Decimal:
    """Сумма позиции по зафиксированной цене."""
    return item.price * item.quantity


def _order_total(order: Order) -> Decimal:
    """Сумма заказа по snapshot-ценам позиций (ADR-009)."""
    return sum((_item_total(item) for item in order.items.all()), Decimal("0.00"))


def _format_money(value: Decimal) -> str:
    """Денежное значение в письме: две цифры после запятой (ADR-015)."""
    return f"{value:.2f}"


def _format_date(order: Order) -> str:
    """Дата оформления заказа (ADR-022)."""
    return timezone.localtime(order.confirmed_at).strftime("%d.%m.%Y %H:%M")
