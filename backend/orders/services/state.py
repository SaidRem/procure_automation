"""Граф состояний заказа (ADR-022).

Допустимые переходы заданы одной структурой данных и проверяются одной
функцией: дублирование правил по сервисам — тот путь, которым граф
расходится с реальностью.

Схема хранит только текущее состояние; переходы в базе не выражаются.
Модуль не знает, кто инициирует переход: право инициатора проверяет
вызывающий сервис (покупатель оформляет заказ, администратор ведёт его
дальше).
"""

from __future__ import annotations

import logging

from django.db import transaction

from orders.models import Order, OrderState
from orders.services.exceptions import InvalidStateTransition

logger = logging.getLogger(__name__)

# Ключ — текущее состояние, значение — состояния, в которые из него
# можно перейти. Отсутствие состояния среди значений означает, что
# войти в него нельзя: так выражен запрет возврата в `basket`.
# Пустое множество — терминальное состояние.
TRANSITIONS: dict[str, frozenset[str]] = {
    OrderState.BASKET: frozenset({OrderState.NEW}),
    OrderState.NEW: frozenset({OrderState.CONFIRMED, OrderState.CANCELED}),
    OrderState.CONFIRMED: frozenset({OrderState.ASSEMBLED, OrderState.CANCELED}),
    OrderState.ASSEMBLED: frozenset({OrderState.SENT, OrderState.CANCELED}),
    OrderState.SENT: frozenset({OrderState.DELIVERED}),
    OrderState.DELIVERED: frozenset(),
    OrderState.CANCELED: frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    """Проверить, предусмотрен ли переход `current` -> `target`."""
    return target in TRANSITIONS.get(current, frozenset())


def transition(order: Order, target: str, *, save: bool = True) -> Order:
    """Перевести заказ в состояние `target`.

    Недопустимый переход — ошибка, а не молчаливое игнорирование:
    иначе заказ остался бы в прежнем состоянии, а вызывающий код счёл
    бы операцию выполненной.

    `save=False` оставляет сохранение вызывающему сервису: оформление
    заказа меняет состояние вместе со snapshot-полями и делает это
    одним `save()` внутри своей транзакции.
    """
    if not can_transition(order.state, target):
        raise InvalidStateTransition(order.state, target)

    previous, order.state = order.state, target

    if save:
        with transaction.atomic():
            order.save(update_fields=["state"])

    logger.info(
        "Order state changed: order_id=%s %s -> %s", order.pk, previous, target
    )
    return order
