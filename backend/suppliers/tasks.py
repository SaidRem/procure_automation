"""Фоновые задачи приложения suppliers (ADR-005).

Задача — тонкая обёртка над сервисным слоем: она принимает примитивы,
вызывает сквозной сценарий импорта и приводит результат к виду, пригодному
для result backend. Бизнес-правил здесь нет.

Повторы выполняются только для повторяемых ошибок транспорта
(`PriceSourceUnavailable`, ADR-018). Ошибки данных — разбор прайса,
валидация, несовпадение метаданных, отсутствие магазина — терминальные:
повтор дал бы тот же результат.
"""

from __future__ import annotations

from celery import shared_task

from suppliers.importers import PriceSourceUnavailable
from suppliers.services import import_supplier_price_from_url


@shared_task(
    name="suppliers.import_supplier_price",
    autoretry_for=(PriceSourceUnavailable,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def import_supplier_price_task(shop_id: int, url: str) -> dict[str, int]:
    """Загрузить прайс по ссылке и импортировать его в каталог."""
    result = import_supplier_price_from_url(shop_id, url)

    return result.to_dict()
