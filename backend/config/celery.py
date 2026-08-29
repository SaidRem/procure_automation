"""Конфигурация Celery-приложения (ADR-005)."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("procure_automation")

# Настройки берутся из Django settings, префикс CELERY_.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Автоматический поиск tasks.py в приложениях проекта.
app.autodiscover_tasks()
