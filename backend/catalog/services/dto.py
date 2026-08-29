"""Объекты передачи данных публичного сервисного слоя catalog (ADR-016).

Приложение `suppliers` формирует эти объекты из прайса поставщика и
передаёт их в `catalog.services`. Каталог не знает ни о YAML, ни о
внешних идентификаторах категорий поставщика (ADR-013): категория
приходит по названию.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ParameterData:
    """Характеристика предложения: название и значение."""

    name: str
    value: str


@dataclass(frozen=True, slots=True)
class CategoryData:
    """Категория из прайса поставщика."""

    name: str


@dataclass(frozen=True, slots=True)
class OfferData:
    """Позиция прайса — предложение товара поставщиком."""

    external_id: int
    product_name: str
    category_name: str
    quantity: int
    price: Decimal
    price_rrc: Decimal
    model: str = ""
    parameters: tuple[ParameterData, ...] = ()


@dataclass(frozen=True, slots=True)
class PriceData:
    """Прайс поставщика целиком."""

    categories: tuple[CategoryData, ...] = ()
    offers: tuple[OfferData, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Итог импорта прайса в каталог.

    Содержит только целочисленные счётчики: результат сериализуется в
    JSON для журналов и фоновых задач (ADR-005), и значения других типов
    сломали бы сериализацию уже после успешного импорта.
    """

    offers_total: int = 0
    created: int = 0
    updated: int = 0
    reactivated: int = 0
    deactivated: int = 0
    products_created: int = 0
    categories_linked: int = 0

    def to_dict(self) -> dict[str, int]:
        """Представление результата для журналов и фоновых задач.

        Собирается из полей dataclass, поэтому новый счётчик попадает в
        результат автоматически.
        """
        return asdict(self)
