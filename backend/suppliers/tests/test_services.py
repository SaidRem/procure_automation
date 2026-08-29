"""Тесты оркестрации импорта прайса поставщика (ADR-012, ADR-016)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from catalog.models import ProductInfo
from catalog.services import CategoryData, OfferData, ParameterData, PriceData
from suppliers.services import (
    ShopMetadataMismatch,
    ShopNotFound,
    SupplierPriceFile,
    import_supplier_price,
)
from suppliers.services import price_import

CATEGORY = "Смартфоны"


def make_price(external_id: int = 4216292, price: str = "110000.00") -> PriceData:
    """Прайс из одной позиции."""
    return PriceData(
        categories=(CategoryData(CATEGORY),),
        offers=(
            OfferData(
                external_id=external_id,
                product_name="Смартфон Apple iPhone XS Max 512GB",
                category_name=CATEGORY,
                quantity=14,
                price=Decimal(price),
                price_rrc=Decimal("116990.00"),
                model="apple/iphone/xs-max",
                parameters=(ParameterData("Цвет", "золотистый"),),
            ),
        ),
    )


def make_file(
    shop_name: str = "Связной",
    shop_url: str | None = None,
    price: PriceData | None = None,
) -> SupplierPriceFile:
    """Прайс поставщика вместе с метаданными магазина."""
    return SupplierPriceFile(
        shop_name=shop_name,
        shop_url=shop_url,
        price=price if price is not None else make_price(),
    )


@pytest.mark.django_db
class TestSuccessfulImport:
    """Успешный импорт."""

    def test_catalog_is_filled(self, shop) -> None:
        result = import_supplier_price(shop_id=shop.pk, supplier_price_file=make_file())

        info = ProductInfo.objects.get()
        assert info.shop == shop
        assert info.price == Decimal("110000.00")
        assert result.created == 1
        assert result.offers_total == 1

    def test_repeated_import_updates_in_place(self, shop) -> None:
        import_supplier_price(shop_id=shop.pk, supplier_price_file=make_file())
        before = ProductInfo.objects.get()

        result = import_supplier_price(
            shop_id=shop.pk, supplier_price_file=make_file(price=make_price(price="99000.00"))
        )
        after = ProductInfo.objects.get()

        assert after.pk == before.pk
        assert after.price == Decimal("99000.00")
        assert result.updated == 1

    def test_shop_fields_are_not_touched(self, shop) -> None:
        import_supplier_price(
            shop_id=shop.pk,
            supplier_price_file=make_file(shop_url="https://example.com/price.yaml"),
        )
        shop.refresh_from_db()

        assert shop.name == "Связной"
        assert shop.url is None


@pytest.mark.django_db
class TestMetadataMismatch:
    """Сверка метаданных прайса с магазином (ADR-012)."""

    def test_other_shop_name_is_rejected(self, shop) -> None:
        with pytest.raises(ShopMetadataMismatch):
            import_supplier_price(
                shop_id=shop.pk, supplier_price_file=make_file(shop_name="Мвидео")
            )

        assert ProductInfo.objects.count() == 0

    def test_shop_is_not_renamed_on_mismatch(self, shop) -> None:
        with pytest.raises(ShopMetadataMismatch):
            import_supplier_price(
                shop_id=shop.pk, supplier_price_file=make_file(shop_name="Мвидео")
            )
        shop.refresh_from_db()

        assert shop.name == "Связной"

    def test_different_url_is_rejected(self, shop) -> None:
        shop.url = "https://svyaznoy.example/price.yaml"
        shop.save(update_fields=["url"])

        with pytest.raises(ShopMetadataMismatch):
            import_supplier_price(
                shop_id=shop.pk,
                supplier_price_file=make_file(shop_url="https://other.example/price.yaml"),
            )

    def test_url_only_in_price_file_is_allowed(self, shop) -> None:
        import_supplier_price(
            shop_id=shop.pk,
            supplier_price_file=make_file(shop_url="https://example.com/price.yaml"),
        )

        assert ProductInfo.objects.count() == 1

    def test_url_only_in_shop_is_allowed(self, shop) -> None:
        shop.url = "https://svyaznoy.example/price.yaml"
        shop.save(update_fields=["url"])

        import_supplier_price(shop_id=shop.pk, supplier_price_file=make_file())

        assert ProductInfo.objects.count() == 1


@pytest.mark.django_db
class TestUnknownShop:
    """Отсутствующий магазин."""

    def test_unknown_shop_is_rejected(self, db) -> None:
        with pytest.raises(ShopNotFound):
            import_supplier_price(shop_id=999, supplier_price_file=make_file())

        assert ProductInfo.objects.count() == 0


@pytest.mark.django_db
class TestCatalogServiceCall:
    """Передача данных в catalog.services (ADR-016)."""

    def test_price_data_is_passed_unchanged(self, shop, monkeypatch) -> None:
        calls: list[tuple[int, PriceData]] = []
        price = make_price()

        def fake_upsert(shop_id: int, passed: PriceData):
            calls.append((shop_id, passed))
            return price_import.ImportResult(offers_total=len(passed.offers))

        monkeypatch.setattr(price_import, "upsert_shop_price", fake_upsert)

        result = import_supplier_price(
            shop_id=shop.pk, supplier_price_file=make_file(price=price)
        )

        assert calls == [(shop.pk, price)]
        assert calls[0][1] is price
        assert result.offers_total == 1

    def test_catalog_service_is_not_called_on_mismatch(self, shop, monkeypatch) -> None:
        def fail_upsert(*args: object, **kwargs: object):
            raise AssertionError("catalog.services не должен вызываться")

        monkeypatch.setattr(price_import, "upsert_shop_price", fail_upsert)

        with pytest.raises(ShopMetadataMismatch):
            import_supplier_price(
                shop_id=shop.pk, supplier_price_file=make_file(shop_name="Мвидео")
            )
