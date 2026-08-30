"""Тесты сервиса уведомлений (ADR-005, ADR-010)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import transaction

from notifications.services import send_email_async

PAYLOAD = {
    "subject": "Подтверждение регистрации",
    "body": "Ссылка: https://example.test/confirm",
    "recipient": "buyer@example.com",
}


@pytest.mark.django_db
class TestSendEmailAsync:
    """send_email_async."""

    def test_queues_task(self, django_capture_on_commit_callbacks) -> None:
        with patch("notifications.services.send_email.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                send_email_async(**PAYLOAD)

        delay.assert_called_once_with(**PAYLOAD)

    def test_task_is_executed(
        self, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        """В eager-режиме задача выполняется и письмо уходит."""
        with django_capture_on_commit_callbacks(execute=True):
            send_email_async(**PAYLOAD)

        assert len(mailoutbox) == 1
        assert mailoutbox[0].subject == PAYLOAD["subject"]
        assert mailoutbox[0].body == PAYLOAD["body"]
        assert mailoutbox[0].to == [PAYLOAD["recipient"]]

    def test_only_primitives_are_passed(
        self, django_capture_on_commit_callbacks
    ) -> None:
        """В задачу уходят только сериализуемые значения (ADR-005)."""
        with patch("notifications.services.send_email.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                send_email_async(**PAYLOAD)

        for value in delay.call_args.kwargs.values():
            assert isinstance(value, str)


@pytest.mark.django_db
class TestOnCommit:
    """Постановка задачи после коммита (ADR-005)."""

    def test_task_is_queued_only_on_commit(
        self, django_capture_on_commit_callbacks
    ) -> None:
        with patch("notifications.services.send_email.delay") as delay:
            with django_capture_on_commit_callbacks() as callbacks:
                send_email_async(**PAYLOAD)

            # Коллбэк зарегистрирован, но не выполнен: до коммита
            # письмо в очередь не попадает.
            assert delay.call_count == 0
            assert len(callbacks) == 1

            callbacks[0]()
            assert delay.call_count == 1

    def test_rollback_cancels_the_email(self, mailoutbox) -> None:
        """Откат транзакции не оставляет письма в очереди."""
        with patch("notifications.services.send_email.delay") as delay:
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    send_email_async(**PAYLOAD)
                    raise RuntimeError("откат")

        assert delay.call_count == 0
        assert mailoutbox == []


@pytest.mark.django_db
class TestEnqueueFailure:
    """Сбой постановки не прерывает вызывающую операцию."""

    def test_broker_failure_is_swallowed_and_logged(
        self, caplog, django_capture_on_commit_callbacks
    ) -> None:
        with patch(
            "notifications.services.send_email.delay",
            side_effect=OSError("брокер недоступен"),
        ):
            with django_capture_on_commit_callbacks(execute=True):
                send_email_async(**PAYLOAD)

        assert "Email task was not queued" in caplog.text

    def test_email_failure_does_not_raise(
        self, settings, caplog, django_capture_on_commit_callbacks
    ) -> None:
        """Отказ самой отправки не поднимается к вызывающему коду."""
        settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
        settings.EMAIL_HOST = "127.0.0.1"
        settings.EMAIL_PORT = 1

        with django_capture_on_commit_callbacks(execute=True):
            send_email_async(**PAYLOAD)

        assert "Email task was not queued" in caplog.text
