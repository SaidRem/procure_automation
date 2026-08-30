"""Тесты графа состояний заказа (ADR-022)."""

from __future__ import annotations

import pytest

from orders.models import Order, OrderState
from orders.services import InvalidStateTransition, can_transition, transition
from orders.services.state import TRANSITIONS


class TestTransitionGraph:
    """Граф переходов задан одной структурой данных."""

    @pytest.mark.parametrize(
        ("current", "target"),
        (
            (OrderState.BASKET, OrderState.NEW),
            (OrderState.NEW, OrderState.CONFIRMED),
            (OrderState.CONFIRMED, OrderState.ASSEMBLED),
            (OrderState.ASSEMBLED, OrderState.SENT),
            (OrderState.SENT, OrderState.DELIVERED),
            (OrderState.NEW, OrderState.CANCELED),
            (OrderState.CONFIRMED, OrderState.CANCELED),
            (OrderState.ASSEMBLED, OrderState.CANCELED),
        ),
    )
    def test_allowed_transitions(self, current, target) -> None:
        assert can_transition(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        (
            # Возврат в корзину запрещён: он нарушил бы уникальность
            # корзины у покупателя с уже собранной новой.
            (OrderState.NEW, OrderState.BASKET),
            (OrderState.CANCELED, OrderState.BASKET),
            # Пропуск состояний вперёд.
            (OrderState.NEW, OrderState.SENT),
            (OrderState.CONFIRMED, OrderState.DELIVERED),
            (OrderState.BASKET, OrderState.CONFIRMED),
            # Возврат назад по цепочке.
            (OrderState.CONFIRMED, OrderState.NEW),
            (OrderState.SENT, OrderState.ASSEMBLED),
            # Выход из терминальных состояний.
            (OrderState.DELIVERED, OrderState.CANCELED),
            (OrderState.CANCELED, OrderState.NEW),
            # Переход в то же состояние.
            (OrderState.CONFIRMED, OrderState.CONFIRMED),
        ),
    )
    def test_forbidden_transitions(self, current, target) -> None:
        assert not can_transition(current, target)

    def test_terminal_states_have_no_exits(self) -> None:
        assert TRANSITIONS[OrderState.DELIVERED] == frozenset()
        assert TRANSITIONS[OrderState.CANCELED] == frozenset()

    def test_basket_is_unreachable(self) -> None:
        """Ни один переход не ведёт в basket."""
        assert not any(
            OrderState.BASKET in targets for targets in TRANSITIONS.values()
        )

    def test_graph_covers_all_states(self) -> None:
        assert set(TRANSITIONS) == set(OrderState.values)


@pytest.mark.django_db
class TestTransition:
    """transition()."""

    def test_applies_and_saves(self, buyer) -> None:
        order = Order.objects.create(user=buyer, state=OrderState.NEW)

        transition(order, OrderState.CONFIRMED)
        order.refresh_from_db()

        assert order.state == OrderState.CONFIRMED

    def test_rejects_forbidden_transition(self, buyer) -> None:
        order = Order.objects.create(user=buyer, state=OrderState.NEW)

        with pytest.raises(InvalidStateTransition):
            transition(order, OrderState.DELIVERED)

        order.refresh_from_db()
        assert order.state == OrderState.NEW

    def test_save_false_leaves_write_to_caller(self, buyer) -> None:
        """Оформление заказа пишет состояние вместе со snapshot."""
        order = Order.objects.create(user=buyer, state=OrderState.NEW)

        transition(order, OrderState.CONFIRMED, save=False)

        assert order.state == OrderState.CONFIRMED
        order.refresh_from_db()
        assert order.state == OrderState.NEW
