"""Удаление контакта не изменяет историю заказов (ADR-024)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from orders.models import Order
from orders.services import add_item, checkout_order


@pytest.mark.django_db
class TestContactDeletionKeepsOrder:
    """DELETE /api/users/contacts/{id}/ и оформленный заказ."""

    def test_order_survives_and_keeps_snapshot(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        add_item(buyer, product_info, 2)
        order = checkout_order(buyer, contact.pk)

        response = auth_client.delete(
            reverse("users:contact-detail", args=[contact.pk])
        )
        order.refresh_from_db()

        assert response.status_code == 204
        assert Order.objects.filter(pk=order.pk).exists()
        assert order.contact is None
        assert order.delivery_city == contact.city
        assert order.delivery_last_name == contact.last_name
        assert order.delivery_phone == contact.phone

    def test_order_api_still_returns_delivery(
        self, auth_client, buyer, contact, product_info
    ) -> None:
        """Карточка заказа читает адрес из snapshot, а не из контакта."""
        add_item(buyer, product_info, 1)
        order = checkout_order(buyer, contact.pk)

        auth_client.delete(reverse("users:contact-detail", args=[contact.pk]))
        response = auth_client.get(reverse("orders:order-detail", args=[order.pk]))

        assert response.status_code == 200
        assert response.data["delivery"]["city"] == "Москва"
        assert response.data["delivery"]["last_name"] == "Петров"
        assert Decimal(response.data["total"]) == product_info.price
