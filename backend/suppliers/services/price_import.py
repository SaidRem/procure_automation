"""Оркестрация импорта прайса поставщика.

Сервис связывает разобранный прайс с магазином и передаёт данные в
публичный сервисный слой каталога (ADR-016). Записью в каталог, границей
транзакции и деактивацией отсутствующих предложений (ADR-008) управляет
`catalog.services`; ORM каталога отсюда не используется.
"""

from __future__ import annotations

import logging

from catalog.services import ImportResult, upsert_shop_price
from suppliers.importers.dto import SupplierPriceFile
from suppliers.models import Shop
from suppliers.services.exceptions import ShopMetadataMismatch, ShopNotFound

logger = logging.getLogger(__name__)


def import_supplier_price(
    *,
    shop_id: int,
    supplier_price_file: SupplierPriceFile,
) -> ImportResult:
    """Импортировать прайс поставщика в каталог.

    Метаданные прайса сверяются с записью магазина и не записываются:
    переименование магазина и смена ссылки — отдельное действие домена
    `suppliers` (ADR-012). Несовпадение названия означает, что прайс
    принадлежит другому поставщику, и импорт отклоняется до записи.
    """
    shop = _get_shop(shop_id)
    _check_metadata(shop, supplier_price_file)

    logger.info(
        "Supplier price import started: shop_id=%s offers=%s",
        shop.pk,
        len(supplier_price_file.price.offers),
    )

    result = upsert_shop_price(shop.pk, supplier_price_file.price)

    logger.info("Supplier price import finished: shop_id=%s %s", shop.pk, result)
    return result


def _get_shop(shop_id: int) -> Shop:
    """Найти магазин по идентификатору."""
    try:
        return Shop.objects.get(pk=shop_id)
    except Shop.DoesNotExist as error:
        raise ShopNotFound(f"Магазин {shop_id} не найден.") from error


def _check_metadata(shop: Shop, supplier_price_file: SupplierPriceFile) -> None:
    """Сверить метаданные прайса с записью магазина.

    Название сверяется всегда. Ссылка — только если она задана и в
    прайсе, и у магазина: пустое значение означает «не указано», а не
    «отличается» (в прайсе требований ссылки нет вовсе).
    """
    if supplier_price_file.shop_name != shop.name:
        raise ShopMetadataMismatch(
            f"Прайс выставлен магазином {supplier_price_file.shop_name!r}, "
            f"а импорт выполняется для {shop.name!r}."
        )

    if supplier_price_file.shop_url and shop.url and supplier_price_file.shop_url != shop.url:
        raise ShopMetadataMismatch(
            f"Ссылка в прайсе ({supplier_price_file.shop_url}) не совпадает "
            f"со ссылкой магазина ({shop.url})."
        )
