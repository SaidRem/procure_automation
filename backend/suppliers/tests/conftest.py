"""Фикстуры тестов приложения suppliers."""

from __future__ import annotations

import pytest

from config.celery import app as celery_app
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


@pytest.fixture(autouse=True)
def eager_celery():
    """Выполнять Celery-задачи синхронно, без брокера.

    Настройка задаётся приложению Celery напрямую: конфигурация читается
    один раз при первом обращении, и подмены Django-настроек после этого
    момента задача уже не увидит.
    """
    previous = (celery_app.conf.task_always_eager, celery_app.conf.task_eager_propagates)
    celery_app.conf.task_always_eager = True
    # Исключения возвращаются в результате задачи, а не поднимаются:
    # так тест видит и состояние задачи, и число повторов.
    celery_app.conf.task_eager_propagates = False

    yield

    celery_app.conf.task_always_eager, celery_app.conf.task_eager_propagates = previous
