"""Публичный сервисный слой приложения catalog.

Другие домены обращаются к каталогу только через этот пакет и передают
данные объектами `PriceData` (ADR-002, ADR-016); прямой доступ к ORM
`catalog` из других приложений не допускается.
"""

from catalog.services.dto import (
    CategoryData,
    ImportResult,
    OfferData,
    ParameterData,
    PriceData,
)
from catalog.services.exceptions import (
    CatalogServiceError,
    InvalidPriceData,
    UnknownShop,
)
from catalog.services.price_import import upsert_shop_price

__all__ = (
    "CatalogServiceError",
    "CategoryData",
    "ImportResult",
    "InvalidPriceData",
    "OfferData",
    "ParameterData",
    "PriceData",
    "UnknownShop",
    "upsert_shop_price",
)
