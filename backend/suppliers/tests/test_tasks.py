"""Тесты Celery-задачи импорта прайса (ADR-005, ADR-018)."""

from __future__ import annotations

import json
import textwrap
from dataclasses import fields

import pytest

from catalog.models import ProductInfo
from catalog.services import ImportResult, InvalidPriceData
from suppliers import tasks
from suppliers.importers import (
    InsecurePriceSource,
    PriceFileTooLarge,
    PriceParseError,
    PriceSourceUnavailable,
)
from suppliers.services import ShopMetadataMismatch, ShopNotFound, import_pipeline
from suppliers.tasks import import_supplier_price_task

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


def serve(monkeypatch, content: str) -> None:
    """Подменить загрузку файла содержимым прайса."""
    monkeypatch.setattr(import_pipeline, "fetch_price_file", lambda url: content)


def fail_with(monkeypatch, error: Exception) -> dict[str, int]:
    """Подменить сервис импорта ошибкой, вернув счётчик вызовов."""
    calls = {"count": 0}

    def failing(shop_id: int, url: str):
        calls["count"] += 1
        raise error

    monkeypatch.setattr(tasks, "import_supplier_price_from_url", failing)
    return calls


@pytest.mark.django_db
class TestSuccessfulTask:
    """Успешный импорт через задачу."""

    def test_catalog_is_filled(self, shop, monkeypatch) -> None:
        serve(monkeypatch, PRICE)

        result = import_supplier_price_task(shop.pk, URL)

        info = ProductInfo.objects.get()
        assert info.shop == shop
        assert info.external_id == 4216292
        assert result["created"] == 1
        assert result["offers_total"] == 1

    def test_apply_reports_success(self, shop, monkeypatch) -> None:
        serve(monkeypatch, PRICE)

        outcome = import_supplier_price_task.apply(args=[shop.pk, URL])

        assert outcome.state == "SUCCESS"
        assert outcome.result["created"] == 1

    def test_service_receives_primitives(self, shop, monkeypatch) -> None:
        calls: list[tuple[int, str]] = []

        def fake_import(shop_id: int, url: str) -> ImportResult:
            calls.append((shop_id, url))
            return ImportResult(offers_total=1, created=1)

        monkeypatch.setattr(tasks, "import_supplier_price_from_url", fake_import)

        import_supplier_price_task(shop.pk, URL)

        assert calls == [(shop.pk, URL)]


@pytest.mark.django_db
class TestJsonResult:
    """Результат задачи пригоден для result backend."""

    def test_result_is_json_serializable(self, shop, monkeypatch) -> None:
        serve(monkeypatch, PRICE)

        result = import_supplier_price_task(shop.pk, URL)

        assert json.loads(json.dumps(result)) == result

    def test_result_contains_every_counter(self, shop, monkeypatch) -> None:
        serve(monkeypatch, PRICE)

        result = import_supplier_price_task(shop.pk, URL)

        assert set(result) == {field.name for field in fields(ImportResult)}
        assert all(isinstance(value, int) for value in result.values())


class TestRetryPolicy:
    """Повторы только для повторяемых ошибок транспорта (ADR-018)."""

    def test_autoretry_is_declared_for_transport_only(self) -> None:
        assert import_supplier_price_task.autoretry_for == (PriceSourceUnavailable,)
        assert import_supplier_price_task.max_retries == 3

    def test_source_unavailable_is_retried(self, monkeypatch) -> None:
        calls = fail_with(monkeypatch, PriceSourceUnavailable("503"))

        outcome = import_supplier_price_task.apply(args=[1, URL])

        assert calls["count"] == 4  # первая попытка и три повтора
        assert outcome.state == "FAILURE"
        assert isinstance(outcome.result, PriceSourceUnavailable)

    @pytest.mark.parametrize(
        "error",
        [
            PriceParseError("битый прайс"),
            InvalidPriceData("пустой прайс"),
            ShopMetadataMismatch("чужой магазин"),
            ShopNotFound("нет магазина"),
            InsecurePriceSource("только https"),
            PriceFileTooLarge("слишком большой"),
        ],
        ids=[
            "parse",
            "validation",
            "metadata",
            "unknown-shop",
            "insecure-source",
            "too-large",
        ],
    )
    def test_data_and_terminal_errors_are_not_retried(
        self, error: Exception, monkeypatch
    ) -> None:
        calls = fail_with(monkeypatch, error)

        outcome = import_supplier_price_task.apply(args=[1, URL])

        assert calls["count"] == 1
        assert outcome.state == "FAILURE"
        assert isinstance(outcome.result, type(error))


@pytest.mark.django_db
class TestTerminalErrorsFromRealPipeline:
    """Терминальные ошибки настоящего пайплайна не вызывают повторов."""

    def test_broken_price_fails_once(self, shop, monkeypatch) -> None:
        downloads = {"count": 0}

        def fetch(url: str) -> str:
            downloads["count"] += 1
            return "shop: Связной\ncategories: []\ngoods: []\n"

        monkeypatch.setattr(import_pipeline, "fetch_price_file", fetch)

        outcome = import_supplier_price_task.apply(args=[shop.pk, URL])

        assert downloads["count"] == 1
        assert isinstance(outcome.result, PriceParseError)
        assert ProductInfo.objects.count() == 0
