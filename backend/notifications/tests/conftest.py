"""Фикстуры тестов приложения notifications."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def celery_eager(settings) -> None:
    """Выполнять Celery-задачи синхронно, без брокера."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
