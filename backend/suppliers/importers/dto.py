"""Объекты передачи данных слоя импорта прайса.

`SupplierPriceFile` — результат разбора файла прайса: данные каталога
вместе с метаданными магазина. Метаданные служат только для сверки с
записью `Shop`; импорт их не записывает (ADR-012).
"""

from __future__ import annotations

from dataclasses import dataclass

from catalog.services import PriceData


@dataclass(frozen=True, slots=True, kw_only=True)
class SupplierPriceFile:
    """Разобранный прайс поставщика вместе с метаданными магазина."""

    shop_name: str
    shop_url: str | None = None
    price: PriceData
