"""Публичный сервисный слой приложения orders.

Слой представления и другие домены обращаются к операциям с корзиной и
заказом только через этот пакет (ADR-006).
"""

from orders.services.basket import (
    add_item,
    get_or_create_basket,
    remove_item,
    update_item_quantity,
)
from orders.services.checkout import checkout_order
from orders.services.exceptions import (
    BasketItemNotFound,
    ContactNotFound,
    EmptyBasket,
    IncompleteRecipientData,
    InsufficientStock,
    InvalidQuantity,
    InvalidStateTransition,
    OfferGone,
    OfferInactive,
    OfferUnavailable,
    OrdersServiceError,
    ShopNotAcceptingOrders,
)
from orders.services.state import can_transition, transition

__all__ = (
    "BasketItemNotFound",
    "ContactNotFound",
    "EmptyBasket",
    "IncompleteRecipientData",
    "InsufficientStock",
    "InvalidQuantity",
    "InvalidStateTransition",
    "OfferGone",
    "OfferInactive",
    "OfferUnavailable",
    "OrdersServiceError",
    "ShopNotAcceptingOrders",
    "add_item",
    "can_transition",
    "checkout_order",
    "get_or_create_basket",
    "remove_item",
    "transition",
    "update_item_quantity",
)
