"""Постановка email-уведомлений в очередь.

Единственная точка приложения users, знающая о Celery-задачах (ADR-005):
сервисы доменной логики вызывают только функции этого модуля. После
переноса задачи в приложение `notifications` (ADR-010) изменится только
реализация этих функций.
"""

from __future__ import annotations

import logging

from django.db import transaction

from users.tasks import send_email

logger = logging.getLogger(__name__)


def send_email_async(*, subject: str, message: str, recipient: str) -> None:
    """Поставить письмо в очередь после успешного коммита транзакции."""
    logger.info("Email queued: subject=%r recipient=%s", subject, recipient)
    transaction.on_commit(
        lambda: send_email.delay(subject=subject, message=message, recipient=recipient)
    )
