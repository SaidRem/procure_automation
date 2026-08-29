"""Тесты сервиса импорта прайса (ADR-008, ADR-016, ADR-017)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from catalog.models import Category, Parameter, Product, ProductInfo, ProductParameter
from catalog.services import (
    CategoryData,
    InvalidPriceData,
    OfferData,
    ParameterData,
    PriceData,
    UnknownShop,
    upsert_shop_price,
)
from catalog.services import price_import

CATEGORY = "Смартфоны"


def make_offer(
    external_id: int = 4216292,
    product_name: str = "Смартфон Apple iPhone XS Max 512GB",
    category_name: str = CATEGORY,
    quantity: int = 14,
    price: str = "110000.00",
    price_rrc: str = "116990.00",
    model: str = "apple/iphone/xs-max",
    parameters: dict[str, str] | None = None,
) -> OfferData:
    """Собрать позицию прайса."""
    return OfferData(
        external_id=external_id,
        product_name=product_name,
        category_name=category_name,
        quantity=quantity,
        price=Decimal(price),
        price_rrc=Decimal(price_rrc),
        model=model,
        parameters=tuple(
            ParameterData(name, value) for name, value in (parameters or {}).items()
        ),
    )


def make_price(*offers: OfferData, categories: tuple[str, ...] | None = None) -> PriceData:
    """Собрать прайс из позиций; категории по умолчанию берутся из них."""
    names = categories if categories is not None else tuple(
        dict.fromkeys(offer.category_name for offer in offers)
    )
    return PriceData(
        categories=tuple(CategoryData(name) for name in names),
        offers=offers,
    )


@pytest.mark.django_db
class TestFirstImport:
    """Первый импорт в пустой каталог."""

    def test_creates_catalog(self, shop) -> None:
        result = upsert_shop_price(
            shop.pk, make_price(make_offer(parameters={"Цвет": "золотистый"}))
        )

        info = ProductInfo.objects.get()
        assert info.shop == shop
        assert info.is_active is True
        assert info.price == Decimal("110000.00")
        assert info.product.category.name == CATEGORY
        assert list(shop.categories.values_list("name", flat=True)) == [CATEGORY]
        assert info.product_parameters.get().value == "золотистый"

    def test_returns_counters(self, shop) -> None:
        result = upsert_shop_price(shop.pk, make_price(make_offer(), make_offer(external_id=2)))

        assert result.offers_total == 2
        assert result.created == 2
        assert result.updated == 0
        assert result.reactivated == 0
        assert result.deactivated == 0
        assert result.categories_linked == 1

    def test_category_without_offers_is_linked(self, shop) -> None:
        upsert_shop_price(
            shop.pk, make_price(make_offer(), categories=(CATEGORY, "Аксессуары"))
        )

        assert set(shop.categories.values_list("name", flat=True)) == {
            CATEGORY,
            "Аксессуары",
        }
        assert Product.objects.count() == 1


@pytest.mark.django_db
class TestIdempotency:
    """Повторный импорт тех же данных."""

    def test_repeated_import_keeps_ids_and_creates_nothing(self, shop) -> None:
        price = make_price(make_offer(parameters={"Цвет": "золотистый"}))
        upsert_shop_price(shop.pk, price)
        before = ProductInfo.objects.get()

        result = upsert_shop_price(shop.pk, price)
        after = ProductInfo.objects.get()

        assert after.pk == before.pk
        assert result.created == 0
        assert result.updated == 1
        assert result.products_created == 0
        assert Product.objects.count() == 1
        assert Category.objects.count() == 1
        assert Parameter.objects.count() == 1
        assert ProductParameter.objects.count() == 1

    def test_price_and_quantity_are_updated_in_place(self, shop) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer()))
        before = ProductInfo.objects.get()

        upsert_shop_price(
            shop.pk, make_price(make_offer(price="99000.50", quantity=3))
        )
        after = ProductInfo.objects.get()

        assert after.pk == before.pk
        assert after.price == Decimal("99000.50")
        assert after.quantity == 3


@pytest.mark.django_db
class TestDeactivation:
    """Снятие с продажи и возврат позиций (ADR-008)."""

    def test_missing_offer_is_deactivated_not_deleted(self, shop) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer(), make_offer(external_id=2)))

        result = upsert_shop_price(shop.pk, make_price(make_offer()))

        assert result.deactivated == 1
        assert ProductInfo.objects.count() == 2
        assert ProductInfo.objects.get(external_id=2).is_active is False

    def test_returned_offer_is_reactivated_on_the_same_row(self, shop) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer(), make_offer(external_id=2)))
        gone = ProductInfo.objects.get(external_id=2)
        upsert_shop_price(shop.pk, make_price(make_offer()))

        result = upsert_shop_price(
            shop.pk, make_price(make_offer(), make_offer(external_id=2))
        )
        back = ProductInfo.objects.get(external_id=2)

        assert back.pk == gone.pk
        assert back.is_active is True
        assert result.reactivated == 1
        assert result.created == 0
        assert ProductInfo.objects.count() == 2

    def test_zero_quantity_does_not_deactivate(self, shop) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer()))

        result = upsert_shop_price(shop.pk, make_price(make_offer(quantity=0)))
        info = ProductInfo.objects.get()

        assert info.quantity == 0
        assert info.is_active is True
        assert result.deactivated == 0

    def test_products_and_categories_survive_deactivation(self, shop) -> None:
        upsert_shop_price(
            shop.pk,
            make_price(
                make_offer(),
                make_offer(external_id=2, product_name="Смартфон Apple iPhone XR"),
            ),
        )

        upsert_shop_price(shop.pk, make_price(make_offer()))

        assert Product.objects.count() == 2
        assert Category.objects.count() == 1


@pytest.mark.django_db
class TestProductSeparation:
    """Разделение Product и ProductInfo (ADR-001, ADR-014)."""

    def test_offer_moves_to_another_product_keeping_row(self, shop) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer()))
        before = ProductInfo.objects.get()

        upsert_shop_price(
            shop.pk, make_price(make_offer(product_name="Смартфон Apple iPhone XR"))
        )
        after = ProductInfo.objects.get()

        assert after.pk == before.pk
        assert after.product.name == "Смартфон Apple iPhone XR"
        assert Product.objects.count() == 2

    def test_two_shops_share_one_product(self, shop, other_shop) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer(price="110000.00")))

        upsert_shop_price(other_shop.pk, make_price(make_offer(price="109500.50")))

        assert Product.objects.count() == 1
        assert ProductInfo.objects.count() == 2
        assert ProductInfo.objects.filter(shop=other_shop).get().price == Decimal(
            "109500.50"
        )

    def test_import_does_not_touch_other_shop(self, shop, other_shop) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer()))
        upsert_shop_price(other_shop.pk, make_price(make_offer()))

        upsert_shop_price(other_shop.pk, make_price(make_offer(external_id=999)))

        assert ProductInfo.objects.get(shop=shop).is_active is True
        assert ProductInfo.objects.get(shop=other_shop, external_id=4216292).is_active is False

    def test_category_is_shared_between_shops(self, shop, other_shop) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer()))

        upsert_shop_price(other_shop.pk, make_price(make_offer(external_id=7)))

        category = Category.objects.get()
        assert set(category.shops.all()) == {shop, other_shop}


@pytest.mark.django_db
class TestParameters:
    """Синхронизация характеристик предложения."""

    def test_parameters_are_added_updated_and_removed(self, shop) -> None:
        upsert_shop_price(
            shop.pk,
            make_price(make_offer(parameters={"Цвет": "золотистый", "Память": "512"})),
        )

        upsert_shop_price(
            shop.pk,
            make_price(make_offer(parameters={"Цвет": "чёрный", "Диагональ": "6.5"})),
        )

        info = ProductInfo.objects.get()
        assert {
            link.parameter.name: link.value for link in info.product_parameters.all()
        } == {"Цвет": "чёрный", "Диагональ": "6.5"}

    def test_unused_parameter_is_kept(self, shop) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer(parameters={"Память": "512"})))

        upsert_shop_price(shop.pk, make_price(make_offer(parameters={"Цвет": "чёрный"})))

        assert set(Parameter.objects.values_list("name", flat=True)) == {"Память", "Цвет"}
        assert ProductParameter.objects.count() == 1


@pytest.mark.django_db
class TestTransaction:
    """Атомарность импорта (ADR-008)."""

    def test_failure_rolls_back_everything(self, shop, monkeypatch) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer()))
        calls = {"count": 0}

        def failing_sync(*args: object, **kwargs: object) -> None:
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("boom")

        monkeypatch.setattr(price_import, "_sync_parameters", failing_sync)

        with pytest.raises(RuntimeError):
            upsert_shop_price(
                shop.pk,
                make_price(
                    make_offer(external_id=2, product_name="Новый товар"),
                    make_offer(external_id=3, product_name="Ещё товар"),
                ),
            )

        assert ProductInfo.objects.count() == 1
        assert ProductInfo.objects.get().is_active is True
        assert Product.objects.count() == 1


@pytest.mark.django_db
class TestUnknownShop:
    """Отсутствующий магазин."""

    def test_unknown_shop_is_rejected(self, db) -> None:
        with pytest.raises(UnknownShop):
            upsert_shop_price(999, make_price(make_offer()))

        assert ProductInfo.objects.count() == 0
        assert Category.objects.count() == 0


@pytest.mark.django_db
class TestValidation:
    """Проверки прайса до записи (ADR-017)."""

    def test_empty_price_is_rejected(self, shop) -> None:
        with pytest.raises(InvalidPriceData):
            upsert_shop_price(shop.pk, PriceData())

    def test_empty_price_does_not_deactivate_catalog(self, shop) -> None:
        upsert_shop_price(shop.pk, make_price(make_offer()))

        with pytest.raises(InvalidPriceData):
            upsert_shop_price(shop.pk, PriceData())

        assert ProductInfo.objects.get().is_active is True

    def test_duplicate_external_id_is_rejected(self, shop) -> None:
        with pytest.raises(InvalidPriceData):
            upsert_shop_price(
                shop.pk, make_price(make_offer(), make_offer(product_name="Другой"))
            )

    def test_unknown_category_is_rejected(self, shop) -> None:
        with pytest.raises(InvalidPriceData):
            upsert_shop_price(shop.pk, make_price(make_offer(), categories=("Аксессуары",)))

    def test_negative_price_is_rejected(self, shop) -> None:
        with pytest.raises(InvalidPriceData):
            upsert_shop_price(shop.pk, make_price(make_offer(price="-1.00")))

    def test_negative_quantity_is_rejected(self, shop) -> None:
        with pytest.raises(InvalidPriceData):
            upsert_shop_price(shop.pk, make_price(make_offer(quantity=-1)))

    def test_too_many_decimal_places_is_rejected(self, shop) -> None:
        with pytest.raises(InvalidPriceData):
            upsert_shop_price(shop.pk, make_price(make_offer(price="10.005")))

    def test_too_long_product_name_is_rejected(self, shop) -> None:
        with pytest.raises(InvalidPriceData):
            upsert_shop_price(shop.pk, make_price(make_offer(product_name="Т" * 81)))

    def test_too_long_parameter_value_is_rejected(self, shop) -> None:
        with pytest.raises(InvalidPriceData):
            upsert_shop_price(
                shop.pk, make_price(make_offer(parameters={"Цвет": "з" * 101}))
            )

    def test_duplicate_parameter_in_offer_is_rejected(self, shop) -> None:
        offer = OfferData(
            external_id=1,
            product_name="Товар",
            category_name=CATEGORY,
            quantity=1,
            price=Decimal("1.00"),
            price_rrc=Decimal("2.00"),
            parameters=(ParameterData("Цвет", "белый"), ParameterData("Цвет", "чёрный")),
        )

        with pytest.raises(InvalidPriceData):
            upsert_shop_price(shop.pk, make_price(offer))

    def test_nothing_is_written_on_validation_error(self, shop) -> None:
        with pytest.raises(InvalidPriceData):
            upsert_shop_price(shop.pk, make_price(make_offer(quantity=-1)))

        assert Category.objects.count() == 0
        assert Product.objects.count() == 0
