"""Постановка импорта прайса в очередь (ADR-021).

Модуль создаёт запись журнала и ставит Celery-задачу после коммита
транзакции (ADR-005). Логики самого импорта здесь нет: она выполняется
в `suppliers.services.import_runner` внутри воркера.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction

from suppliers.models import ImportLog, ImportStatus, Shop
from suppliers.services.exceptions import (
    ImportAlreadyRunning,
    PriceSourceNotConfigured,
    ShopNotFound,
)

if TYPE_CHECKING:
    from users.models import User

logger = logging.getLogger(__name__)


def schedule_price_import(
    *,
    shop_id: int,
    url: str,
    initiated_by: User | None = None,
) -> ImportLog:
    """Зарегистрировать запуск импорта и поставить задачу в очередь.

    Одна запись журнала — один запуск импорта (ADR-021): повторы задачи
    выполняются в её пределах и увеличивают `attempts`.

    Задача ставится через `transaction.on_commit()` (ADR-005), поэтому
    откат транзакции не оставляет ни записи журнала, ни задачи в
    очереди. Пустой `initiated_by` означает запуск не человеком.
    """
    if not url:
        raise PriceSourceNotConfigured(
            f"У магазина {shop_id} не указана ссылка на прайс."
        )

    log = ImportLog.objects.create(
        shop_id=shop_id,
        source_url=url,
        initiated_by=initiated_by,
        status=ImportStatus.QUEUED,
        attempts=0,
    )

    transaction.on_commit(lambda: _enqueue(shop_id, url, log.pk))

    logger.info("Import run scheduled: log_id=%s shop_id=%s", log.pk, shop_id)
    return log


def _enqueue(shop_id: int, url: str, log_id: int) -> None:
    """Отправить задачу и сохранить её идентификатор в журнале.

    Импорт задачи отложен до вызова: `suppliers.tasks` обращается к
    сервисному слою, и импорт на уровне модуля замкнул бы цикл.

    Идентификатор записывается точечным `update()`, а не `save()`:
    воркер может начать выполнение раньше, чем вернётся `delay()`, и
    полное сохранение затёрло бы уже записанное им состояние.
    """
    from suppliers.tasks import import_supplier_price_task

    task = import_supplier_price_task.delay(shop_id, url, log_id)
    ImportLog.objects.filter(pk=log_id).update(task_id=task.id)

    logger.info("Import task queued: log_id=%s task_id=%s", log_id, task.id)


# Состояния, в которых запуск считается незавершённым.
UNFINISHED_STATUSES = (ImportStatus.QUEUED, ImportStatus.RUNNING)


def request_price_import(
    *,
    shop_id: int,
    initiated_by: User | None = None,
) -> ImportLog:
    """Принять запрос поставщика на импорт своего прайса (ADR-026).

    Источник — `Shop.url`: адрес задаёт сам поставщик при заведении
    магазина, и отдельного источника у запуска нет.

    Параллельный запуск отклоняется. Импорты одного магазина всё равно
    сериализуются блокировкой строки в
    `catalog.services.upsert_shop_price` (ADR-005), поэтому повторный
    вызов не ускоряет обработку, а занимает воркер ожиданием.

    Отличие от `schedule_price_import`: тот выражает низкоуровневое
    «поставить запуск в очередь» и проверок очерёдности не делает.
    """
    try:
        shop = Shop.objects.get(pk=shop_id)
    except Shop.DoesNotExist as error:
        raise ShopNotFound(f"Магазин {shop_id} не найден.") from error

    unfinished = ImportLog.objects.filter(
        shop_id=shop_id, status__in=UNFINISHED_STATUSES
    ).first()

    if unfinished is not None:
        raise ImportAlreadyRunning(
            f"Импорт магазина {shop_id} уже выполняется "
            f"(запуск {unfinished.pk}, состояние {unfinished.status})."
        )

    return schedule_price_import(
        shop_id=shop_id,
        url=shop.url or "",
        initiated_by=initiated_by,
    )
