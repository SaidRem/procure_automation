"""Тесты разбора прайса поставщика (ADR-013, ADR-015, ADR-017).

Ни один тест не использует фикстуру `db`: парсер не обращается к базе,
и попытка запроса привела бы к ошибке pytest-django.
"""

from __future__ import annotations

import textwrap
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings

from suppliers.importers.exceptions import PriceParseError
from suppliers.importers.yaml_parser import parse_price_yaml

PRICE = textwrap.dedent(
    """
    shop: Связной
    categories:
      - id: 224
        name: Смартфоны
      - id: 15
        name: Аксессуары

    goods:
      - id: 4216292
        category: 224
        model: apple/iphone/xs-max
        name: Смартфон Apple iPhone XS Max 512GB (золотистый)
        price: 110000
        price_rrc: 116990
        quantity: 14
        parameters:
          "Диагональ (дюйм)": 6.5
          "Встроенная память (Гб)": 512
          "Цвет": золотистый
    """
)


def price_with(goods: str, categories: str | None = None) -> str:
    """Собрать прайс с произвольными разделами goods и categories."""
    categories = categories if categories is not None else """
      - id: 224
        name: Смартфоны
"""
    return f"shop: Связной\ncategories:{categories}\ngoods:{goods}"


class TestValidPrice:
    """Разбор корректного прайса."""

    def test_returns_categories_and_offers(self) -> None:
        price = parse_price_yaml(PRICE)

        assert [category.name for category in price.categories] == [
            "Смартфоны",
            "Аксессуары",
        ]
        assert len(price.offers) == 1

    def test_external_category_id_is_resolved_to_name(self) -> None:
        offer = parse_price_yaml(PRICE).offers[0]

        assert offer.category_name == "Смартфоны"

    def test_offer_fields_are_converted(self) -> None:
        offer = parse_price_yaml(PRICE).offers[0]

        assert offer.external_id == 4216292
        assert offer.product_name.startswith("Смартфон Apple iPhone XS Max")
        assert offer.model == "apple/iphone/xs-max"
        assert offer.quantity == 14
        assert offer.price == Decimal("110000")
        assert offer.price_rrc == Decimal("116990")

    def test_parameter_values_become_strings(self) -> None:
        offer = parse_price_yaml(PRICE).offers[0]

        assert {parameter.name: parameter.value for parameter in offer.parameters} == {
            "Диагональ (дюйм)": "6.5",
            "Встроенная память (Гб)": "512",
            "Цвет": "золотистый",
        }

    def test_boolean_parameter_becomes_yes_or_no(self) -> None:
        offer = parse_price_yaml(
            price_with(
                """
      - id: 1
        category: 224
        name: Товар
        price: 100
        price_rrc: 120
        quantity: 1
        parameters:
          "Smart TV": true
          "Влагозащита": no
"""
            )
        ).offers[0]

        assert {parameter.name: parameter.value for parameter in offer.parameters} == {
            "Smart TV": "да",
            "Влагозащита": "нет",
        }

    def test_fractional_price_keeps_kopecks(self) -> None:
        price = parse_price_yaml(
            price_with(
                """
      - id: 1
        category: 224
        name: Товар
        price: 1999.99
        price_rrc: 2499.90
        quantity: 1
"""
            )
        )

        assert price.offers[0].price == Decimal("1999.99")
        assert price.offers[0].price_rrc == Decimal("2499.90")

    def test_optional_fields_have_defaults(self) -> None:
        offer = parse_price_yaml(
            price_with(
                """
      - id: 1
        category: 224
        name: Товар
        price: 100
        price_rrc: 120
        quantity: 1
"""
            )
        ).offers[0]

        assert offer.model == ""
        assert offer.parameters == ()


