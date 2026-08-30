"""Фоновые задачи приложения suppliers (ADR-005).

Задача — тонкая обёртка над сервисным слоем: она принимает примитивы,
вызывает запуск импорта и приводит результат к виду, пригодному для
result backend. Бизнес-правил и ведения журнала здесь нет.

Повторы выполняются только для повторяемых ошибок транспорта
(`PriceSourceUnavailable`, ADR-018). Ошибки данных — разбор прайса,
валидация, несовпадение метаданных, отсутствие магазина — терминальные:
повтор дал бы тот же результат.
"""

from __future__ import annotations

from celery import Task, shared_task

from suppliers.importers import PriceSourceUnavailable
from suppliers.services import mark_run_exhausted, run_logged_import


class ImportTask(Task):
    """Задача импорта с завершением журнала при окончательном провале.

    Промежуточные повторы поднимают `Retry` и сюда не попадают:
    `on_failure` вызывается один раз, когда задача провалилась
    окончательно — по терминальной ошибке или после исчерпания лимита
    попыток. Решение, нужно ли что-то записывать, принимает сервисный
    слой (ADR-006, ADR-021).
    """

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        einfo: object,
    ) -> None:
        """Сообщить сервисному слою об окончательном провале задачи."""
        mark_run_exhausted(args[2], exc)


@shared_task(
    base=ImportTask,
    name="suppliers.import_supplier_price",
    autoretry_for=(PriceSourceUnavailable,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def import_supplier_price_task(shop_id: int, url: str, log_id: int) -> dict[str, int]:
    """Выполнить запуск импорта, зарегистрированный в журнале.

    `shop_id` и `url` остаются в сигнатуре, чтобы запись в очереди была
    самоописательной: в журналах Celery и в мониторинге видно, чей прайс
    и откуда загружается. Источник истины для выполнения — запись
    журнала `log_id`: она одна переживает повторы задачи (ADR-021).
    """
    result = run_logged_import(log_id)

    return result.to_dict()
