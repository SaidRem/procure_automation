"""Запись прайса поставщика в каталог (ADR-008, ADR-016).

Приложение `catalog` владеет каталогом и границей транзакции: разбор
файла и его формат — ответственность `suppliers`, которое передаёт сюда
уже подготовленные объекты `PriceData`.
"""

from __future__ import annotations

import logging
from collections import Counter

from django.db import transaction

from catalog.models import Category, Parameter, Product, ProductInfo, ProductParameter
from catalog.services.dto import ImportResult, OfferData, ParameterData, PriceData
from catalog.services.exceptions import UnknownShop
from catalog.services.validation import validate_price_data
from suppliers.models import Shop

logger = logging.getLogger(__name__)

_OFFER_FIELDS = ("product", "model", "quantity", "price", "price_rrc", "is_active")


def upsert_shop_price(shop_id: int, price: PriceData) -> ImportResult:
    """Обновить каталог магазина по данным прайса.

    Предложения обновляются на месте по ключу `(shop, external_id)`:
    `ProductInfo.id` сохраняется, отсутствующие в прайсе предложения
    помечаются `is_active=False`, вернувшиеся — реактивируются (ADR-008).
    `Product`, `Category` и `Parameter` не удаляются.

    Операция идемпотентна: повторный вызов с теми же данными каталог не
    изменяет.
    """
    validate_price_data(price)

    with transaction.atomic():
        shop = _lock_shop(shop_id)
        categories = _sync_categories(shop, price)
        counters = _upsert_offers(shop, price.offers, categories)
        deactivated = _deactivate_missing(shop, price)

    result = ImportResult(
        offers_total=len(price.offers),
        created=counters["created"],
        updated=counters["updated"],
        reactivated=counters["reactivated"],
        deactivated=deactivated,
        products_created=counters["products_created"],
        categories_linked=len(categories),
    )
    logger.info("Price imported: shop_id=%s %s", shop_id, result)
    return result


def _lock_shop(shop_id: int) -> Shop:
    """Заблокировать магазин на время импорта.

    Блокировка сериализует одновременные импорты одного поставщика:
    без неё параллельный запуск деактивирует позиции, только что
    записанные соседним импортом.
    """
    try:
        return Shop.objects.select_for_update().get(pk=shop_id)
    except Shop.DoesNotExist as error:
        raise UnknownShop(f"Магазин {shop_id} не найден.") from error


def _sync_categories(shop: Shop, price: PriceData) -> dict[str, Category]:
    """Создать недостающие категории и привязать их к магазину."""
    categories = {
        data.name: Category.objects.get_or_create(name=data.name)[0]
        for data in price.categories
    }

    if categories:
        shop.categories.add(*categories.values())

    return categories


def _upsert_offers(
    shop: Shop,
    offers: tuple[OfferData, ...],
    categories: dict[str, Category],
) -> Counter[str]:
    """Обновить предложения магазина, сохраняя идентификаторы записей."""
    existing = {info.external_id: info for info in ProductInfo.objects.filter(shop=shop)}
    parameters: dict[str, Parameter] = {}
    counters: Counter[str] = Counter()

    for offer in offers:
        product, created = Product.objects.get_or_create(
            name=offer.product_name,
            category=categories[offer.category_name],
        )
        counters["products_created"] += int(created)

        info, state = _upsert_offer(shop, offer, product, existing.get(offer.external_id))
        counters[state] += 1

        _sync_parameters(info, offer.parameters, parameters)

    return counters


def _upsert_offer(
    shop: Shop,
    offer: OfferData,
    product: Product,
    existing: ProductInfo | None,
) -> tuple[ProductInfo, str]:
    """Создать или обновить предложение, вернув его и вид изменения."""
    if existing is None:
        info = ProductInfo.objects.create(
            shop=shop,
            product=product,
            external_id=offer.external_id,
            model=offer.model,
            quantity=offer.quantity,
            price=offer.price,
            price_rrc=offer.price_rrc,
            is_active=True,
        )
        return info, "created"

    state = "updated" if existing.is_active else "reactivated"

    existing.product = product
    existing.model = offer.model
    existing.quantity = offer.quantity
    existing.price = offer.price
    existing.price_rrc = offer.price_rrc
    existing.is_active = True
    existing.save(update_fields=_OFFER_FIELDS)

    return existing, state


def _sync_parameters(
    info: ProductInfo,
    parameters: tuple[ParameterData, ...],
    cache: dict[str, Parameter],
) -> None:
    """Привести характеристики предложения к состоянию из прайса.

    Удаляются только связи `ProductParameter`; сами `Parameter`
    сохраняются (ADR-008).
    """
    desired = {data.name: data.value for data in parameters}
    links = {
        link.parameter.name: link
        for link in info.product_parameters.select_related("parameter")
    }

    for name, value in desired.items():
        link = links.get(name)

        if link is None:
            ProductParameter.objects.create(
                product_info=info,
                parameter=_get_parameter(name, cache),
                value=value,
            )
        elif link.value != value:
            link.value = value
            link.save(update_fields=["value"])

    stale = [link.pk for name, link in links.items() if name not in desired]
    if stale:
        ProductParameter.objects.filter(pk__in=stale).delete()


def _get_parameter(name: str, cache: dict[str, Parameter]) -> Parameter:
    """Вернуть характеристику по названию, создав её при необходимости."""
    if name not in cache:
        cache[name] = Parameter.objects.get_or_create(name=name)[0]

    return cache[name]


def _deactivate_missing(shop: Shop, price: PriceData) -> int:
    """Снять с продажи предложения, отсутствующие в новом прайсе.

    Нулевой остаток деактивацией не является: товар присутствует в
    прайсе, но временно отсутствует на складе (ADR-008).
    """
    present = {offer.external_id for offer in price.offers}

    return (
        ProductInfo.objects.filter(shop=shop, is_active=True)
        .exclude(external_id__in=present)
        .update(is_active=False)
    )
