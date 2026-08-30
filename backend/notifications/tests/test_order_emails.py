"""Тесты писем по оформленному заказу (ADR-005, ADR-024, ADR-027)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from catalog.models import Category, Product, ProductInfo
from notifications.services import (
    send_new_order_notification,
    send_order_confirmation,
)
from orders.models import Order, OrderItem, OrderState
from suppliers.models import Shop
from users.models import User


@pytest.fixture
def placed_order(db) -> Order:
    """Оформленный заказ со снятыми snapshot (ADR-003, ADR-024)."""
    user = User.objects.create_user(
        email="buyer@example.com", password="StrongPass123!", is_active=True
    )
    shop = Shop.objects.create(name="Связной")
    category = Category.objects.create(name="Смартфоны")
    product = Product.objects.create(name="Смартфон Apple iPhone XS Max", category=category)
    offer = ProductInfo.objects.create(
        product=product,
        shop=shop,
        external_id=1,
        quantity=10,
        price=Decimal("110000.00"),
        price_rrc=Decimal("116990.00"),
    )

    from django.utils import timezone

    order = Order.objects.create(
        user=user,
        state=OrderState.NEW,
        confirmed_at=timezone.now(),
        delivery_last_name="Петров",
        delivery_first_name="Пётр",
        delivery_middle_name="Петрович",
        delivery_email="recipient@example.com",
        delivery_phone="+70000000000",
        delivery_city="Москва",
        delivery_street="Тверская",
        delivery_house="1",
        delivery_apartment="5",
    )
    OrderItem.objects.create(
        order=order,
        product_info=offer,
        quantity=2,
        product_name=product.name,
        shop_name=shop.name,
        price=Decimal("110000.00"),
        price_rrc=Decimal("116990.00"),
    )
    return order


@pytest.mark.django_db
class TestCustomerEmail:
    """Письмо покупателю."""

    def test_is_sent_to_account_email(
        self, placed_order, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        """Подтверждение уходит на email учётной записи, не получателя."""
        with django_capture_on_commit_callbacks(execute=True):
            send_order_confirmation(placed_order.pk)

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["buyer@example.com"]
        assert mailoutbox[0].to != [placed_order.delivery_email]

    def test_contains_order_number_and_date(
        self, placed_order, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            send_order_confirmation(placed_order.pk)

        assert f"№{placed_order.pk}" in mailoutbox[0].subject
        assert f"Заказ №{placed_order.pk}" in mailoutbox[0].body
        assert placed_order.confirmed_at.strftime("%d.%m.%Y") in mailoutbox[0].body

    def test_contains_items_and_total(
        self, placed_order, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            send_order_confirmation(placed_order.pk)

        body = mailoutbox[0].body

        assert "Смартфон Apple iPhone XS Max" in body
        assert "Связной" in body
        assert "2 x 110000.00 = 220000.00" in body
        assert "Итого: 220000.00" in body

    def test_contains_delivery_address(
        self, placed_order, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            send_order_confirmation(placed_order.pk)

        body = mailoutbox[0].body

        assert "Петров Пётр Петрович" in body
        assert "+70000000000" in body
        assert "Москва, ул. Тверская, д. 1, кв. 5" in body

    def test_uses_snapshot_not_catalog(
        self, placed_order, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        """Изменение прайса не меняет содержимое письма (ADR-003)."""
        offer = placed_order.items.get().product_info
        offer.price = Decimal("1.00")
        offer.product.name = "Другое название"
        offer.product.save()
        offer.save()

        with django_capture_on_commit_callbacks(execute=True):
            send_order_confirmation(placed_order.pk)

        assert "110000.00" in mailoutbox[0].body
        assert "Другое название" not in mailoutbox[0].body


@pytest.mark.django_db
class TestAdminEmail:
    """Накладная администратору."""

    def test_is_sent_to_configured_address(
        self, placed_order, mailoutbox, settings, django_capture_on_commit_callbacks
    ) -> None:
        settings.ORDER_ADMIN_EMAIL = "admin@procure.test"

        with django_capture_on_commit_callbacks(execute=True):
            send_new_order_notification(placed_order.pk)

        assert mailoutbox[0].to == ["admin@procure.test"]

    def test_contains_order_user_and_contact(
        self, placed_order, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            send_new_order_notification(placed_order.pk)

        body = mailoutbox[0].body

        assert f"Оформлен заказ №{placed_order.pk}" in body
        assert "Покупатель: buyer@example.com" in body
        assert "Петров Пётр Петрович" in body
        assert "Москва, ул. Тверская, д. 1, кв. 5" in body

    def test_contains_items(
        self, placed_order, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            send_new_order_notification(placed_order.pk)

        assert "Смартфон Apple iPhone XS Max" in mailoutbox[0].body
        assert "Итого: 220000.00" in mailoutbox[0].body


@pytest.mark.django_db
class TestTaskArguments:
    """Задача получает только примитивы (ADR-005)."""

    def test_only_primitives_are_passed(
        self, placed_order, django_capture_on_commit_callbacks
    ) -> None:
        with patch("notifications.services.send_email.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                send_order_confirmation(placed_order.pk)
                send_new_order_notification(placed_order.pk)

        assert delay.call_count == 2
        for call in delay.call_args_list:
            assert set(call.kwargs) == {"subject", "body", "recipient"}
            for value in call.kwargs.values():
                assert isinstance(value, str)


@pytest.mark.django_db
class TestFailureIsolation:
    """Сбой уведомления не поднимается к вызывающему коду."""

    def test_missing_order_is_logged(
        self, caplog, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            send_order_confirmation(10_000)

        assert "Order notification failed" in caplog.text

    def test_broker_failure_is_logged(
        self, placed_order, caplog, django_capture_on_commit_callbacks
    ) -> None:
        with patch(
            "notifications.services.send_email.delay",
            side_effect=OSError("брокер недоступен"),
        ):
            with django_capture_on_commit_callbacks(execute=True):
                send_order_confirmation(placed_order.pk)

        assert "Email task was not queued" in caplog.text
