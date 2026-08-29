"""Проверка данных прайса перед записью в каталог (ADR-017).

Проверки выполняются до открытия транзакции: ошибочный прайс не должен
приводить ни к частичной записи, ни к массовой деактивации каталога.

Полная валидация формата файла (типы, приведение значений) выполняется в
приложении `suppliers` (ADR-016). Здесь — защита инвариантов каталога от
некорректного вызова.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from catalog.models import Category, Parameter, Product, ProductInfo, ProductParameter
from catalog.services.dto import OfferData, PriceData
from catalog.services.exceptions import InvalidPriceData

logger = logging.getLogger(__name__)


def _max_length(model: type, field_name: str) -> int:
    """Вернуть ограничение длины поля модели."""
    return model._meta.get_field(field_name).max_length


def validate_price_data(price: PriceData) -> None:
    """Проверить прайс целиком, возбуждая InvalidPriceData при нарушении."""
    try:
        _check_offers_present(price)
        _check_categories(price)
        _check_unique_external_ids(price)

        for offer in price.offers:
            _check_offer(offer)
    except InvalidPriceData as error:
        logger.warning("Price data rejected: %s", error)
        raise


def _check_offers_present(price: PriceData) -> None:
    """Прайс без позиций отклоняется: он деактивировал бы весь каталог."""
    if not price.offers:
        raise InvalidPriceData("Прайс не содержит позиций.")


def _check_categories(price: PriceData) -> None:
    """Каждая позиция должна ссылаться на категорию из того же прайса."""
    limit = _max_length(Category, "name")
    known = set()

    for category in price.categories:
        if not category.name:
            raise InvalidPriceData("Название категории пустое.")
        if len(category.name) > limit:
            raise InvalidPriceData(
                f"Название категории длиннее {limit} символов: {category.name!r}."
            )
        known.add(category.name)

    unknown = {offer.category_name for offer in price.offers} - known
    if unknown:
        raise InvalidPriceData(f"Категории отсутствуют в прайсе: {sorted(unknown)}.")


def _check_unique_external_ids(price: PriceData) -> None:
    """Внешний идентификатор позиции должен встречаться в прайсе один раз."""
    seen = set()
    duplicates = {
        offer.external_id
        for offer in price.offers
        if offer.external_id in seen or seen.add(offer.external_id)
    }

    if duplicates:
        raise InvalidPriceData(f"Дублируются внешние ИД позиций: {sorted(duplicates)}.")


def _check_offer(offer: OfferData) -> None:
    """Проверить значения и длины полей одной позиции."""
    if offer.external_id < 0:
        raise InvalidPriceData(f"Отрицательный внешний ИД: {offer.external_id}.")
    if offer.quantity < 0:
        raise InvalidPriceData(f"Отрицательное количество в позиции {offer.external_id}.")

    for name, value in (("price", offer.price), ("price_rrc", offer.price_rrc)):
        _check_money(offer, name, value)

    _check_length(offer, "product_name", offer.product_name, _max_length(Product, "name"))
    _check_length(offer, "model", offer.model, _max_length(ProductInfo, "model"))

    if not offer.product_name:
        raise InvalidPriceData(f"Пустое название товара в позиции {offer.external_id}.")

    _check_parameters(offer)


def _check_money(offer: OfferData, field_name: str, value: Decimal) -> None:
    """Проверить цену: знак, число знаков после запятой и разрядность."""
    field = ProductInfo._meta.get_field(field_name)

    if value < 0:
        raise InvalidPriceData(f"Отрицательная цена в позиции {offer.external_id}.")

    digits = value.as_tuple()
    if -digits.exponent > field.decimal_places:
        raise InvalidPriceData(
            f"Цена позиции {offer.external_id} имеет больше "
            f"{field.decimal_places} знаков после запятой."
        )
    if len(digits.digits) - (-digits.exponent) > field.max_digits - field.decimal_places:
        raise InvalidPriceData(f"Цена позиции {offer.external_id} превышает допустимую.")


def _check_parameters(offer: OfferData) -> None:
    """Проверить характеристики позиции: длины и отсутствие дубликатов."""
    name_limit = _max_length(Parameter, "name")
    value_limit = _max_length(ProductParameter, "value")
    names = set()

    for parameter in offer.parameters:
        if parameter.name in names:
            raise InvalidPriceData(
                f"Характеристика {parameter.name!r} повторяется "
                f"в позиции {offer.external_id}."
            )
        names.add(parameter.name)

        _check_length(offer, "parameter", parameter.name, name_limit)
        _check_length(offer, f"parameter {parameter.name}", parameter.value, value_limit)


def _check_length(offer: OfferData, field_name: str, value: str, limit: int) -> None:
    """Проверить, что значение укладывается в ограничение колонки."""
    if len(value) > limit:
        raise InvalidPriceData(
            f"Поле {field_name} позиции {offer.external_id} "
            f"длиннее {limit} символов."
        )
