"""Интеграция оформления заказа с уведомлениями (ADR-005, ADR-022)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from orders.models import Order, OrderState
from orders.services import add_item, checkout_order, get_or_create_basket


@pytest.mark.django_db
class TestCheckoutQueuesNotifications:
    """Оформление ставит оба письма."""

    def test_checkout_creates_order(self, buyer, contact, product_info) -> None:
        add_item(buyer, product_info, 2)

        order = checkout_order(buyer, contact.pk)

        assert order.state == OrderState.NEW
        assert order.confirmed_at is not None

    def test_both_notifications_are_queued(
        self, buyer, contact, product_info, django_capture_on_commit_callbacks
    ) -> None:
        add_item(buyer, product_info, 1)

        with patch("notifications.services.send_email.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                order = checkout_order(buyer, contact.pk)

        subjects = [call.kwargs["subject"] for call in delay.call_args_list]
        recipients = [call.kwargs["recipient"] for call in delay.call_args_list]

        assert subjects == [f"Заказ №{order.pk} принят", f"Новый заказ №{order.pk}"]
        assert buyer.email in recipients

    def test_emails_are_delivered(
        self, buyer, contact, product_info, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        add_item(buyer, product_info, 1)

        with django_capture_on_commit_callbacks(execute=True):
            checkout_order(buyer, contact.pk)

        assert len(mailoutbox) == 2
        assert mailoutbox[0].to == [buyer.email]

    def test_notifications_are_not_sent_before_commit(
        self, buyer, contact, product_info, django_capture_on_commit_callbacks
    ) -> None:
        """До коммита писем нет: заказ ещё может откатиться (ADR-005)."""
        add_item(buyer, product_info, 1)

        with patch("notifications.services.send_email.delay") as delay:
            with django_capture_on_commit_callbacks() as callbacks:
                checkout_order(buyer, contact.pk)

                assert delay.call_count == 0

            assert len(callbacks) == 2


@pytest.mark.django_db
class TestNotificationFailureDoesNotBreakCheckout:
    """Недоступность почты не отменяет оформленный заказ."""

    def test_broker_failure_keeps_order(
        self, buyer, contact, product_info, caplog, django_capture_on_commit_callbacks
    ) -> None:
        add_item(buyer, product_info, 1)

        with patch(
            "notifications.services.send_email.delay",
            side_effect=OSError("брокер недоступен"),
        ):
            with django_capture_on_commit_callbacks(execute=True):
                order = checkout_order(buyer, contact.pk)

        order.refresh_from_db()

        assert order.state == OrderState.NEW
        assert Order.objects.filter(pk=order.pk).exists()
        assert "Email task was not queued" in caplog.text

    def test_message_building_failure_keeps_order(
        self, buyer, contact, product_info, caplog, django_capture_on_commit_callbacks
    ) -> None:
        """Сбой при сборке письма тоже не трогает заказ."""
        add_item(buyer, product_info, 1)

        with patch(
            "notifications.services._customer_body",
            side_effect=RuntimeError("сбой шаблона"),
        ):
            with django_capture_on_commit_callbacks(execute=True):
                order = checkout_order(buyer, contact.pk)

        order.refresh_from_db()

        assert order.state == OrderState.NEW
        assert "Order notification failed" in caplog.text

    def test_smtp_failure_keeps_order(
        self, buyer, contact, product_info, settings, django_capture_on_commit_callbacks
    ) -> None:
        settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
        settings.EMAIL_HOST = "127.0.0.1"
        settings.EMAIL_PORT = 1
        add_item(buyer, product_info, 1)

        with django_capture_on_commit_callbacks(execute=True):
            order = checkout_order(buyer, contact.pk)

        assert Order.objects.filter(pk=order.pk, state=OrderState.NEW).exists()


@pytest.mark.django_db
class TestRollbackCancelsNotifications:
    """Откат оформления не оставляет писем."""

    def test_unavailable_offer_queues_nothing(
        self, buyer, contact, product_info, mailoutbox
    ) -> None:
        """Отказ по доступности откатывает транзакцию целиком."""
        from orders.services import OfferInactive

        add_item(buyer, product_info, 1)
        product_info.is_active = False
        product_info.save(update_fields=["is_active"])

        with patch("notifications.services.send_email.delay") as delay:
            with pytest.raises(OfferInactive):
                checkout_order(buyer, contact.pk)

        assert delay.call_count == 0
        assert mailoutbox == []
        assert get_or_create_basket(buyer).state == OrderState.BASKET

    def test_incomplete_contact_queues_nothing(
        self, buyer, incomplete_contact, product_info, mailoutbox
    ) -> None:
        from orders.services import IncompleteRecipientData

        add_item(buyer, product_info, 1)

        with patch("notifications.services.send_email.delay") as delay:
            with pytest.raises(IncompleteRecipientData):
                checkout_order(buyer, incomplete_contact.pk)

        assert delay.call_count == 0
        assert mailoutbox == []
