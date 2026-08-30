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
def shop(db) -> Shop:
    return Shop.objects.create(name="Связной")


@pytest.fixture
def category(db) -> Category:
    return Category.objects.create(name="Смартфоны")


@pytest.fixture
def product_info(shop: Shop, category: Category) -> ProductInfo:
    product = Product.objects.create(name="Смартфон Apple iPhone XS Max", category=category)
    return ProductInfo.objects.create(product=product, shop=shop, **OFFER)


@pytest.fixture
def other_product_info(shop: Shop, category: Category) -> ProductInfo:
    """Второе предложение того же магазина."""
    product = Product.objects.create(name="Смартфон Apple iPhone 11", category=category)
    return ProductInfo.objects.create(
        product=product,
        shop=shop,
        **{**OFFER, "external_id": 4216293, "price": Decimal("54990.00")},
    )


@pytest.fixture
def incomplete_contact(buyer: User) -> Contact:
    """Контакт без данных получателя.

    Воспроизводит строку, созданную до миграции 0002_contact_recipient:
    backfill намеренно не выполнялся (ADR-027).
    """
    return Contact.objects.create(
        user=buyer,
        city="Москва",
        street="Тверская",
        phone="+70000000000",
    )
