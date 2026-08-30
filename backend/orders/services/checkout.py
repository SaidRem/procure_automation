"""Оформление заказа: переход basket -> new (ADR-022).

Оформление — смена состояния, а не копирование данных между таблицами
(ADR-009). В одной транзакции заполняются snapshot получателя и адреса
(ADR-024, ADR-027), snapshot каждой позиции (ADR-003) и отметка времени
оформления.

Остатки не списываются и не резервируются: полем `quantity` владеет
прайс поставщика, и ближайший импорт перезаписал бы списание значением
из файла (ADR-022, ADR-008).

Уведомления ставятся через `notifications.services` (ADR-005): ни
Celery-задачи, ни отправка писем здесь не вызываются. Письма уходят
только после коммита оформления и их сбой заказ не отменяет.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from notifications import services as notifications
from orders.models import Order, OrderItem, OrderState
from orders.services import state as state_service
from orders.services.basket import check_orderable, get_or_create_basket
from orders.services.exceptions import (
    ContactNotFound,
    EmptyBasket,
    IncompleteRecipientData,
    OfferGone,
)
from users.models import Contact, User

logger = logging.getLogger(__name__)

# Поля контакта, без которых заказ не может быть оформлен: получателя
# нужно назвать в накладной, а адрес — доставить (ADR-027).
REQUIRED_CONTACT_FIELDS = ("last_name", "first_name", "city", "street", "phone")

# Snapshot доставки: поле Order -> поле Contact (ADR-024, ADR-027).
DELIVERY_SNAPSHOT_FIELDS = {
    "delivery_last_name": "last_name",
    "delivery_first_name": "first_name",
    "delivery_middle_name": "middle_name",
    "delivery_email": "email",
    "delivery_phone": "phone",
    "delivery_city": "city",
    "delivery_street": "street",
    "delivery_house": "house",
    "delivery_structure": "structure",
    "delivery_building": "building",
    "delivery_apartment": "apartment",
}


def checkout_order(user: User, contact_id: int) -> Order:
    """Оформить корзину пользователя как заказ.

    Возвращает заказ в состоянии `new` со заполненными snapshot-полями.
    Проверки выполняются до записи: частично оформленный заказ
    недопустим, поэтому вся операция идёт одной транзакцией.

    Доступность позиций проверяется повторно (ADR-025): между
    добавлением товара в корзину и оформлением поставщик мог снять
    предложение с продажи, отключить приём заказов или продать остаток.
    """
    with transaction.atomic():
        basket = _lock_basket(user)
        items = _load_items(basket)
        contact = _get_contact(user, contact_id)

        _validate_contact(contact)

        for item in items:
            _validate_item(item)

        _apply_delivery_snapshot(basket, contact)
        _apply_item_snapshots(items)

        basket.contact = contact
        basket.confirmed_at = timezone.now()
        state_service.transition(basket, OrderState.NEW, save=False)
        basket.save()

        # Постановка внутри транзакции, отправка — после её коммита:
        # `notifications.services` регистрирует коллбэк on_commit
        # (ADR-005). Откат оформления не оставляет ни заказа, ни писем.
        notifications.send_order_confirmation(basket.pk)
        notifications.send_new_order_notification(basket.pk)

    logger.info(
        "Order placed: order_id=%s user_id=%s items=%s",
        basket.pk,
        user.pk,
        len(items),
    )
    return basket


def _lock_basket(user: User) -> Order:
    """Заблокировать корзину на время оформления."""
    basket = get_or_create_basket(user)
    return Order.objects.select_for_update().get(pk=basket.pk)


def _load_items(basket: Order) -> list[OrderItem]:
    """Загрузить позиции корзины вместе с товаром и магазином.

    `select_related` обязателен: без него проверка доступности и сбор
    snapshot дают по три запроса на позицию (`coding_rules.md`).
    """
    items = list(
        basket.items.select_related(
            "product_info",
            "product_info__product",
            "product_info__shop",
        )
    )

    if not items:
        raise EmptyBasket("Корзина пуста.")

    return items


def _get_contact(user: User, contact_id: int) -> Contact:
    """Взять контакт пользователя.

    Выборка ограничена владельцем: чужой контакт неотличим от
    несуществующего, и snapshot снимается только со своего адреса
    (ADR-024).
    """
    contact = Contact.objects.filter(pk=contact_id, user=user).first()

    if contact is None:
        raise ContactNotFound(f"Контакт {contact_id} не найден.")

    return contact


def _validate_contact(contact: Contact) -> None:
    """Проверить полноту данных получателя (ADR-027).

    Контакты, созданные до появления полей получателя, могут быть
    неполными: backfill намеренно не выполнялся. Неполнота
    обнаруживается здесь — там, где впервые становится важна.
    """
    missing = tuple(
        field
        for field in REQUIRED_CONTACT_FIELDS
        if not getattr(contact, field).strip()
    )

    if missing:
        raise IncompleteRecipientData(missing)


def _validate_item(item: OrderItem) -> None:
    """Проверить, что позицию всё ещё можно заказать."""
    if item.product_info is None:
        raise OfferGone(
            f"Товар «{item.product_name or item.pk}» больше не продаётся."
        )

    check_orderable(item.product_info, item.quantity)


def _apply_delivery_snapshot(order: Order, contact: Contact) -> None:
    """Скопировать получателя и адрес в заказ (ADR-024, ADR-027)."""
    for order_field, contact_field in DELIVERY_SNAPSHOT_FIELDS.items():
        setattr(order, order_field, getattr(contact, contact_field))


def _apply_item_snapshots(items: list[OrderItem]) -> None:
    """Зафиксировать наименование, магазин и цены позиций (ADR-003).

    После этого сумма заказа считается по snapshot, а не по текущему
    каталогу: импорт прайса не изменит уже оформленный заказ.
    """
    for item in items:
        offer = item.product_info
        item.product_name = offer.product.name
        item.shop_name = offer.shop.name
        item.price = offer.price
        item.price_rrc = offer.price_rrc

    OrderItem.objects.bulk_update(
        items,
        ("product_name", "shop_name", "price", "price_rrc"),
    )
