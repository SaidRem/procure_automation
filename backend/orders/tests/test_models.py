"""Тесты моделей приложения orders."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.utils import timezone

from orders.models import Order, OrderItem, OrderState

SNAPSHOT = {
    "delivery_last_name": "Петров",
    "delivery_first_name": "Пётр",
    "delivery_middle_name": "Петрович",
    "delivery_email": "recipient@example.com",
    "delivery_phone": "+70000000000",
    "delivery_city": "Москва",
    "delivery_street": "Тверская",
    "delivery_house": "1",
    "delivery_structure": "2",
    "delivery_building": "3",
    "delivery_apartment": "4",
}


@pytest.mark.django_db
class TestOrderCreation:
    """Создание заказа и корзины."""

    def test_new_order_is_a_basket_by_default(self, buyer) -> None:
        """Корзина — начальное состояние заказа (ADR-022)."""
        order = Order.objects.create(user=buyer)

        assert order.state == OrderState.BASKET
        assert order.confirmed_at is None
        assert order.contact is None
        assert order.dt is not None

    def test_create_confirmed_order(self, buyer, contact) -> None:
        confirmed_at = timezone.now()

        order = Order.objects.create(
            user=buyer,
            contact=contact,
            state=OrderState.NEW,
            confirmed_at=confirmed_at,
            **SNAPSHOT,
        )
        order.refresh_from_db()

        assert order.state == OrderState.NEW
        assert order.confirmed_at == confirmed_at
        assert order in buyer.orders.all()

    def test_basket_snapshot_is_empty(self, buyer) -> None:
        """Snapshot заполняется при оформлении, у корзины пуст (ADR-024)."""
        order = Order.objects.create(user=buyer)

        for field in SNAPSHOT:
            assert getattr(order, field) == ""

    def test_str_contains_state(self, buyer) -> None:
        order = Order.objects.create(user=buyer)

        assert "Корзина" in str(order)

    def test_order_deletion_is_forbidden(self, buyer) -> None:
        """Заказ — историческая запись, отмена выражается состоянием."""
        order = Order.objects.create(user=buyer, state=OrderState.NEW)

        with pytest.raises(ProtectedError):
            order.delete()

        assert Order.objects.filter(pk=order.pk).exists()

    def test_basket_deletion_is_forbidden(self, buyer) -> None:
        """Корзина — это заказ: опустошение удаляет позиции, не запись."""
        basket = Order.objects.create(user=buyer)

        with pytest.raises(ProtectedError):
            basket.delete()


@pytest.mark.django_db
class TestBasketUniqueness:
    """Не более одной корзины на пользователя (ADR-009)."""

    def test_second_basket_is_rejected(self, buyer) -> None:
        Order.objects.create(user=buyer)

        with pytest.raises(IntegrityError):
            Order.objects.create(user=buyer)

    def test_different_users_have_own_baskets(self, buyer, other_buyer) -> None:
        first = Order.objects.create(user=buyer)
        second = Order.objects.create(user=other_buyer)

        assert Order.objects.baskets().count() == 2
        assert first.pk != second.pk

    def test_many_placed_orders_are_allowed(self, buyer) -> None:
        """Ограничение частичное: оформленных заказов сколько угодно."""
        Order.objects.create(user=buyer, state=OrderState.NEW)
        Order.objects.create(user=buyer, state=OrderState.DELIVERED)
        Order.objects.create(user=buyer)

        assert Order.objects.filter(user=buyer).count() == 3

    def test_basket_becomes_free_after_checkout(self, buyer) -> None:
        """Оформление корзины освобождает место под новую."""
        basket = Order.objects.create(user=buyer)
        basket.state = OrderState.NEW
        basket.save(update_fields=["state"])

        assert Order.objects.create(user=buyer).pk != basket.pk


@pytest.mark.django_db
class TestOrderState:
    """Закрытый набор состояний (ADR-022)."""

    def test_all_states_are_accepted(self, buyer, other_buyer) -> None:
        # Корзина одна на пользователя, поэтому basket проверяется
        # на отдельном пользователе.
        Order.objects.create(user=other_buyer, state=OrderState.BASKET)

        for state in OrderState.values:
            if state == OrderState.BASKET:
                continue
            order = Order.objects.create(user=buyer, state=state)
            assert order.state == state

    def test_unknown_state_is_rejected_by_database(self, buyer) -> None:
        with pytest.raises(IntegrityError):
            Order.objects.create(user=buyer, state="shipped")

    def test_unknown_state_is_rejected_by_full_clean(self, buyer) -> None:
        order = Order(user=buyer, state="shipped")

        with pytest.raises(ValidationError):
            order.full_clean()

    def test_state_choices_match_adr_022(self) -> None:
        assert OrderState.values == [
            "basket",
            "new",
            "confirmed",
            "assembled",
            "sent",
            "delivered",
            "canceled",
        ]

    def test_orders_queryset_excludes_baskets(self, buyer) -> None:
        """Корзина не должна попадать в историю заказов (ADR-009)."""
        Order.objects.create(user=buyer)
        placed = Order.objects.create(user=buyer, state=OrderState.NEW)

        assert list(Order.objects.orders()) == [placed]


@pytest.mark.django_db
class TestDeliverySnapshot:
    """Историчность получателя и адреса (ADR-024, ADR-027)."""

    def test_snapshot_is_stored(self, buyer, contact) -> None:
        order = Order.objects.create(
            user=buyer, contact=contact, state=OrderState.NEW, **SNAPSHOT
        )
        order.refresh_from_db()

        for field, value in SNAPSHOT.items():
            assert getattr(order, field) == value

    def test_contact_change_does_not_affect_order(self, buyer, contact) -> None:
        order = Order.objects.create(
            user=buyer, contact=contact, state=OrderState.NEW, **SNAPSHOT
        )

        contact.city = "Тверь"
        contact.last_name = "Сидоров"
        contact.save()
        order.refresh_from_db()

        assert order.delivery_city == "Москва"
        assert order.delivery_last_name == "Петров"

    def test_contact_deletion_keeps_order(self, buyer, contact) -> None:
        """Удаление контакта не удаляет заказ и не меняет snapshot."""
        order = Order.objects.create(
            user=buyer, contact=contact, state=OrderState.NEW, **SNAPSHOT
        )

        contact.delete()
        order.refresh_from_db()

        assert Order.objects.filter(pk=order.pk).exists()
        assert order.contact is None
        assert order.delivery_city == "Москва"
        assert order.delivery_last_name == "Петров"

    def test_snapshot_is_independent_of_user(self, buyer, contact) -> None:
        """Получатель не выводится из учётной записи (ADR-027)."""
        order = Order.objects.create(
            user=buyer, contact=contact, state=OrderState.NEW, **SNAPSHOT
        )

        assert order.delivery_email != buyer.email

    def test_user_with_orders_is_protected(self, buyer) -> None:
        """История заказов не исчезает вместе с пользователем."""
        Order.objects.create(user=buyer, state=OrderState.NEW)

        with pytest.raises(ProtectedError):
            buyer.delete()


@pytest.mark.django_db
class TestOrderItem:
    """Позиции заказа и snapshot товара (ADR-003)."""

    def test_create_item_in_basket(self, buyer, product_info) -> None:
        order = Order.objects.create(user=buyer)

        item = OrderItem.objects.create(
            order=order, product_info=product_info, quantity=2
        )

        assert item in order.items.all()
        assert item.product_name == ""
        assert item.price is None

    def test_snapshot_is_stored(self, buyer, product_info) -> None:
        order = Order.objects.create(user=buyer, state=OrderState.NEW)

        item = OrderItem.objects.create(
            order=order,
            product_info=product_info,
            quantity=2,
            product_name="Смартфон Apple iPhone XS Max",
            shop_name="Связной",
            price=Decimal("110000.00"),
            price_rrc=Decimal("116990.00"),
        )
        item.refresh_from_db()

        assert item.product_name == "Смартфон Apple iPhone XS Max"
        assert item.shop_name == "Связной"
        assert item.price == Decimal("110000.00")
        assert item.price_rrc == Decimal("116990.00")

    def test_money_fields_are_decimal(self, buyer, product_info) -> None:
        """Денежные значения — Decimal, float не используется (ADR-015)."""
        order = Order.objects.create(user=buyer, state=OrderState.NEW)
        OrderItem.objects.create(
            order=order,
            product_info=product_info,
            quantity=1,
            price=Decimal("110000.55"),
            price_rrc=Decimal("116990.99"),
        )

        item = OrderItem.objects.get(order=order)

        assert isinstance(item.price, Decimal)
        assert isinstance(item.price_rrc, Decimal)
        assert item.price == Decimal("110000.55")

    def test_product_info_deletion_keeps_item(self, buyer, product_info) -> None:
        """Позиция переживает удаление предложения (ADR-003)."""
        order = Order.objects.create(user=buyer, state=OrderState.NEW)
        item = OrderItem.objects.create(
            order=order,
            product_info=product_info,
            quantity=2,
            product_name="Смартфон Apple iPhone XS Max",
            shop_name="Связной",
            price=Decimal("110000.00"),
            price_rrc=Decimal("116990.00"),
        )

        product_info.delete()
        item.refresh_from_db()

        assert OrderItem.objects.filter(pk=item.pk).exists()
        assert item.product_info is None
        assert item.product_name == "Смартфон Apple iPhone XS Max"
        assert item.price == Decimal("110000.00")

    def test_same_offer_twice_is_rejected(self, buyer, product_info) -> None:
        """Повторное добавление увеличивает количество, а не строку."""
        order = Order.objects.create(user=buyer)
        OrderItem.objects.create(order=order, product_info=product_info, quantity=1)

        with pytest.raises(IntegrityError):
            OrderItem.objects.create(order=order, product_info=product_info, quantity=3)

    def test_same_offer_in_different_orders_is_allowed(
        self, buyer, other_buyer, product_info
    ) -> None:
        first = Order.objects.create(user=buyer)
        second = Order.objects.create(user=other_buyer)

        OrderItem.objects.create(order=first, product_info=product_info, quantity=1)
        OrderItem.objects.create(order=second, product_info=product_info, quantity=1)

        assert OrderItem.objects.count() == 2

    def test_zero_quantity_is_rejected(self, buyer, product_info) -> None:
        order = Order.objects.create(user=buyer)

        with pytest.raises(IntegrityError):
            OrderItem.objects.create(order=order, product_info=product_info, quantity=0)

    def test_basket_item_can_be_removed(self, buyer, product_info) -> None:
        """Удаление товара из корзины — требование спецификации."""
        order = Order.objects.create(user=buyer)
        item = OrderItem.objects.create(
            order=order, product_info=product_info, quantity=1
        )

        item.delete()

        assert order.items.count() == 0

    def test_item_of_placed_order_is_protected(self, buyer, product_info) -> None:
        """Позиция оформленного заказа входит в накладную (ADR-022)."""
        order = Order.objects.create(user=buyer, state=OrderState.NEW)
        item = OrderItem.objects.create(
            order=order, product_info=product_info, quantity=1
        )

        with pytest.raises(ProtectedError):
            item.delete()

        assert OrderItem.objects.filter(pk=item.pk).exists()

    def test_items_of_deleted_offer_do_not_collide(self, buyer, product_info) -> None:
        """После SET_NULL уникальность не мешает истории.

        NULL в PostgreSQL не конфликтует с NULL, поэтому позиции с
        обнулённой ссылкой сосуществуют в одном заказе.
        """
        order = Order.objects.create(user=buyer, state=OrderState.NEW)
        OrderItem.objects.create(
            order=order, product_info=product_info, quantity=1, product_name="Первый"
        )
        OrderItem.objects.create(order=order, product_info=None, quantity=1, product_name="Второй")

        product_info.delete()

        assert order.items.count() == 2
        assert list(order.items.values_list("product_info", flat=True)) == [None, None]
