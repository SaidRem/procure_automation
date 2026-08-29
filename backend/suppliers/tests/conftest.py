"""Фикстуры тестов приложения suppliers."""

from __future__ import annotations

import pytest

from suppliers.models import Shop
from users.models import User, UserType


@pytest.fixture
def shop_user(db) -> User:
    """Активный пользователь типа `shop`."""
    return User.objects.create_user(
        email="supplier@example.com",
        password="StrongPass123!",
        is_active=True,
        type=UserType.SHOP,
    )


@pytest.fixture
def shop(db) -> Shop:
    """Магазин без привязки к пользователю."""
    return Shop.objects.create(name="Связной")
