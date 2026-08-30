"""Публичный сервисный слой приложения notifications (ADR-005, ADR-010).

Единственная точка проекта, знающая о задаче отправки писем. Доменные
сервисы вызывают только эти функции и не импортируют Celery-задачи
напрямую: цепочка вызова — `<app>.services` -> `notifications.services`
-> Celery task.

Модуль намеренно не импортирует модели других приложений и принимает
только примитивы. Иначе `notifications` знал бы о `users` и `orders`, а
они о нём — то есть цикл между доменом и инфраструктурой уведомлений.
"""

from __future__ import annotations

import logging

from django.db import transaction

from notifications.tasks import send_email

logger = logging.getLogger(__name__)


def send_email_async(*, subject: str, body: str, recipient: str) -> None:
    """Поставить письмо в очередь после успешного коммита транзакции.

    Постановка через `transaction.on_commit` (ADR-005): письмо не должно
    уходить, если транзакция, породившая событие, откатилась —
    пользователь получил бы подтверждение регистрации, которой не было.

    Сбой постановки не прерывает вызывающую операцию. Коллбэк
    выполняется уже после коммита, и исключение из него отменило бы
    ответ на запрос, ничего не откатив: пользователь был бы создан, а
    клиент получил бы ошибку. Недоступность брокера — причина не
    отправить письмо, а не причина считать регистрацию неудавшейся,
    поэтому она логируется и на результат операции не влияет.
    """
    logger.info("Email queued: subject=%r recipient=%s", subject, recipient)
    transaction.on_commit(lambda: _enqueue(subject, body, recipient))


def _enqueue(subject: str, body: str, recipient: str) -> None:
    """Отправить задачу в очередь, не прерывая вызывающую операцию."""
    try:
        send_email.delay(subject=subject, body=body, recipient=recipient)
    except Exception:
        logger.exception(
            "Email task was not queued: subject=%r recipient=%s", subject, recipient
        )
