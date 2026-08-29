"""Конфигурация проекта.

Импорт celery_app обеспечивает инициализацию Celery при старте Django.
"""

from config.celery import app as celery_app

__all__ = ("celery_app",)
