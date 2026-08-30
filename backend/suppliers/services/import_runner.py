"""Выполнение запуска импорта с ведением журнала (ADR-021).

Модуль переводит запись `ImportLog` по состояниям
`queued → running → success/failed` и вызывает сквозной сценарий
импорта. Повторяемые ошибки транспорта (ADR-018) в `failed` не
переводятся: запуск остаётся выполняющимся и возвращается в повтор
Celery.
"""

from __future__ import annotations

import logging

from django.db.models import F
from django.utils import timezone

from catalog.services import ImportResult, InvalidPriceData, UnknownShop
from suppliers.importers import (
    InsecurePriceSource,
    PriceDownloadError,
    PriceFileTooLarge,
    PriceParseError,
    PriceSourceUnavailable,
)
from suppliers.models import ImportErrorCode, ImportLog, ImportStatus
from suppliers.services.exceptions import (
    ImportRunNotFound,
    ShopMetadataMismatch,
    ShopNotFound,
)
from suppliers.services.import_pipeline import import_supplier_price_from_url

logger = logging.getLogger(__name__)

# Порядок важен: подкласс стоит раньше своего базового класса, иначе
# `PriceSourceUnavailable` получил бы код общей ошибки загрузки.
_ERROR_CODES: tuple[tuple[type[Exception], str], ...] = (
    (InsecurePriceSource, ImportErrorCode.INSECURE_SOURCE),
    (PriceFileTooLarge, ImportErrorCode.FILE_TOO_LARGE),
    (PriceSourceUnavailable, ImportErrorCode.SOURCE_UNAVAILABLE),
    (PriceDownloadError, ImportErrorCode.DOWNLOAD_ERROR),
    (PriceParseError, ImportErrorCode.PARSE_ERROR),
    (InvalidPriceData, ImportErrorCode.INVALID_PRICE_DATA),
    (ShopMetadataMismatch, ImportErrorCode.SHOP_METADATA_MISMATCH),
    (ShopNotFound, ImportErrorCode.SHOP_NOT_FOUND),
    (UnknownShop, ImportErrorCode.SHOP_NOT_FOUND),
)


def run_logged_import(log_id: int) -> ImportResult:
    """Выполнить запуск импорта, зарегистрированный в журнале.

    Магазин и ссылка берутся из записи журнала: она остаётся источником
    истины на всех попытках выполнения (ADR-021).

    Исключение всегда пробрасывается дальше — иначе Celery не увидит
    отказ и политика повторов ADR-018 перестанет работать.
    """
    log = _start(log_id)

    try:
        result = import_supplier_price_from_url(log.shop_id, log.source_url)
    except Exception as error:
        _record_failure(log_id, error)
        raise

    _record_success(log_id, result)
    return result


def _start(log_id: int) -> ImportLog:
    """Перевести запуск в состояние выполнения и учесть попытку.

    `attempts` увеличивается выражением `F()`: повтор может выполняться
    другим воркером, и чтение-запись значения в Python потеряло бы
    попытку. `started_at` отмечает начало текущей попытки.
    """
    updated = ImportLog.objects.filter(pk=log_id).update(
        status=ImportStatus.RUNNING,
        attempts=F("attempts") + 1,
        started_at=timezone.now(),
    )

    if not updated:
        raise ImportRunNotFound(f"Запуск импорта {log_id} не найден.")

    log = ImportLog.objects.get(pk=log_id)
    logger.info("Import run started: log_id=%s attempt=%s", log_id, log.attempts)
    return log


def _record_success(log_id: int, result: ImportResult) -> None:
    """Зафиксировать успешный итог запуска.

    Счётчики переносятся из `ImportResult` без сопоставления имён: поля
    журнала повторяют его поля один в один (ADR-021).
    """
    ImportLog.objects.filter(pk=log_id).update(
        status=ImportStatus.SUCCESS,
        finished_at=timezone.now(),
        error_code="",
        error_message="",
        **result.to_dict(),
    )

    logger.info("Import run finished: log_id=%s %s", log_id, result)


def _record_failure(log_id: int, error: Exception) -> None:
    """Зафиксировать отказ, если он терминальный.

    Повторяемая ошибка транспорта (ADR-018) итогом запуска не является:
    запись остаётся в состоянии выполнения и ждёт следующей попытки.
    """
    if getattr(error, "retryable", False):
        logger.warning(
            "Import run will be retried: log_id=%s error=%r", log_id, error
        )
        return

    ImportLog.objects.filter(pk=log_id).update(
        status=ImportStatus.FAILED,
        finished_at=timezone.now(),
        error_code=_error_code(error),
        error_message=str(error),
    )

    logger.error("Import run failed: log_id=%s error=%r", log_id, error)


def _error_code(error: Exception) -> str:
    """Сопоставить исключению код из закрытого словаря (ADR-021)."""
    for error_type, code in _ERROR_CODES:
        if isinstance(error, error_type):
            return code

    return ImportErrorCode.INTERNAL_ERROR


def mark_run_exhausted(log_id: int, error: Exception) -> None:
    """Завершить запуск отказом после исчерпания повторов (ADR-021).

    Вызывается, когда задача окончательно провалилась. Обновляются
    только записи, оставшиеся в состоянии выполнения: терминальная
    ошибка уже перевела запуск в `failed` со своим кодом, и перезаписать
    его на `retries_exhausted` означало бы потерять причину отказа.

    Без этого шага запуск, у которого исчерпан лимит попыток, навсегда
    остался бы выполняющимся: повторяемая ошибка сама по себе итогом
    запуска не является.
    """
    updated = ImportLog.objects.filter(
        pk=log_id,
        status=ImportStatus.RUNNING,
    ).update(
        status=ImportStatus.FAILED,
        finished_at=timezone.now(),
        error_code=ImportErrorCode.RETRIES_EXHAUSTED,
        error_message=str(error),
    )

    if updated:
        logger.error("Import run exhausted retries: log_id=%s error=%r", log_id, error)
