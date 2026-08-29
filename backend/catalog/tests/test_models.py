"""Тесты моделей каталога (ADR-001, ADR-008, ADR-013, ADR-014, ADR-015)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError

from catalog.models import Category, Parameter, Product, ProductInfo, ProductParameter
from catalog.tests.conftest import OFFER


@pytest.mark.django_db
class TestCategory:
    """Категория каталога (ADR-013)."""

    def test_name_is_unique(self, category) -> None:
        with pytest.raises(IntegrityError):
            Category.objects.create(name=category.name)

    def test_category_is_shared_between_shops(self, category, shop, other_shop) -> None:
        category.shops.add(shop, other_shop)

        assert set(category.shops.all()) == {shop, other_shop}
        assert list(shop.categories.all()) == [category]

    def test_category_with_products_is_protected(self, category, product) -> None:
        with pytest.raises(ProtectedError):
            category.delete()


@pytest.mark.django_db
class TestProduct:
    """Логический товар (ADR-014)."""

    def test_name_is_unique_within_category(self, category, product) -> None:
        with pytest.raises(IntegrityError):
            Product.objects.create(name=product.name, category=category)

    def test_same_name_allowed_in_other_category(self, product) -> None:
        other = Category.objects.create(name="Аксессуары")

        twin = Product.objects.create(name=product.name, category=other)

        assert twin.pk != product.pk


@pytest.mark.django_db
class TestProductInfoSeparation:
    """Разделение Product и ProductInfo (ADR-001)."""

    def test_one_product_has_offers_from_several_shops(
        self, product, product_info, other_shop
    ) -> None:
        second = ProductInfo.objects.create(
            product=product,
            shop=other_shop,
            **{**OFFER, "price": Decimal("109500.50"), "external_id": 999},
        )

        assert product.product_infos.count() == 2
        assert {info.shop for info in product.product_infos.all()} == {
            product_info.shop,
            other_shop,
        }
        assert product_info.price != second.price

    def test_product_data_does_not_depend_on_offer(self, product, product_info) -> None:
        product_info.price = Decimal("100000.00")
        product_info.save(update_fields=["price"])
        product.refresh_from_db()

        assert product.name.startswith("Смартфон Apple iPhone XS Max")
        assert product.category.name == "Смартфоны"


@pytest.mark.django_db
class TestProductInfoConstraints:
    """Ключ предложения и его состояние (ADR-008, ADR-015)."""

    def test_shop_and_external_id_are_unique(self, product, shop, product_info) -> None:
        twin = Product.objects.create(name="Другой товар", category=product.category)

        with pytest.raises(IntegrityError):
            ProductInfo.objects.create(product=twin, shop=shop, **OFFER)

    def test_same_external_id_allowed_for_other_shop(
        self, product, other_shop, product_info
    ) -> None:
        second = ProductInfo.objects.create(product=product, shop=other_shop, **OFFER)

        assert second.external_id == product_info.external_id
        assert ProductInfo.objects.count() == 2

    def test_is_active_is_true_by_default(self, product_info) -> None:
        assert product_info.is_active is True

    def test_offer_can_be_deactivated(self, product_info) -> None:
        product_info.is_active = False
        product_info.save(update_fields=["is_active"])
        product_info.refresh_from_db()

        assert product_info.is_active is False

    def test_price_keeps_two_decimal_places(self, product, other_shop) -> None:
        info = ProductInfo.objects.create(
            product=product,
            shop=other_shop,
            **{**OFFER, "price": Decimal("1999.99"), "price_rrc": Decimal("2499.90")},
        )
        info.refresh_from_db()

        assert info.price == Decimal("1999.99")
        assert info.price_rrc == Decimal("2499.90")


@pytest.mark.django_db
class TestProductParameter:
    """Характеристики предложения."""

    def test_parameter_name_is_unique(self, parameter) -> None:
        with pytest.raises(IntegrityError):
            Parameter.objects.create(name=parameter.name)

    def test_value_is_unique_per_parameter(self, product_info, parameter) -> None:
        ProductParameter.objects.create(
            product_info=product_info, parameter=parameter, value="золотистый"
        )

        with pytest.raises(IntegrityError):
            ProductParameter.objects.create(
                product_info=product_info, parameter=parameter, value="чёрный"
            )

    def test_parameter_in_use_is_protected(self, product_info, parameter) -> None:
        ProductParameter.objects.create(
            product_info=product_info, parameter=parameter, value="золотистый"
        )

        with pytest.raises(ProtectedError):
            parameter.delete()

    def test_deleting_offer_removes_its_parameters(self, product_info, parameter) -> None:
        ProductParameter.objects.create(
            product_info=product_info, parameter=parameter, value="золотистый"
        )

        product_info.delete()

        assert ProductParameter.objects.count() == 0
