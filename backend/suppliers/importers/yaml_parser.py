"""Разбор прайса поставщика в формате YAML.

Модуль отвечает только за формат: чтение файла, проверку структуры,
приведение типов и разрешение внешних идентификаторов категорий в их
названия (ADR-013). Результат — объекты публичного сервисного слоя
каталога (ADR-016).

Парсер не обращается к базе данных, не импортирует ORM-модели `catalog`
и ничего не создаёт: запись выполняет `catalog.services`.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import yaml

from catalog.services import (
    CategoryData,
    InvalidPriceData,
    OfferData,
    ParameterData,
    PriceData,
    validate_price_data,
)
from suppliers.importers.exceptions import PriceParseError

logger = logging.getLogger(__name__)

REQUIRED_ROOT_KEYS = ("shop", "categories", "goods")
REQUIRED_OFFER_KEYS = ("id", "category", "name", "price", "price_rrc", "quantity")

# Представление булевых характеристик в каталоге.
BOOLEAN_VALUES = {True: "да", False: "нет"}


def parse_price_yaml(yaml_content: str) -> PriceData:
    """Разобрать прайс поставщика и вернуть проверенные данные.

    Возбуждает `PriceParseError`, если файл не разбирается, не
    соответствует ожидаемой структуре или нарушает правила прайса
    (ADR-017). При успехе возвращённый `PriceData` пригоден для передачи
    в `catalog.services.upsert_shop_price` без дополнительных проверок.
    """
    data = _load(yaml_content)
    categories = _parse_categories(data["categories"])
    offers = tuple(
        _parse_offer(item, categories) for item in _as_list(data["goods"], "goods")
    )

    price = PriceData(
        categories=tuple(CategoryData(name) for name in dict.fromkeys(categories.values())),
        offers=offers,
    )

    try:
        validate_price_data(price)
    except InvalidPriceData as error:
        raise PriceParseError(str(error)) from error

    logger.info(
        "Price parsed: categories=%s offers=%s", len(price.categories), len(price.offers)
    )
    return price


def _load(yaml_content: str) -> dict[str, Any]:
    """Прочитать YAML и проверить обязательные разделы прайса."""
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as error:
        raise PriceParseError(f"Не удалось разобрать YAML: {error}") from error

    if not isinstance(data, dict):
        raise PriceParseError("Прайс должен быть YAML-отображением с разделами прайса.")

    missing = [key for key in REQUIRED_ROOT_KEYS if key not in data]
    if missing:
        raise PriceParseError(f"В прайсе отсутствуют разделы: {missing}.")

    # Название магазина в каталог не передаётся (им владеет suppliers),
    # но его отсутствие означает неполный файл.
    _as_text(data["shop"], "shop")

    return data


def _parse_categories(raw: Any) -> dict[int, str]:
    """Построить соответствие «внешний ИД категории → название».

    Соответствие существует только на время разбора: в каталоге
    внешние идентификаторы не хранятся (ADR-013).
    """
    categories: dict[int, str] = {}

    for item in _as_list(raw, "categories"):
        if not isinstance(item, dict):
            raise PriceParseError("Категория должна быть отображением с полями id и name.")

        missing = [key for key in ("id", "name") if key not in item]
        if missing:
            raise PriceParseError(f"В категории отсутствуют поля: {missing}.")

        external_id = _as_int(item["id"], "categories.id")
        if external_id in categories:
            raise PriceParseError(f"Категория с ИД {external_id} встречается дважды.")

        categories[external_id] = _as_text(item["name"], "categories.name")

    return categories


def _parse_offer(raw: Any, categories: dict[int, str]) -> OfferData:
    """Разобрать одну позицию прайса."""
    if not isinstance(raw, dict):
        raise PriceParseError("Позиция прайса должна быть отображением.")

    missing = [key for key in REQUIRED_OFFER_KEYS if key not in raw]
    if missing:
        raise PriceParseError(f"В позиции прайса отсутствуют поля: {missing}.")

    external_id = _as_int(raw["id"], "goods.id")
    category_id = _as_int(raw["category"], "goods.category")

    if category_id not in categories:
        raise PriceParseError(
            f"Позиция {external_id} ссылается на категорию {category_id}, "
            "отсутствующую в разделе categories."
        )

    return OfferData(
        external_id=external_id,
        product_name=_as_text(raw["name"], "goods.name"),
        category_name=categories[category_id],
        quantity=_as_int(raw["quantity"], "goods.quantity"),
        price=_as_money(raw["price"], "goods.price"),
        price_rrc=_as_money(raw["price_rrc"], "goods.price_rrc"),
        model=_as_text(raw.get("model", ""), "goods.model", allow_empty=True),
        parameters=_parse_parameters(raw.get("parameters")),
    )


def _parse_parameters(raw: Any) -> tuple[ParameterData, ...]:
    """Разобрать характеристики позиции, приведя значения к строке."""
    if raw is None:
        return ()

    if not isinstance(raw, dict):
        raise PriceParseError("Характеристики позиции должны быть отображением.")

    return tuple(
        ParameterData(
            name=_as_text(name, "parameters.name"),
            value=_as_parameter_value(value, name),
        )
        for name, value in raw.items()
    )


def _as_list(value: Any, field: str) -> list[Any]:
    """Проверить, что значение — список."""
    if not isinstance(value, list):
        raise PriceParseError(f"Раздел {field} должен быть списком.")

    return value


def _as_text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    """Проверить, что значение — непустая строка."""
    if not isinstance(value, str):
        raise PriceParseError(f"Поле {field} должно быть строкой, получено {value!r}.")

    if not value and not allow_empty:
        raise PriceParseError(f"Поле {field} пустое.")

    return value


def _as_int(value: Any, field: str) -> int:
    """Проверить, что значение — целое число (но не булево)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise PriceParseError(f"Поле {field} должно быть целым числом, получено {value!r}.")

    return value


def _as_money(value: Any, field: str) -> Decimal:
    """Привести денежное значение к Decimal (ADR-015)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise PriceParseError(f"Поле {field} должно быть числом, получено {value!r}.")

    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise PriceParseError(f"Поле {field} не является числом: {value!r}.") from error


def _as_parameter_value(value: Any, name: Any) -> str:
    """Привести значение характеристики к строке.

    Булево значение переводится в «да»/«нет»: YAML разбирает
    `true`/`yes`/`on` как `True`, и `str()` дал бы в карточке товара
    «True». Реальный прайс требований (`private/shop1.yaml`) содержит
    такие характеристики, поэтому отклонять их нельзя.
    """
    if isinstance(value, bool):
        return BOOLEAN_VALUES[value]

    if not isinstance(value, (str, int, float, Decimal)):
        raise PriceParseError(
            f"Характеристика {name!r} имеет неподдерживаемое значение {value!r}."
        )

    return str(value)
