"""Тесты Celery-задачи отправки письма."""

from __future__ import annotations

import pytest
from notifications.tasks import send_email


@pytest.mark.django_db
class TestSendEmailTask:
    """notifications.send_email."""

    def test_sends_email(self, mailoutbox) -> None:
        send_email("Тема", "Текст письма", "buyer@example.com")

        assert len(mailoutbox) == 1
        assert mailoutbox[0].subject == "Тема"
        assert mailoutbox[0].body == "Текст письма"
        assert mailoutbox[0].to == ["buyer@example.com"]

    def test_uses_default_from_email(self, mailoutbox, settings) -> None:
        settings.DEFAULT_FROM_EMAIL = "noreply@procure.test"

        send_email("Тема", "Текст", "buyer@example.com")

        assert mailoutbox[0].from_email == "noreply@procure.test"

    def test_task_is_registered_under_stable_name(self) -> None:
        """Имя задачи входит в контракт очереди и не меняется молча."""
        assert send_email.name == "notifications.send_email"

    def test_retries_only_network_failures(self) -> None:
        """Повтор имеет смысл для сетевого сбоя, но не для отвергнутого адреса."""
        assert send_email.autoretry_for == (OSError,)
        assert send_email.retry_kwargs["max_retries"] == 3
