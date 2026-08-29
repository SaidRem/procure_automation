"""Тесты подтверждения email."""

from __future__ import annotations

import pytest
from django.urls import reverse

from users.models import User
from users.tokens import email_confirmation_token_generator, encode_uid

CONFIRM_URL = reverse("auth:register-confirm")


@pytest.fixture
def pending_user(db, password) -> User:
    """Зарегистрированный, но не подтверждённый пользователь."""
    return User.objects.create_user(email="pending@example.com", password=password)


@pytest.mark.django_db
class TestEmailConfirmation:
    """POST /api/auth/register/confirm/."""

    def test_valid_token_activates_user(self, api_client, pending_user) -> None:
        payload = {
            "uid": encode_uid(pending_user),
            "token": email_confirmation_token_generator.make_token(pending_user),
        }

        response = api_client.post(CONFIRM_URL, payload, format="json")

        assert response.status_code == 200
        pending_user.refresh_from_db()
        assert pending_user.is_active is True

    def test_invalid_token_is_rejected(self, api_client, pending_user) -> None:
        payload = {"uid": encode_uid(pending_user), "token": "broken-token"}

        response = api_client.post(CONFIRM_URL, payload, format="json")

        assert response.status_code == 400
        pending_user.refresh_from_db()
        assert pending_user.is_active is False

    def test_unknown_uid_is_rejected(self, api_client, pending_user) -> None:
        payload = {
            "uid": "not-a-uid",
            "token": email_confirmation_token_generator.make_token(pending_user),
        }

        response = api_client.post(CONFIRM_URL, payload, format="json")

        assert response.status_code == 400

    def test_token_cannot_be_reused(self, api_client, pending_user) -> None:
        payload = {
            "uid": encode_uid(pending_user),
            "token": email_confirmation_token_generator.make_token(pending_user),
        }

        first = api_client.post(CONFIRM_URL, payload, format="json")
        second = api_client.post(CONFIRM_URL, payload, format="json")

        assert first.status_code == 200
        assert second.status_code == 400
        pending_user.refresh_from_db()
        assert pending_user.is_active is True

    def test_token_of_other_user_is_rejected(self, api_client, pending_user, active_user) -> None:
        payload = {
            "uid": encode_uid(pending_user),
            "token": email_confirmation_token_generator.make_token(active_user),
        }

        response = api_client.post(CONFIRM_URL, payload, format="json")

        assert response.status_code == 400
        pending_user.refresh_from_db()
        assert pending_user.is_active is False
