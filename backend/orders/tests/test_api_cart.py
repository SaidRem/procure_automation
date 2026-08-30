"""Тесты API корзины."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from orders.models import Order, OrderItem
from orders.services import add_item, get_or_create_basket

CART_URL = reverse("orders:cart")
ITEMS_URL = reverse("orders:cart-items")


def item_url(item: OrderItem) -> str:
    return reverse("orders:cart-item", args=[item.pk])


@pytest.mark.django_db
class TestGetCart:
    """GET /api/orders/cart/."""

    def test_creates_empty_cart_on_first_request(self, auth_client, buyer) -> None:
        response = auth_client.get(CART_URL)

        assert response.status_code == 200
        assert response.data["items"] == []
        assert response.data["total"] == Decimal("0.00")
        assert Order.objects.baskets().filter(user=buyer).count() == 1

    def test_returns_items_with_current_prices(
        self, auth_client, buyer, product_info
    ) -> None:
        """В корзине цена берётся из каталога, а не из snapshot (ADR-009)."""
        add_item(buyer, product_info, 2)

        item = auth_client.get(CART_URL).data["items"][0]

        assert item["product_name"] == product_info.product.name
        assert item["shop"] == product_info.shop.name
        assert Decimal(item["price"]) == product_info.price
        assert item["quantity"] == 2
        assert Decimal(item["total"]) == product_info.price * 2

    def test_total_sums_items(
        self, auth_client, buyer, product_info, other_product_info
    ) -> None:
        add_item(buyer, product_info, 1)
        add_item(buyer, other_product_info, 2)

        total = auth_client.get(CART_URL).data["total"]

        assert Decimal(total) == product_info.price + other_product_info.price * 2

    def test_price_change_is_reflected(self, auth_client, buyer, product_info) -> None:
        add_item(buyer, product_info, 1)
        product_info.price = Decimal("999.00")
        product_info.save(update_fields=["price"])

        assert Decimal(auth_client.get(CART_URL).data["total"]) == Decimal("999.00")

    def test_carts_are_isolated(
        self, auth_client, other_client, buyer, product_info
    ) -> None:
        add_item(buyer, product_info, 1)

        assert other_client.get(CART_URL).data["items"] == []

    def test_anonymous_access_is_denied(self, api_client) -> None:
        assert api_client.get(CART_URL).status_code == 401


@pytest.mark.django_db
class TestAddItem:
    """POST /api/orders/cart/items/."""

    def test_adds_item(self, auth_client, buyer, product_info) -> None:
        response = auth_client.post(
            ITEMS_URL, {"product_info": product_info.pk, "quantity": 2}, format="json"
        )

        assert response.status_code == 201
        assert response.data["quantity"] == 2
        assert get_or_create_basket(buyer).items.count() == 1

    def test_repeated_add_increases_quantity(
        self, auth_client, product_info
    ) -> None:
        payload = {"product_info": product_info.pk, "quantity": 2}
        auth_client.post(ITEMS_URL, payload, format="json")

        response = auth_client.post(ITEMS_URL, payload, format="json")

        assert response.data["quantity"] == 4
        assert OrderItem.objects.count() == 1

    @pytest.mark.parametrize("quantity", (0, -1))
    def test_non_positive_quantity_is_rejected(
        self, auth_client, product_info, quantity
    ) -> None:
        response = auth_client.post(
            ITEMS_URL,
            {"product_info": product_info.pk, "quantity": quantity},
            format="json",
        )

        assert response.status_code == 400
        assert "quantity" in response.data

    def test_unknown_offer_is_rejected(self, auth_client) -> None:
        response = auth_client.post(
            ITEMS_URL, {"product_info": 10_000, "quantity": 1}, format="json"
        )

        assert response.status_code == 400
        assert "product_info" in response.data

    def test_inactive_offer_is_rejected(self, auth_client, product_info) -> None:
        product_info.is_active = False
        product_info.save(update_fields=["is_active"])

        response = auth_client.post(
            ITEMS_URL, {"product_info": product_info.pk, "quantity": 1}, format="json"
        )

        assert response.status_code == 409
        assert response.data["code"] == "offer_inactive"

    def test_disabled_shop_is_rejected(self, auth_client, product_info, shop) -> None:
        shop.state = False
        shop.save(update_fields=["state"])

        response = auth_client.post(
            ITEMS_URL, {"product_info": product_info.pk, "quantity": 1}, format="json"
        )

        assert response.status_code == 409
        assert response.data["code"] == "shop_not_accepting_orders"

    def test_insufficient_stock_is_rejected(self, auth_client, product_info) -> None:
        response = auth_client.post(
            ITEMS_URL,
            {"product_info": product_info.pk, "quantity": product_info.quantity + 1},
            format="json",
        )

        assert response.status_code == 409
        assert response.data["code"] == "insufficient_stock"
        assert response.data["product_info"] == product_info.pk


@pytest.mark.django_db
class TestUpdateItem:
    """PATCH /api/orders/cart/items/{id}/."""

    def test_changes_quantity(self, auth_client, buyer, product_info) -> None:
        item = add_item(buyer, product_info, 1)

        response = auth_client.patch(item_url(item), {"quantity": 4}, format="json")

        assert response.status_code == 200
        assert response.data["quantity"] == 4
        item.refresh_from_db()
        assert item.quantity == 4

    def test_zero_quantity_is_rejected(self, auth_client, buyer, product_info) -> None:
        item = add_item(buyer, product_info, 2)

        response = auth_client.patch(item_url(item), {"quantity": 0}, format="json")

        assert response.status_code == 400
        item.refresh_from_db()
        assert item.quantity == 2

    def test_over_stock_is_rejected(self, auth_client, buyer, product_info) -> None:
        item = add_item(buyer, product_info, 1)

        response = auth_client.patch(
            item_url(item), {"quantity": product_info.quantity + 1}, format="json"
        )

        assert response.status_code == 409
        assert response.data["code"] == "insufficient_stock"

    def test_foreign_item_is_not_found(
        self, auth_client, other_buyer, product_info
    ) -> None:
        """Чужая позиция неотличима от несуществующей (404, не 403)."""
        item = add_item(other_buyer, product_info, 1)

        response = auth_client.patch(item_url(item), {"quantity": 5}, format="json")

        assert response.status_code == 404
        item.refresh_from_db()
        assert item.quantity == 1


@pytest.mark.django_db
class TestRemoveItem:
    """DELETE /api/orders/cart/items/{id}/."""

    def test_removes_item(self, auth_client, buyer, product_info) -> None:
        item = add_item(buyer, product_info, 1)

        response = auth_client.delete(item_url(item))

        assert response.status_code == 204
        assert not OrderItem.objects.filter(pk=item.pk).exists()

    def test_cart_survives_removal_of_last_item(
        self, auth_client, buyer, product_info
    ) -> None:
        """Корзина не удаляется вместе с последней позицией (ADR-022)."""
        item = add_item(buyer, product_info, 1)
        basket_id = item.order_id

        auth_client.delete(item_url(item))
        response = auth_client.get(CART_URL)

        assert response.status_code == 200
        assert response.data["id"] == basket_id
        assert response.data["items"] == []

    def test_item_of_deleted_offer_can_be_removed(
        self, auth_client, buyer, product_info
    ) -> None:
        item = add_item(buyer, product_info, 1)
        product_info.delete()

        assert auth_client.delete(item_url(item)).status_code == 204

    def test_foreign_item_is_not_found(
        self, auth_client, other_buyer, product_info
    ) -> None:
        item = add_item(other_buyer, product_info, 1)

        assert auth_client.delete(item_url(item)).status_code == 404
        assert OrderItem.objects.filter(pk=item.pk).exists()

    def test_unknown_item_is_not_found(self, auth_client) -> None:
        assert auth_client.delete(reverse("orders:cart-item", args=[10_000])).status_code == 404
