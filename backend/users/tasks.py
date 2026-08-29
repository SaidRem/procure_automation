"""Celery-задачи приложения users.

Временное размещение задачи отправки email (ADR-010): целевой владелец —
приложение `notifications` (ADR-005), которое будет создано на шаге 7.
Задача принимает только сериализуемые примитивы и вызывается исключительно
из `users.services`.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(
    name="users.send_email",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_email(subject: str, message: str, recipient: str) -> None:
    """Отправить письмо одному получателю."""
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )
    logger.info("Email sent: subject=%r recipient=%s", subject, recipient)
