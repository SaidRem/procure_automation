"""Загрузка и разбор прайсов поставщиков.

Слой отвечает за источник и формат файла и не обращается ни к базе
данных, ни к ORM каталога (ADR-016, ADR-018).
"""

from suppliers.importers.downloader import fetch_price_file
from suppliers.importers.dto import SupplierPriceFile
from suppliers.importers.exceptions import (
    InsecurePriceSource,
    PriceDownloadError,
    PriceFileTooLarge,
    PriceParseError,
    PriceSourceUnavailable,
)
from suppliers.importers.yaml_parser import parse_price_file

__all__ = (
    "InsecurePriceSource",
    "PriceDownloadError",
    "PriceFileTooLarge",
    "PriceParseError",
    "PriceSourceUnavailable",
    "SupplierPriceFile",
    "fetch_price_file",
    "parse_price_file",
)
