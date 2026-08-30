"""Заказы, содержащие товары конкретного поставщика (ADR-026).

Приложение `suppliers` стоит ниже `orders` в цепочке зависимостей и
обращается к заказам только через этот публичный сервис, а не к их ORM
(`docs/database.md`, ADR-002). Данные передаются объектами сервисного
слоя — тем же способом, каким `catalog` принимает прайс от `suppliers`
(ADR-016): поставщик не получает ни моделей заказа, ни доступа к чужим
позициям.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db.models import Prefetch

from orders.models import Order, OrderItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupplierOrderItemData:
    """Позиция заказа, относящаяся к прайсу поставщика."""

    product_name: str
    quantity: int
    price: Decimal
    total: Decimal


@dataclass(frozen=True)
class SupplierDeliveryData:
    """Получатель и адрес доставки на момент оформления (ADR-024)."""

    last_name: str
    first_name: str
    middle_name: str
    phone: str
    email: str
    city: str
    street: str
    house: str
    structure: str
    building: str
    apartment: str


@dataclass(frozen=True)
class SupplierOrderData:
    """Заказ в том виде, в каком его видит поставщик."""

    id: int
    confirmed_at: datetime | None
    state: str
    items: tuple[SupplierOrderItemData, ...]
    total: Decimal
    delivery: SupplierDeliveryData


def supplier_orders(*, shop_id: int) -> list[SupplierOrderData]:
    """Вернуть оформленные заказы с товарами указанного магазина.

    Корзины исключены (ADR-009): незакрытый фильтр означал бы показ
    поставщику чужих корзин.

    Заказ показывается только своими позициями: в одном заказе могут
    быть товары нескольких поставщиков, и каждый видит лишь свою часть.
    Сумма считается по этой же части — это то, что поставщику предстоит
    отгрузить, а не общая сумма покупки.

    Принадлежность позиции определяется ссылкой на предложение
    (`product_info__shop`). Ссылка устойчива: импорт обновляет
    предложения на месте и не удаляет их (ADR-008), а деактивированные
    предложения связь сохраняют. Позиция, чьё предложение всё же
    удалено вручную, в выдачу не попадёт — `SET_NULL` обнуляет ссылку
    (ADR-003), и определить поставщика по snapshot нельзя: название
    магазина изменяемо.
    """
    own_items = OrderItem.objects.filter(product_info__shop_id=shop_id)

    orders = (
        Order.objects.orders()
        .filter(items__product_info__shop_id=shop_id)
        .distinct()
        .prefetch_related(Prefetch("items", queryset=own_items, to_attr="own_items"))
    )

    result = [_build(order) for order in orders]
    logger.debug("Supplier orders listed: shop_id=%s orders=%s", shop_id, len(result))
    return result


def _build(order: Order) -> SupplierOrderData:
    """Собрать представление заказа для поставщика."""
    items = tuple(_build_item(item) for item in order.own_items)

    return SupplierOrderData(
        id=order.pk,
        confirmed_at=order.confirmed_at,
        state=order.state,
        items=items,
        total=sum((item.total for item in items), Decimal("0.00")),
        delivery=SupplierDeliveryData(
            last_name=order.delivery_last_name,
            first_name=order.delivery_first_name,
            middle_name=order.delivery_middle_name,
            phone=order.delivery_phone,
            email=order.delivery_email,
            city=order.delivery_city,
            street=order.delivery_street,
            house=order.delivery_house,
            structure=order.delivery_structure,
            building=order.delivery_building,
            apartment=order.delivery_apartment,
        ),
    )


def _build_item(item: OrderItem) -> SupplierOrderItemData:
    """Позиция по snapshot: цена на момент заказа, а не текущая (ADR-003)."""
    return SupplierOrderItemData(
        product_name=item.product_name,
        quantity=item.quantity,
        price=item.price,
        total=item.price * item.quantity,
    )
