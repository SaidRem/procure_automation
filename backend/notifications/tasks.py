"""Celery-задачи приложения notifications (ADR-005).

Задача — тонкая обёртка над отправкой письма: она не решает, кому и по
какому поводу писать, и не обращается к моделям. Всё, что ей нужно,
приходит примитивами, потому что аргументы задачи сериализуются в
очередь, а инстансы моделей к моменту выполнения могут устареть.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(
    name="notifications.send_email",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_email(subject: str, body: str, recipient: str) -> None:
    """Отправить письмо одному получателю.

    Повтор выполняется только для сетевых сбоев (`OSError`): недоступный
    SMTP-сервер — временная причина, а отвергнутый адрес повтором не
    исправляется.
    """
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )
    logger.info("Email sent: subject=%r recipient=%s", subject, recipient)
