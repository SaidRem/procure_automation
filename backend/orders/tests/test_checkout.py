"""Тесты оформления заказа (ADR-022, ADR-024, ADR-025, ADR-027)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from orders.models import Order, OrderState
from orders.services import (
    ContactNotFound,
    EmptyBasket,
    IncompleteRecipientData,
    InsufficientStock,
    OfferGone,
    OfferInactive,
    ShopNotAcceptingOrders,
    add_item,
    checkout_order,
    get_or_create_basket,
)


@pytest.mark.django_db
class TestCheckoutTransition:
    """Переход basket -> new."""

    def test_basket_becomes_new(self, buyer, contact, product_info) -> None:
        basket = get_or_create_basket(buyer)
        add_item(buyer, product_info, 2)

        order = checkout_order(buyer, contact.pk)

        assert order.pk == basket.pk
        assert order.state == OrderState.NEW
        assert order.confirmed_at is not None
        assert order.contact == contact

    def test_basket_is_freed_after_checkout(self, buyer, contact, product_info) -> None:
        """Оформленный заказ перестаёт быть корзиной (ADR-009)."""
        add_item(buyer, product_info, 1)
        order = checkout_order(buyer, contact.pk)

        assert Order.objects.baskets().filter(user=buyer).count() == 0
        assert list(Order.objects.orders()) == [order]
        assert get_or_create_basket(buyer).pk != order.pk

    def test_empty_basket_is_rejected(self, buyer, contact) -> None:
        with pytest.raises(EmptyBasket):
            checkout_order(buyer, contact.pk)

        assert get_or_create_basket(buyer).state == OrderState.BASKET


@pytest.mark.django_db
class TestCheckoutContact:
    """Проверки контакта (ADR-024, ADR-027)."""

    def test_foreign_contact_is_rejected(
        self, buyer, other_buyer, product_info
    ) -> None:
        """Snapshot снимается только со своего адреса."""
        from users.models import Contact

        foreign = Contact.objects.create(
            user=other_buyer,
            last_name="Иванов",
            first_name="Иван",
            city="Тверь",
            street="Ленина",
            phone="+70000000001",
        )
        add_item(buyer, product_info, 1)

        with pytest.raises(ContactNotFound):
            checkout_order(buyer, foreign.pk)

    def test_unknown_contact_is_rejected(self, buyer, product_info) -> None:
        add_item(buyer, product_info, 1)

        with pytest.raises(ContactNotFound):
            checkout_order(buyer, 10_000)

    def test_incomplete_recipient_is_rejected(
        self, buyer, incomplete_contact, product_info
    ) -> None:
        """Контакт без ФИО оформить заказ не позволяет (ADR-027)."""
        add_item(buyer, product_info, 1)

        with pytest.raises(IncompleteRecipientData) as error:
            checkout_order(buyer, incomplete_contact.pk)

        assert error.value.fields == ("last_name", "first_name")
        assert get_or_create_basket(buyer).state == OrderState.BASKET

    def test_missing_email_does_not_block_checkout(
        self, buyer, contact, product_info
    ) -> None:
        """Email получателя необязателен (ADR-027)."""
        contact.email = ""
        contact.save(update_fields=["email"])
        add_item(buyer, product_info, 1)

        order = checkout_order(buyer, contact.pk)

        assert order.state == OrderState.NEW
        assert order.delivery_email == ""


@pytest.mark.django_db
class TestDeliverySnapshot:
    """Snapshot получателя и адреса (ADR-024, ADR-027)."""

    def test_snapshot_is_filled(self, buyer, contact, product_info) -> None:
        add_item(buyer, product_info, 1)

        order = checkout_order(buyer, contact.pk)

        assert order.delivery_last_name == contact.last_name
        assert order.delivery_first_name == contact.first_name
        assert order.delivery_middle_name == contact.middle_name
        assert order.delivery_email == contact.email
        assert order.delivery_phone == contact.phone
        assert order.delivery_city == contact.city
        assert order.delivery_street == contact.street
        assert order.delivery_house == contact.house

    def test_snapshot_survives_contact_change(
        self, buyer, contact, product_info
    ) -> None:
        add_item(buyer, product_info, 1)
        order = checkout_order(buyer, contact.pk)

        contact.city = "Тверь"
        contact.last_name = "Сидоров"
        contact.save()
        order.refresh_from_db()

        assert order.delivery_city == "Москва"
        assert order.delivery_last_name == "Петров"

    def test_snapshot_survives_contact_deletion(
        self, buyer, contact, product_info
    ) -> None:
        add_item(buyer, product_info, 1)
        order = checkout_order(buyer, contact.pk)

        contact.delete()
        order.refresh_from_db()

        assert order.contact is None
        assert order.delivery_city == "Москва"

    def test_recipient_is_not_taken_from_account(
        self, buyer, contact, product_info
    ) -> None:
        """Получатель — из контакта, а не из учётной записи (ADR-027)."""
        add_item(buyer, product_info, 1)

        order = checkout_order(buyer, contact.pk)

        assert order.delivery_email != buyer.email


@pytest.mark.django_db
class TestItemSnapshot:
    """Snapshot позиций заказа (ADR-003)."""

    def test_item_snapshot_is_filled(self, buyer, contact, product_info) -> None:
        add_item(buyer, product_info, 2)

        order = checkout_order(buyer, contact.pk)
        item = order.items.get()

        assert item.product_name == product_info.product.name
        assert item.shop_name == product_info.shop.name
        assert item.price == product_info.price
        assert item.price_rrc == product_info.price_rrc
        assert item.quantity == 2

    def test_snapshot_is_decimal(self, buyer, contact, product_info) -> None:
        add_item(buyer, product_info, 1)

        item = checkout_order(buyer, contact.pk).items.get()

        assert isinstance(item.price, Decimal)
        assert item.price == Decimal("110000.00")

    def test_snapshot_survives_price_change(
        self, buyer, contact, product_info
    ) -> None:
        """Импорт прайса не переписывает оформленный заказ (ADR-003)."""
        add_item(buyer, product_info, 1)
        order = checkout_order(buyer, contact.pk)

        product_info.price = Decimal("1.00")
        product_info.save(update_fields=["price"])
        item = order.items.get()

        assert item.price == Decimal("110000.00")

    def test_all_items_get_snapshot(
        self, buyer, contact, product_info, other_product_info
    ) -> None:
        add_item(buyer, product_info, 1)
        add_item(buyer, other_product_info, 2)

        order = checkout_order(buyer, contact.pk)

        assert order.items.count() == 2
        assert all(item.price is not None for item in order.items.all())
        assert {item.product_name for item in order.items.all()} == {
            product_info.product.name,
            other_product_info.product.name,
        }


@pytest.mark.django_db
class TestCheckoutAvailability:
    """Повторная проверка доступности при оформлении (ADR-025)."""

    def test_offer_deactivated_after_adding_blocks_checkout(
        self, buyer, contact, product_info
    ) -> None:
        add_item(buyer, product_info, 1)
        product_info.is_active = False
        product_info.save(update_fields=["is_active"])

        with pytest.raises(OfferInactive):
            checkout_order(buyer, contact.pk)

        assert get_or_create_basket(buyer).state == OrderState.BASKET

    def test_shop_disabled_after_adding_blocks_checkout(
        self, buyer, contact, product_info, shop
    ) -> None:
        add_item(buyer, product_info, 1)
        shop.state = False
        shop.save(update_fields=["state"])

        with pytest.raises(ShopNotAcceptingOrders):
            checkout_order(buyer, contact.pk)

    def test_stock_drop_after_adding_blocks_checkout(
        self, buyer, contact, product_info
    ) -> None:
        add_item(buyer, product_info, 5)
        product_info.quantity = 2
        product_info.save(update_fields=["quantity"])

        with pytest.raises(InsufficientStock):
            checkout_order(buyer, contact.pk)

    def test_deleted_offer_blocks_checkout(
        self, buyer, contact, product_info
    ) -> None:
        """Позиция с обнулённой ссылкой не оформляется (SET_NULL)."""
        add_item(buyer, product_info, 1)
        product_info.delete()

        with pytest.raises(OfferGone):
            checkout_order(buyer, contact.pk)

    def test_failed_checkout_leaves_no_snapshot(
        self, buyer, contact, product_info
    ) -> None:
        """Отказ откатывает транзакцию целиком: частичного заказа нет."""
        add_item(buyer, product_info, 1)
        product_info.is_active = False
        product_info.save(update_fields=["is_active"])

        with pytest.raises(OfferInactive):
            checkout_order(buyer, contact.pk)

        basket = get_or_create_basket(buyer)
        item = basket.items.get()

        assert basket.delivery_city == ""
        assert basket.confirmed_at is None
        assert basket.contact is None
        assert item.price is None
        assert item.product_name == ""


@pytest.mark.django_db
class TestStockIsNotReserved:
    """Остатки не списываются и не резервируются (ADR-022, ADR-008)."""

    def test_checkout_does_not_change_stock(
        self, buyer, contact, product_info
    ) -> None:
        before = product_info.quantity
        add_item(buyer, product_info, 3)

        checkout_order(buyer, contact.pk)
        product_info.refresh_from_db()

        assert product_info.quantity == before

    def test_two_buyers_can_order_the_same_stock(
        self, buyer, other_buyer, contact, product_info
    ) -> None:
        """Резерва нет: остаток проверяется, но не удерживается."""
        from users.models import Contact

        other_contact = Contact.objects.create(
            user=other_buyer,
            last_name="Иванов",
            first_name="Иван",
            city="Тверь",
            street="Ленина",
            phone="+70000000001",
        )
        add_item(buyer, product_info, product_info.quantity)
        add_item(other_buyer, product_info, product_info.quantity)

        checkout_order(buyer, contact.pk)
        checkout_order(other_buyer, other_contact.pk)
        product_info.refresh_from_db()

        assert Order.objects.orders().count() == 2
        assert product_info.quantity == 14
