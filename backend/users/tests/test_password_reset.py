"""Тесты восстановления пароля."""

from __future__ import annotations

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse

from users.tokens import encode_uid

REQUEST_URL = reverse("auth:password-reset")
CONFIRM_URL = reverse("auth:password-reset-confirm")
NEW_PASSWORD = "AnotherStrong456!"


@pytest.mark.django_db
class TestPasswordResetRequest:
    """POST /api/auth/password-reset/."""

    def test_email_is_sent_to_known_user(
        self, api_client, active_user, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                REQUEST_URL, {"email": active_user.email}, format="json"
            )

        assert response.status_code == 200
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [active_user.email]

    def test_unknown_email_does_not_leak(
        self, api_client, db, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                REQUEST_URL, {"email": "unknown@example.com"}, format="json"
            )

        assert response.status_code == 200
        assert mailoutbox == []


@pytest.mark.django_db
class TestPasswordResetConfirm:
    """POST /api/auth/password-reset/confirm/."""

    def test_password_is_changed(self, api_client, active_user) -> None:
        payload = {
            "uid": encode_uid(active_user),
            "token": default_token_generator.make_token(active_user),
            "password": NEW_PASSWORD,
        }

        response = api_client.post(CONFIRM_URL, payload, format="json")

        assert response.status_code == 200
        active_user.refresh_from_db()
        assert active_user.check_password(NEW_PASSWORD)

    def test_invalid_token_is_rejected(self, api_client, active_user, password) -> None:
        payload = {
            "uid": encode_uid(active_user),
            "token": "broken-token",
            "password": NEW_PASSWORD,
        }

        response = api_client.post(CONFIRM_URL, payload, format="json")

        assert response.status_code == 400
        active_user.refresh_from_db()
        assert active_user.check_password(password)

    def test_token_cannot_be_reused(self, api_client, active_user) -> None:
        payload = {
            "uid": encode_uid(active_user),
            "token": default_token_generator.make_token(active_user),
            "password": NEW_PASSWORD,
        }

        first = api_client.post(CONFIRM_URL, payload, format="json")
        second = api_client.post(CONFIRM_URL, payload, format="json")

        assert first.status_code == 200
        assert second.status_code == 400

    def test_weak_password_is_rejected(self, api_client, active_user, password) -> None:
        payload = {
            "uid": encode_uid(active_user),
            "token": default_token_generator.make_token(active_user),
            "password": "12345",
        }

        response = api_client.post(CONFIRM_URL, payload, format="json")

        assert response.status_code == 400
        active_user.refresh_from_db()
        assert active_user.check_password(password)
