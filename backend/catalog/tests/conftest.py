"""Фикстуры тестов приложения catalog."""

from __future__ import annotations

from decimal import Decimal

import pytest

from catalog.models import Category, Parameter, Product, ProductInfo
from suppliers.models import Shop

OFFER = {
    "external_id": 4216292,
    "model": "apple/iphone/xs-max",
    "quantity": 14,
    "price": Decimal("110000.00"),
    "price_rrc": Decimal("116990.00"),
}


@pytest.fixture
def shop(db) -> Shop:
    return Shop.objects.create(name="Связной")


@pytest.fixture
def other_shop(db) -> Shop:
    return Shop.objects.create(name="Мвидео")


@pytest.fixture
def category(db) -> Category:
    return Category.objects.create(name="Смартфоны")


@pytest.fixture
def product(category: Category) -> Product:
    return Product.objects.create(
        name="Смартфон Apple iPhone XS Max 512GB (золотистый)",
        category=category,
    )


@pytest.fixture
def product_info(product: Product, shop: Shop) -> ProductInfo:
    return ProductInfo.objects.create(product=product, shop=shop, **OFFER)


@pytest.fixture
def parameter(db) -> Parameter:
    return Parameter.objects.create(name="Цвет")
