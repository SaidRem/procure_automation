"""Тесты API оформления и истории заказов."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from orders.models import Order, OrderState
from orders.services import add_item, checkout_order, get_or_create_basket

CHECKOUT_URL = reverse("orders:checkout")
ORDERS_URL = reverse("orders:order-list")


def order_url(order: Order) -> str:
    return reverse("orders:order-detail", args=[order.pk])


@pytest.mark.django_db
class TestCheckout:
    """POST /api/orders/checkout/."""

    def test_places_order(self, auth_client, buyer, contact, product_info) -> None:
        add_item(buyer, product_info, 2)

        response = auth_client.post(
            CHECKOUT_URL, {"contact": contact.pk}, format="json"
        )

        assert response.status_code == 201
        assert response.data["state"] == OrderState.NEW
        assert response.data["confirmed_at"] is not None
        assert Decimal(response.data["total"]) == product_info.price * 2

    def test_response_contains_item_snapshot(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        add_item(buyer, product_info, 2)

        item = auth_client.post(
            CHECKOUT_URL, {"contact": contact.pk}, format="json"
        ).data["items"][0]

        assert item["product_name"] == product_info.product.name
        assert item["shop_name"] == product_info.shop.name
        assert Decimal(item["price"]) == product_info.price
        assert Decimal(item["total"]) == product_info.price * 2

    def test_response_contains_delivery_snapshot(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        add_item(buyer, product_info, 1)

        delivery = auth_client.post(
            CHECKOUT_URL, {"contact": contact.pk}, format="json"
        ).data["delivery"]

        assert delivery["last_name"] == contact.last_name
        assert delivery["first_name"] == contact.first_name
        assert delivery["middle_name"] == contact.middle_name
        assert delivery["email"] == contact.email
        assert delivery["city"] == contact.city
        assert delivery["street"] == contact.street

    def test_snapshot_survives_catalog_change(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        """Импорт прайса не переписывает оформленный заказ (ADR-003)."""
        add_item(buyer, product_info, 1)
        order_id = auth_client.post(
            CHECKOUT_URL, {"contact": contact.pk}, format="json"
        ).data["id"]

        product_info.price = Decimal("1.00")
        product_info.save(update_fields=["price"])
        response = auth_client.get(order_url(Order.objects.get(pk=order_id)))

        assert Decimal(response.data["items"][0]["price"]) == Decimal("110000.00")

    def test_cart_is_empty_after_checkout(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        add_item(buyer, product_info, 1)
        auth_client.post(CHECKOUT_URL, {"contact": contact.pk}, format="json")

        assert auth_client.get(reverse("orders:cart")).data["items"] == []

    def test_empty_cart_is_rejected(self, auth_client, contact) -> None:
        response = auth_client.post(
            CHECKOUT_URL, {"contact": contact.pk}, format="json"
        )

        assert response.status_code == 400

    def test_foreign_contact_is_rejected(
        self, auth_client, buyer, other_contact, product_info
    ) -> None:
        """Оформить заказ на чужой контакт нельзя (ADR-024)."""
        add_item(buyer, product_info, 1)

        response = auth_client.post(
            CHECKOUT_URL, {"contact": other_contact.pk}, format="json"
        )

        assert response.status_code == 400
        assert "contact" in response.data
        assert get_or_create_basket(buyer).state == OrderState.BASKET

    def test_unknown_contact_is_rejected(self, auth_client, buyer, product_info) -> None:
        add_item(buyer, product_info, 1)

        response = auth_client.post(CHECKOUT_URL, {"contact": 10_000}, format="json")

        assert response.status_code == 400
        assert "contact" in response.data

    def test_incomplete_contact_lists_missing_fields(
        self, auth_client, buyer, incomplete_contact, product_info
    ) -> None:
        """Покупателю сообщается, что именно дописать (ADR-027)."""
        add_item(buyer, product_info, 1)

        response = auth_client.post(
            CHECKOUT_URL, {"contact": incomplete_contact.pk}, format="json"
        )

        assert response.status_code == 400
        assert response.data["fields"] == ["last_name", "first_name"]

    def test_unavailable_offer_blocks_checkout(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        add_item(buyer, product_info, 1)
        product_info.is_active = False
        product_info.save(update_fields=["is_active"])

        response = auth_client.post(
            CHECKOUT_URL, {"contact": contact.pk}, format="json"
        )

        assert response.status_code == 409
        assert response.data["code"] == "offer_inactive"

    def test_deleted_offer_blocks_checkout(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        """Товар исчез из каталога после добавления в корзину."""
        add_item(buyer, product_info, 1)
        product_info.delete()

        response = auth_client.post(
            CHECKOUT_URL, {"contact": contact.pk}, format="json"
        )

        assert response.status_code == 409
        assert response.data["code"] == "offer_gone"

    def test_stock_is_not_changed(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        """Остатки не списываются и не резервируются (ADR-022)."""
        before = product_info.quantity
        add_item(buyer, product_info, 3)

        auth_client.post(CHECKOUT_URL, {"contact": contact.pk}, format="json")
        product_info.refresh_from_db()

        assert product_info.quantity == before

    def test_anonymous_access_is_denied(self, api_client, contact) -> None:
        assert api_client.post(
            CHECKOUT_URL, {"contact": contact.pk}, format="json"
        ).status_code == 401


@pytest.mark.django_db
class TestOrderHistory:
    """GET /api/orders/ и /api/orders/{id}/."""

    def test_lists_own_orders(self, auth_client, buyer, contact, product_info) -> None:
        add_item(buyer, product_info, 1)
        order = checkout_order(buyer, contact.pk)

        response = auth_client.get(ORDERS_URL)

        assert response.status_code == 200
        assert [item["id"] for item in response.data["results"]] == [order.pk]

    def test_history_fields(self, auth_client, buyer, contact, product_info) -> None:
        """Спецификация: номер, дата, сумма, статус (private/screens.md)."""
        add_item(buyer, product_info, 2)
        checkout_order(buyer, contact.pk)

        item = auth_client.get(ORDERS_URL).data["results"][0]

        assert set(item) == {"id", "confirmed_at", "state", "total"}
        assert item["state"] == OrderState.NEW
        assert Decimal(item["total"]) == product_info.price * 2

    def test_basket_is_not_in_history(
        self, auth_client, buyer, product_info
    ) -> None:
        """Корзина не должна попадать в историю заказов (ADR-009)."""
        add_item(buyer, product_info, 1)

        assert auth_client.get(ORDERS_URL).data["count"] == 0

    def test_foreign_orders_are_not_listed(
        self, auth_client, other_buyer, other_contact, product_info
    ) -> None:
        add_item(other_buyer, product_info, 1)
        checkout_order(other_buyer, other_contact.pk)

        assert auth_client.get(ORDERS_URL).data["count"] == 0

    def test_foreign_order_is_not_accessible(
        self, auth_client, other_buyer, other_contact, product_info
    ) -> None:
        add_item(other_buyer, product_info, 1)
        foreign = checkout_order(other_buyer, other_contact.pk)

        assert auth_client.get(order_url(foreign)).status_code == 404

    def test_detail_contains_items_and_delivery(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        add_item(buyer, product_info, 1)
        order = checkout_order(buyer, contact.pk)

        response = auth_client.get(order_url(order))

        assert response.status_code == 200
        assert len(response.data["items"]) == 1
        assert response.data["delivery"]["city"] == contact.city

    def test_delivery_survives_contact_deletion(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        """Удаление контакта не меняет историю заказа (ADR-024)."""
        add_item(buyer, product_info, 1)
        order = checkout_order(buyer, contact.pk)
        contact.delete()

        response = auth_client.get(order_url(order))

        assert response.data["delivery"]["city"] == "Москва"
        assert response.data["delivery"]["last_name"] == "Петров"

    def test_delete_is_not_allowed(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        """Заказ не удаляется: маршрута нет (ADR-022)."""
        add_item(buyer, product_info, 1)
        order = checkout_order(buyer, contact.pk)

        assert auth_client.delete(order_url(order)).status_code == 405
        assert Order.objects.filter(pk=order.pk).exists()

    def test_anonymous_access_is_denied(self, api_client) -> None:
        assert api_client.get(ORDERS_URL).status_code == 401
