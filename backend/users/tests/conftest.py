"""Общие фикстуры тестов приложения users."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User

PASSWORD = "StrongPass123!"


@pytest.fixture(autouse=True)
def celery_eager(settings) -> None:
    """Выполнять Celery-задачи синхронно, без брокера."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def password() -> str:
    return PASSWORD


@pytest.fixture
def active_user(db) -> User:
    """Подтверждённый пользователь-покупатель."""
    return User.objects.create_user(
        email="buyer@example.com",
        password=PASSWORD,
        is_active=True,
        company="ООО Ромашка",
        position="Менеджер",
    )


@pytest.fixture
def other_user(db) -> User:
    """Второй подтверждённый пользователь — для проверки изоляции данных."""
    return User.objects.create_user(
        email="other@example.com",
        password=PASSWORD,
        is_active=True,
    )


@pytest.fixture
def auth_client(api_client: APIClient, active_user: User) -> APIClient:
    """Клиент с реальным access-токеном текущего пользователя."""
    access = RefreshToken.for_user(active_user).access_token
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return api_client
