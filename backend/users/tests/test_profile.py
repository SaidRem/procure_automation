"""Тесты профиля текущего пользователя."""

from __future__ import annotations

import pytest
from django.urls import reverse

PROFILE_URL = reverse("users:profile")


@pytest.mark.django_db
class TestProfile:
    """GET/PATCH /api/users/profile/."""

    def test_returns_current_user(self, auth_client, active_user) -> None:
        response = auth_client.get(PROFILE_URL)

        assert response.status_code == 200
        assert response.data["email"] == active_user.email
        assert response.data["type"] == active_user.type
        assert response.data["company"] == active_user.company
        assert response.data["position"] == active_user.position

    def test_allowed_fields_are_updated(self, auth_client, active_user) -> None:
        response = auth_client.patch(
            PROFILE_URL,
            {"company": "ООО Вектор", "position": "Директор"},
            format="json",
        )

        assert response.status_code == 200
        active_user.refresh_from_db()
        assert active_user.company == "ООО Вектор"
        assert active_user.position == "Директор"

    def test_email_cannot_be_changed(self, auth_client, active_user) -> None:
        original_email = active_user.email

        response = auth_client.patch(
            PROFILE_URL, {"email": "hacked@example.com"}, format="json"
        )

        assert response.status_code == 200
        active_user.refresh_from_db()
        assert active_user.email == original_email

    def test_type_cannot_be_changed(self, auth_client, active_user) -> None:
        response = auth_client.patch(PROFILE_URL, {"type": "shop"}, format="json")

        assert response.status_code == 200
        active_user.refresh_from_db()
        assert active_user.type == "buyer"

    def test_anonymous_access_is_denied(self, api_client) -> None:
        assert api_client.get(PROFILE_URL).status_code == 401
