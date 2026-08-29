"""Тесты регистрации пользователя."""

from __future__ import annotations

import pytest
from django.urls import reverse

from users.models import User, UserType

REGISTER_URL = reverse("auth:register")


@pytest.mark.django_db
class TestRegistration:
    """POST /api/auth/register/."""

    def test_successful_registration(self, api_client, password) -> None:
        response = api_client.post(
            REGISTER_URL,
            {
                "email": "new@example.com",
                "password": password,
                "first_name": "Иван",
                "last_name": "Иванов",
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.data["email"] == "new@example.com"
        assert "password" not in response.data

        user = User.objects.get(email="new@example.com")
        assert user.check_password(password)
        assert user.type == UserType.BUYER

    def test_user_is_inactive_after_registration(self, api_client, password) -> None:
        api_client.post(
            REGISTER_URL,
            {"email": "new@example.com", "password": password},
            format="json",
        )

        assert User.objects.get(email="new@example.com").is_active is False

    def test_confirmation_email_is_sent(
        self, api_client, password, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                REGISTER_URL,
                {"email": "new@example.com", "password": password},
                format="json",
            )

        assert response.status_code == 201
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["new@example.com"]
        assert "uid:" in mailoutbox[0].body
        assert "token:" in mailoutbox[0].body

    def test_email_is_required(self, api_client, password) -> None:
        response = api_client.post(REGISTER_URL, {"password": password}, format="json")

        assert response.status_code == 400
        assert "email" in response.data

    def test_password_is_required(self, api_client) -> None:
        response = api_client.post(REGISTER_URL, {"email": "new@example.com"}, format="json")

        assert response.status_code == 400
        assert "password" in response.data

    def test_email_is_unique(self, api_client, active_user, password) -> None:
        response = api_client.post(
            REGISTER_URL,
            {"email": active_user.email, "password": password},
            format="json",
        )

        assert response.status_code == 400
        assert "email" in response.data
        assert User.objects.filter(email=active_user.email).count() == 1

    def test_weak_password_is_rejected(self, api_client) -> None:
        response = api_client.post(
            REGISTER_URL,
            {"email": "new@example.com", "password": "12345"},
            format="json",
        )

        assert response.status_code == 400
        assert "password" in response.data
        assert User.objects.filter(email="new@example.com").exists() is False
