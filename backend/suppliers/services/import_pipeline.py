"""Сквозной сценарий импорта прайса по ссылке.

Модуль связывает три готовых шага: загрузку файла (ADR-018), разбор
формата (ADR-016) и запись в каталог через доменный сервис. Собственной
логики импорта здесь нет.

Celery в этом модуле отсутствует намеренно: задача (ADR-005) будет
вызывать эту функцию, а не наоборот.
"""

from __future__ import annotations

import logging

from catalog.services import ImportResult
from suppliers.importers import fetch_price_file, parse_price_file
from suppliers.services.price_import import import_supplier_price

logger = logging.getLogger(__name__)


def import_supplier_price_from_url(shop_id: int, url: str) -> ImportResult:
    """Загрузить прайс по ссылке и импортировать его в каталог.

    Принимает только примитивы, поэтому пригодна для вызова из фоновой
    задачи (ADR-005). Ошибки не подавляются: вызывающая сторона
    различает повторяемые и терминальные по типу исключения (ADR-018).
    """
    logger.info("Supplier price import from url: shop_id=%s url=%s", shop_id, url)

    content = fetch_price_file(url)
    price_file = parse_price_file(content)

    return import_supplier_price(shop_id=shop_id, supplier_price_file=price_file)
