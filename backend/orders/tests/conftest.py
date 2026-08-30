"""Фикстуры тестов приложения orders."""

from __future__ import annotations

from decimal import Decimal

import pytest

from catalog.models import Category, Product, ProductInfo
from suppliers.models import Shop
from users.models import Contact, User

OFFER = {
    "external_id": 4216292,
    "model": "apple/iphone/xs-max",
    "quantity": 14,
    "price": Decimal("110000.00"),
    "price_rrc": Decimal("116990.00"),
}


@pytest.fixture
def buyer(db) -> User:
    return User.objects.create_user(
        email="buyer@example.com",
        password="StrongPass123!",
        is_active=True,
    )


@pytest.fixture
def other_buyer(db) -> User:
    return User.objects.create_user(
        email="other@example.com",
        password="StrongPass123!",
        is_active=True,
    )


@pytest.fixture
def contact(buyer: User) -> Contact:
    return Contact.objects.create(
        user=buyer,
        last_name="Петров",
        first_name="Пётр",
        middle_name="Петрович",
        email="recipient@example.com",
        city="Москва",
        street="Тверская",
        house="1",
        phone="+70000000000",
    )


@pytest.fixture
def product_info(db) -> ProductInfo:
    shop = Shop.objects.create(name="Связной")
    category = Category.objects.create(name="Смартфоны")
    product = Product.objects.create(name="Смартфон Apple iPhone XS Max", category=category)
    return ProductInfo.objects.create(product=product, shop=shop, **OFFER)
