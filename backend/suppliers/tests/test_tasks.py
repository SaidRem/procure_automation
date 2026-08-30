"""Тесты Celery-задачи импорта прайса (ADR-005, ADR-018, ADR-021)."""

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
from suppliers.models import ImportErrorCode, ImportLog, ImportStatus, Shop
from suppliers.services import ShopMetadataMismatch, ShopNotFound, import_pipeline
from suppliers.services import import_runner
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


@pytest.fixture
def queued_run(shop: Shop) -> ImportLog:
    """Запуск импорта, зарегистрированный планировщиком."""
    return ImportLog.objects.create(shop=shop, source_url=URL)


def serve(monkeypatch, content: str) -> None:
    """Подменить загрузку файла содержимым прайса."""
    monkeypatch.setattr(import_pipeline, "fetch_price_file", lambda url: content)


def fail_with(monkeypatch, error: Exception) -> dict[str, int]:
    """Подменить запуск импорта ошибкой, вернув счётчик вызовов."""
    calls = {"count": 0}

    def failing(log_id: int):
        calls["count"] += 1
        raise error

    monkeypatch.setattr(tasks, "run_logged_import", failing)
    return calls


@pytest.mark.django_db
class TestSuccessfulTask:
    """Успешный импорт через задачу."""

    def test_catalog_is_filled(self, shop, queued_run, monkeypatch) -> None:
        serve(monkeypatch, PRICE)

        result = import_supplier_price_task(shop.pk, URL, queued_run.pk)

        info = ProductInfo.objects.get()
        assert info.shop == shop
        assert info.external_id == 4216292
        assert result["created"] == 1
        assert result["offers_total"] == 1

    def test_apply_reports_success(self, shop, queued_run, monkeypatch) -> None:
        serve(monkeypatch, PRICE)

        outcome = import_supplier_price_task.apply(args=[shop.pk, URL, queued_run.pk])

        assert outcome.state == "SUCCESS"
        assert outcome.result["created"] == 1

    def test_run_is_recorded_in_the_journal(self, shop, queued_run, monkeypatch) -> None:
        serve(monkeypatch, PRICE)

        import_supplier_price_task(shop.pk, URL, queued_run.pk)

        queued_run.refresh_from_db()
        assert queued_run.status == ImportStatus.SUCCESS
        assert queued_run.attempts == 1
        assert queued_run.created == 1


@pytest.mark.django_db
class TestTaskIsThin:
    """Задача только делегирует запуск сервисному слою (ADR-006)."""

    def test_task_delegates_to_the_runner(self, shop, queued_run, monkeypatch) -> None:
        calls: list[int] = []

        def fake_run(log_id: int) -> ImportResult:
            calls.append(log_id)
            return ImportResult(offers_total=1, created=1)

        monkeypatch.setattr(tasks, "run_logged_import", fake_run)

        import_supplier_price_task(shop.pk, URL, queued_run.pk)

        assert calls == [queued_run.pk]


@pytest.mark.django_db
class TestJsonResult:
    """Результат задачи пригоден для result backend."""

    def test_result_is_json_serializable(self, shop, queued_run, monkeypatch) -> None:
        serve(monkeypatch, PRICE)

        result = import_supplier_price_task(shop.pk, URL, queued_run.pk)

        assert json.loads(json.dumps(result)) == result

    def test_result_contains_every_counter(self, shop, queued_run, monkeypatch) -> None:
        serve(monkeypatch, PRICE)

        result = import_supplier_price_task(shop.pk, URL, queued_run.pk)

        assert set(result) == {field.name for field in fields(ImportResult)}
        assert all(isinstance(value, int) for value in result.values())


@pytest.mark.django_db
class TestRetryPolicy:
    """Повторы только для повторяемых ошибок транспорта (ADR-018).

    Записи журнала здесь нет: `log_id` указывает в пустоту, и завершение
    запуска после провала (ADR-021) не находит, что обновлять. Доступ к
    базе всё равно нужен — обработчик провала обращается к ней.
    """

    def test_autoretry_is_declared_for_transport_only(self) -> None:
        assert import_supplier_price_task.autoretry_for == (PriceSourceUnavailable,)
        assert import_supplier_price_task.max_retries == 3

    def test_source_unavailable_is_retried(self, monkeypatch) -> None:
        calls = fail_with(monkeypatch, PriceSourceUnavailable("503"))

        outcome = import_supplier_price_task.apply(args=[1, URL, 1])

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

        outcome = import_supplier_price_task.apply(args=[1, URL, 1])

        assert calls["count"] == 1
        assert outcome.state == "FAILURE"
        assert isinstance(outcome.result, type(error))


@pytest.mark.django_db
class TestTerminalErrorsFromRealPipeline:
    """Терминальные ошибки настоящего пайплайна не вызывают повторов."""

    def test_broken_price_fails_once(self, shop, queued_run, monkeypatch) -> None:
        downloads = {"count": 0}

        def fetch(url: str) -> str:
            downloads["count"] += 1
            return "shop: Связной\ncategories: []\ngoods: []\n"

        monkeypatch.setattr(import_pipeline, "fetch_price_file", fetch)

        outcome = import_supplier_price_task.apply(args=[shop.pk, URL, queued_run.pk])

        assert downloads["count"] == 1
        assert isinstance(outcome.result, PriceParseError)
        assert ProductInfo.objects.count() == 0

    def test_failure_is_recorded_in_the_journal(
        self, shop, queued_run, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            import_pipeline,
            "fetch_price_file",
            lambda url: "shop: Связной\ncategories: []\ngoods: []\n",
        )

        import_supplier_price_task.apply(args=[shop.pk, URL, queued_run.pk])

        queued_run.refresh_from_db()
        assert queued_run.status == ImportStatus.FAILED
        assert queued_run.error_message != ""


@pytest.mark.django_db
class TestRetriesExhausted:
    """Исчерпание повторов не оставляет запуск выполняющимся (ADR-021)."""

    def test_journal_is_closed_as_failed(self, shop, queued_run, monkeypatch) -> None:
        def unavailable(shop_id: int, url: str):
            raise PriceSourceUnavailable("503")

        monkeypatch.setattr(
            import_runner, "import_supplier_price_from_url", unavailable
        )

        outcome = import_supplier_price_task.apply(args=[shop.pk, URL, queued_run.pk])

        assert outcome.state == "FAILURE"
        assert isinstance(outcome.result, PriceSourceUnavailable)

        queued_run.refresh_from_db()
        assert queued_run.status == ImportStatus.FAILED
        assert queued_run.error_code == ImportErrorCode.RETRIES_EXHAUSTED
        assert queued_run.finished_at is not None
        assert queued_run.attempts == 4  # первая попытка и три повтора

    def test_terminal_error_keeps_its_own_code(
        self, shop, queued_run, monkeypatch
    ) -> None:
        def broken(shop_id: int, url: str):
            raise PriceParseError("битый прайс")

        monkeypatch.setattr(import_runner, "import_supplier_price_from_url", broken)

        import_supplier_price_task.apply(args=[shop.pk, URL, queued_run.pk])

        queued_run.refresh_from_db()
        assert queued_run.status == ImportStatus.FAILED
        assert queued_run.error_code == ImportErrorCode.PARSE_ERROR
        assert queued_run.attempts == 1
