"""Доменные сервисы обращаются к уведомлениям только через notifications.

Проверяется цепочка ADR-005: `<app>.services` -> `notifications.services`
-> Celery task. Временная зависимость `users` -> `users.tasks` (ADR-010)
снята.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from users.models import User
from users.services import register_user, request_password_reset

PASSWORD = "StrongPass123!"


@pytest.fixture
def active_user(db) -> User:
    return User.objects.create_user(
        email="buyer@example.com", password=PASSWORD, is_active=True
    )


@pytest.mark.django_db
class TestRegistrationUsesNotifications:
    """Регистрация ставит письмо через notifications.services."""

    def test_registration_calls_notifications_service(self) -> None:
        with patch("users.services.registration.send_email_async") as send:
            register_user(email="new@example.com", password=PASSWORD)

        assert send.call_count == 1
        assert send.call_args.kwargs["recipient"] == "new@example.com"
        assert set(send.call_args.kwargs) == {"subject", "body", "recipient"}

    def test_confirmation_email_is_sent(
        self, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            register_user(email="new@example.com", password=PASSWORD)

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["new@example.com"]

    def test_email_failure_does_not_break_registration(
        self, caplog, django_capture_on_commit_callbacks
    ) -> None:
        """Пользователь создан, даже если письмо поставить не удалось."""
        with patch(
            "notifications.services.send_email.delay",
            side_effect=OSError("брокер недоступен"),
        ):
            with django_capture_on_commit_callbacks(execute=True):
                user = register_user(email="new@example.com", password=PASSWORD)

        assert User.objects.filter(pk=user.pk).exists()
        assert "Email task was not queued" in caplog.text

    def test_rollback_cancels_confirmation_email(self, mailoutbox) -> None:
        """Письмо не уходит, если регистрация откатилась (ADR-005)."""
        with patch(
            "users.services.registration.User.objects.create_user",
            side_effect=RuntimeError("сбой"),
        ):
            with pytest.raises(RuntimeError):
                register_user(email="new@example.com", password=PASSWORD)

        assert mailoutbox == []


@pytest.mark.django_db
class TestPasswordResetUsesNotifications:
    """Восстановление пароля ставит письмо через notifications.services."""

    def test_reset_calls_notifications_service(self, active_user) -> None:
        with patch("users.services.password_reset.send_email_async") as send:
            request_password_reset(email=active_user.email)

        assert send.call_count == 1
        assert send.call_args.kwargs["recipient"] == active_user.email
        assert set(send.call_args.kwargs) == {"subject", "body", "recipient"}

    def test_reset_email_is_sent(
        self, active_user, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            request_password_reset(email=active_user.email)

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [active_user.email]

    def test_unknown_email_sends_nothing(
        self, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            request_password_reset(email="unknown@example.com")

        assert mailoutbox == []
