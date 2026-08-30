"""Операции с корзиной покупателя (ADR-009, ADR-025).

Корзина — это `Order` в состоянии `basket`, её позиции — обычные
`OrderItem`. Пока заказ не оформлен, цена и наименование берутся из
текущего `catalog.ProductInfo`, а snapshot-поля позиции не заполнены
(ADR-003).

Доступность предложения к заказу проверяется здесь, а не фильтром
каталожной выдачи: каталог показывает предложение, даже когда заказать
его сейчас нельзя (ADR-025).
"""

from __future__ import annotations

import logging

from django.db import transaction

from catalog.models import ProductInfo
from orders.models import Order, OrderItem, OrderState
from orders.services.exceptions import (
    BasketItemNotFound,
    InsufficientStock,
    InvalidQuantity,
    OfferGone,
    OfferInactive,
    ShopNotAcceptingOrders,
)
from users.models import User

logger = logging.getLogger(__name__)


def get_or_create_basket(user: User) -> Order:
    """Вернуть корзину пользователя, создав её при первом обращении.

    Отдельного действия «создать корзину» нет: она появляется при
    первом добавлении позиции (ADR-022). Повторный вызов возвращает ту
    же запись — не более одной корзины на пользователя (ADR-009).
    """
    basket, created = Order.objects.get_or_create(
        user=user,
        state=OrderState.BASKET,
    )

    if created:
        logger.info("Basket created: order_id=%s user_id=%s", basket.pk, user.pk)

    return basket


def add_item(user: User, product_info: ProductInfo, quantity: int) -> OrderItem:
    """Добавить предложение в корзину или увеличить его количество.

    Повторное добавление того же предложения увеличивает количество
    существующей позиции: одно предложение — одна строка корзины.
    Доступность проверяется по итоговому количеству, а не по
    добавляемому: остатка должно хватать на всю позицию целиком.
    """
    _validate_quantity(quantity)

    with transaction.atomic():
        basket = _lock_basket(user)

        item = basket.items.filter(product_info=product_info).first()
        total = quantity if item is None else item.quantity + quantity

        check_orderable(product_info, total)

        if item is None:
            item = OrderItem.objects.create(
                order=basket,
                product_info=product_info,
                quantity=total,
            )
        else:
            item.quantity = total
            item.save(update_fields=["quantity"])

    logger.info(
        "Basket item added: order_id=%s product_info_id=%s quantity=%s",
        basket.pk,
        product_info.pk,
        total,
    )
    return item


def update_item_quantity(user: User, item_id: int, quantity: int) -> OrderItem:
    """Задать количество позиции корзины.

    Нулевое количество не удаляет позицию: удаление — отдельная
    операция `remove_item`, и подменять её здесь означало бы стирать
    строку в ответ на опечатку в количестве.
    """
    _validate_quantity(quantity)

    with transaction.atomic():
        basket = _lock_basket(user)
        item = _get_item(basket, item_id)

        if item.product_info is None:
            # Позиция найдена, исчезло предложение: причина отказа
            # другая, и покупателю она означает «удалите позицию», а не
            # «такой позиции нет».
            raise OfferGone(
                f"Позиция {item_id} ссылается на удалённое предложение."
            )

        check_orderable(item.product_info, quantity)

        item.quantity = quantity
        item.save(update_fields=["quantity"])

    logger.info(
        "Basket item quantity changed: order_id=%s item_id=%s quantity=%s",
        basket.pk,
        item_id,
        quantity,
    )
    return item


def remove_item(user: User, item_id: int) -> None:
    """Удалить позицию из корзины.

    Физическое удаление здесь допустимо: позиция корзины выражает
    текущее намерение покупателя, а не историю заказа (ADR-022,
    amendment).
    """
    with transaction.atomic():
        basket = _lock_basket(user)
        item = _get_item(basket, item_id)
        item.delete()

    logger.info("Basket item removed: order_id=%s item_id=%s", basket.pk, item_id)


def _validate_quantity(quantity: int) -> None:
    """Отклонить непозитивное количество."""
    if quantity <= 0:
        raise InvalidQuantity("Количество должно быть больше нуля.")


def _lock_basket(user: User) -> Order:
    """Заблокировать корзину пользователя на время операции.

    Блокировка строки сериализует изменения одной корзины: без неё
    одновременное добавление одного предложения из двух запросов
    приводит либо к нарушению `unique(order, product_info)`, либо к
    потере одного из увеличений количества.
    """
    basket = get_or_create_basket(user)
    return Order.objects.select_for_update().get(pk=basket.pk)


def _get_item(basket: Order, item_id: int) -> OrderItem:
    """Найти позицию в корзине пользователя.

    Выборка ограничена корзиной: обращение к чужой позиции неотличимо
    от обращения к несуществующей.
    """
    item = basket.items.filter(pk=item_id).first()

    if item is None:
        raise BasketItemNotFound(f"Позиция {item_id} не найдена в корзине.")

    return item


def check_orderable(product_info: ProductInfo, quantity: int) -> None:
    """Проверить, можно ли заказать предложение в этом количестве.

    Функция публична внутри пакета: то же правило применяется при
    оформлении заказа (ADR-025 требует одного определения
    заказуемости, а не двух копий).

    Три причины отказа различимы (ADR-025): снятие с продажи
    окончательно, отключённый приём заказов и нехватка остатка
    временны.
    """
    if not product_info.is_active:
        raise OfferInactive(
            "Предложение снято поставщиком с продажи.",
            product_info_id=product_info.pk,
        )

    if not product_info.shop.state:
        raise ShopNotAcceptingOrders(
            f"Поставщик «{product_info.shop.name}» временно не принимает заказы.",
            product_info_id=product_info.pk,
        )

    if product_info.quantity < quantity:
        raise InsufficientStock(
            f"Доступно {product_info.quantity} шт., запрошено {quantity} шт.",
            product_info_id=product_info.pk,
        )
