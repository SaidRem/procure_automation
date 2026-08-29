"""Публичный сервисный слой приложения suppliers.

Внешние вызовы (управляющие команды, API, Celery-задачи) обращаются к
импорту прайса только через этот пакет (ADR-006).
"""

from suppliers.importers.dto import SupplierPriceFile
from suppliers.services.exceptions import (
    ShopMetadataMismatch,
    ShopNotFound,
    SupplierServiceError,
)
from suppliers.services.import_pipeline import import_supplier_price_from_url
from suppliers.services.price_import import import_supplier_price

__all__ = (
    "ShopMetadataMismatch",
    "ShopNotFound",
    "SupplierPriceFile",
    "SupplierServiceError",
    "import_supplier_price",
    "import_supplier_price_from_url",
)
