"""Тесты JWT-аутентификации (ADR-007)."""

from __future__ import annotations

import pytest
from django.urls import reverse

from users.models import User

LOGIN_URL = reverse("auth:login")
REFRESH_URL = reverse("auth:token-refresh")
PROFILE_URL = reverse("users:profile")


@pytest.mark.django_db
class TestJWTAuthentication:
    """POST /api/auth/login/ и /api/auth/token/refresh/."""

    def test_login_returns_token_pair(self, api_client, active_user, password) -> None:
        response = api_client.post(
            LOGIN_URL,
            {"email": active_user.email, "password": password},
            format="json",
        )

        assert response.status_code == 200
        assert "access" in response.data
        assert "refresh" in response.data

    def test_login_with_wrong_password_is_rejected(self, api_client, active_user) -> None:
        response = api_client.post(
            LOGIN_URL,
            {"email": active_user.email, "password": "WrongPass123!"},
            format="json",
        )

        assert response.status_code == 401

    def test_inactive_user_cannot_login(self, api_client, password) -> None:
        user = User.objects.create_user(email="pending@example.com", password=password)

        response = api_client.post(
            LOGIN_URL,
            {"email": user.email, "password": password},
            format="json",
        )

        assert response.status_code == 401

    def test_refresh_returns_new_access_token(self, api_client, active_user, password) -> None:
        login = api_client.post(
            LOGIN_URL,
            {"email": active_user.email, "password": password},
            format="json",
        )

        response = api_client.post(
            REFRESH_URL, {"refresh": login.data["refresh"]}, format="json"
        )

        assert response.status_code == 200
        assert "access" in response.data

    def test_invalid_refresh_token_is_rejected(self, api_client) -> None:
        response = api_client.post(REFRESH_URL, {"refresh": "broken"}, format="json")

        assert response.status_code == 401

    def test_access_token_grants_access(self, api_client, active_user, password) -> None:
        login = api_client.post(
            LOGIN_URL,
            {"email": active_user.email, "password": password},
            format="json",
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        response = api_client.get(PROFILE_URL)

        assert response.status_code == 200

    def test_anonymous_access_is_denied(self, api_client) -> None:
        response = api_client.get(PROFILE_URL)

        assert response.status_code == 401
