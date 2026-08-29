"""Тесты сквозного импорта прайса по ссылке."""

from __future__ import annotations

import textwrap
from decimal import Decimal

import pytest

from catalog.models import ProductInfo
from suppliers.importers.exceptions import (
    InsecurePriceSource,
    PriceFileTooLarge,
    PriceParseError,
    PriceSourceUnavailable,
)
from suppliers.services import ShopMetadataMismatch, import_supplier_price_from_url
from suppliers.services import import_pipeline

URL = "https://supplier.example/price.yaml"

PRICE = textwrap.dedent(
    """
    shop: Связной
    categories:
      - id: 224
        name: Смартфоны
    goods:
      - id: 4216292
        category: 224
        model: apple/iphone/xs-max
        name: Смартфон Apple iPhone XS Max 512GB
        price: 110000
        price_rrc: 116990
        quantity: 14
        parameters:
          "Цвет": золотистый
    """
)


def serve(monkeypatch, content: str | Exception) -> list[str]:
    """Подменить загрузку файла, вернув журнал запрошенных ссылок."""
    urls: list[str] = []

    def fake_fetch(url: str) -> str:
        urls.append(url)
        if isinstance(content, Exception):
            raise content
        return content

    monkeypatch.setattr(import_pipeline, "fetch_price_file", fake_fetch)
    return urls


@pytest.mark.django_db
class TestSuccessfulImport:
    """Успешная загрузка и импорт."""

    def test_catalog_is_filled(self, shop, monkeypatch) -> None:
        urls = serve(monkeypatch, PRICE)

        result = import_supplier_price_from_url(shop.pk, URL)

        info = ProductInfo.objects.get()
        assert urls == [URL]
        assert info.shop == shop
        assert info.price == Decimal("110000")
        assert info.product_parameters.get().value == "золотистый"
        assert result.created == 1

    def test_repeated_import_is_idempotent(self, shop, monkeypatch) -> None:
        serve(monkeypatch, PRICE)
        import_supplier_price_from_url(shop.pk, URL)
        before = ProductInfo.objects.get()

        result = import_supplier_price_from_url(shop.pk, URL)

        assert ProductInfo.objects.get().pk == before.pk
        assert result.created == 0
        assert result.updated == 1


@pytest.mark.django_db
class TestTransportErrors:
    """Ошибки загрузки доходят до вызывающей стороны (ADR-018)."""

    def test_timeout_is_propagated(self, shop, monkeypatch) -> None:
        serve(monkeypatch, PriceSourceUnavailable("таймаут"))

        with pytest.raises(PriceSourceUnavailable) as error:
            import_supplier_price_from_url(shop.pk, URL)

        assert error.value.retryable is True
        assert ProductInfo.objects.count() == 0

    def test_unavailable_source_leaves_catalog_untouched(self, shop, monkeypatch) -> None:
        serve(monkeypatch, PRICE)
        import_supplier_price_from_url(shop.pk, URL)
        serve(monkeypatch, PriceSourceUnavailable("503"))

        with pytest.raises(PriceSourceUnavailable):
            import_supplier_price_from_url(shop.pk, URL)

        assert ProductInfo.objects.get().is_active is True

    def test_too_large_file_is_terminal(self, shop, monkeypatch) -> None:
        serve(monkeypatch, PriceFileTooLarge("слишком большой"))

        with pytest.raises(PriceFileTooLarge) as error:
            import_supplier_price_from_url(shop.pk, URL)

        assert error.value.retryable is False

    def test_insecure_url_is_terminal(self, shop, monkeypatch) -> None:
        serve(monkeypatch, InsecurePriceSource("только https"))

        with pytest.raises(InsecurePriceSource):
            import_supplier_price_from_url(shop.pk, URL)


@pytest.mark.django_db
class TestContentErrors:
    """Ошибки содержимого прайса."""

    def test_broken_price_is_rejected(self, shop, monkeypatch) -> None:
        serve(monkeypatch, "shop: Связной\ncategories: []\ngoods: []\n")

        with pytest.raises(PriceParseError):
            import_supplier_price_from_url(shop.pk, URL)

        assert ProductInfo.objects.count() == 0

    def test_metadata_mismatch_is_rejected(self, shop, monkeypatch) -> None:
        serve(monkeypatch, PRICE.replace("shop: Связной", "shop: Мвидео"))

        with pytest.raises(ShopMetadataMismatch):
            import_supplier_price_from_url(shop.pk, URL)

        assert ProductInfo.objects.count() == 0