class TestStructureErrors:
    """Ошибки структуры файла."""

    def test_broken_yaml(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml("shop: Связной\n  goods: [")

    def test_root_is_not_a_mapping(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml("- 1\n- 2\n")

    def test_empty_document(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml("")

    @pytest.mark.parametrize("section", ["shop", "categories", "goods"])
    def test_missing_root_section(self, section: str) -> None:
        lines = [line for line in PRICE.splitlines() if not line.startswith(f"{section}:")]
        content = "\n".join(lines)

        with pytest.raises(PriceParseError):
            parse_price_yaml(content if section != "shop" else content)

    def test_shop_name_must_be_text(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml(PRICE.replace("shop: Связной", "shop: 42"))

    def test_goods_must_be_a_list(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml("shop: Связной\ncategories: []\ngoods: 5\n")

    def test_offer_without_required_field(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml(
                price_with(
                    """
      - id: 1
        category: 224
        name: Товар
        price: 100
        quantity: 1
"""
                )
            )

    def test_category_without_name(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml(
                price_with(
                    """
      - id: 1
        category: 224
        name: Товар
        price: 100
        price_rrc: 120
        quantity: 1
""",
                    categories="""
      - id: 224
""",
                )
            )

    def test_duplicate_category_id(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml(
                price_with(
                    """
      - id: 1
        category: 224
        name: Товар
        price: 100
        price_rrc: 120
        quantity: 1
""",
                    categories="""
      - id: 224
        name: Смартфоны
      - id: 224
        name: Аксессуары
""",
                )
            )

    def test_unknown_category_reference(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml(
                price_with(
                    """
      - id: 1
        category: 999
        name: Товар
        price: 100
        price_rrc: 120
        quantity: 1
"""
                )
            )

    def test_price_must_be_a_number(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml(
                price_with(
                    """
      - id: 1
        category: 224
        name: Товар
        price: дорого
        price_rrc: 120
        quantity: 1
"""
                )
            )

    def test_unsupported_parameter_value_is_rejected(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml(
                price_with(
                    """
      - id: 1
        category: 224
        name: Товар
        price: 100
        price_rrc: 120
        quantity: 1
        parameters:
          "Комплектация":
            - кабель
            - чехол
"""
                )
            )


class TestPriceRules:
    """Правила прайса, проверяемые валидацией каталога (ADR-017)."""

    def test_empty_goods_is_rejected(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml("shop: Связной\ncategories: []\ngoods: []\n")

    def test_duplicate_external_id_is_rejected(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml(
                price_with(
                    """
      - id: 1
        category: 224
        name: Товар
        price: 100
        price_rrc: 120
        quantity: 1
      - id: 1
        category: 224
        name: Другой товар
        price: 200
        price_rrc: 220
        quantity: 2
"""
                )
            )

    def test_negative_price_is_rejected(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml(
                price_with(
                    """
      - id: 1
        category: 224
        name: Товар
        price: -1
        price_rrc: 120
        quantity: 1
"""
                )
            )

    def test_negative_quantity_is_rejected(self) -> None:
        with pytest.raises(PriceParseError):
            parse_price_yaml(
                price_with(
                    """
      - id: 1
        category: 224
        name: Товар
        price: 100
        price_rrc: 120
        quantity: -5
"""
                )
            )


SHOP1 = Path(settings.BASE_DIR).parent / "private" / "shop1.yaml"


@pytest.mark.skipif(not SHOP1.exists(), reason="private/shop1.yaml недоступен")
class TestReferencePrice:
    """Разбор реального прайса из требований."""

    def test_shop1_is_parsed(self) -> None:
        price = parse_price_yaml(SHOP1.read_text(encoding="utf-8"))

        assert len(price.categories) == 4
        assert len(price.offers) == 14
        assert {category.name for category in price.categories} == {
            "Смартфоны",
            "Аксессуары",
            "Flash-накопители",
            "Телевизоры",
        }
        assert all(offer.price > 0 for offer in price.offers)
        assert all(isinstance(offer.price, Decimal) for offer in price.offers)
