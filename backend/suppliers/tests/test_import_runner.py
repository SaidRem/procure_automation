"""Тесты выполнения запуска импорта с ведением журнала (ADR-021)."""

from __future__ import annotations

import pytest

from catalog.services import ImportResult, InvalidPriceData, UnknownShop
from suppliers.importers import (
    InsecurePriceSource,
    PriceDownloadError,
    PriceFileTooLarge,
    PriceParseError,
    PriceSourceUnavailable,
)
from suppliers.models import ImportErrorCode, ImportLog, ImportStatus, Shop
from suppliers.services import ImportRunNotFound, mark_run_exhausted, run_logged_import
from suppliers.services import import_runner
from suppliers.services.exceptions import ShopMetadataMismatch, ShopNotFound

URL = "https://supplier.example/price.yaml"

RESULT = ImportResult(
    offers_total=7,
    created=3,
    updated=2,
    reactivated=1,
    deactivated=4,
    products_created=5,
    categories_linked=6,
)


@pytest.fixture
def queued_run(shop: Shop) -> ImportLog:
    """Запуск импорта, ожидающий выполнения."""
    return ImportLog.objects.create(shop=shop, source_url=URL)


def succeed_with(monkeypatch, result: ImportResult) -> list[tuple[int, str]]:
    """Подменить импорт успешным результатом, вернув список вызовов."""
    calls: list[tuple[int, str]] = []

    def fake_import(shop_id: int, url: str) -> ImportResult:
        calls.append((shop_id, url))
        return result

    monkeypatch.setattr(import_runner, "import_supplier_price_from_url", fake_import)
    return calls


def fail_with(monkeypatch, error: Exception) -> None:
    """Подменить импорт ошибкой."""

    def failing(shop_id: int, url: str) -> ImportResult:
        raise error

    monkeypatch.setattr(import_runner, "import_supplier_price_from_url", failing)


@pytest.mark.django_db
class TestSuccessfulRun:
    """Успешный запуск: queued → running → success."""

    def test_status_becomes_success(self, queued_run: ImportLog, monkeypatch) -> None:
        succeed_with(monkeypatch, RESULT)

        run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        assert queued_run.status == ImportStatus.SUCCESS

    def test_counters_are_stored(self, queued_run: ImportLog, monkeypatch) -> None:
        succeed_with(monkeypatch, RESULT)

        run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        stored = {name: getattr(queued_run, name) for name in RESULT.to_dict()}
        assert stored == RESULT.to_dict()

    def test_timestamps_are_filled(self, queued_run: ImportLog, monkeypatch) -> None:
        succeed_with(monkeypatch, RESULT)

        run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        assert queued_run.started_at is not None
        assert queued_run.finished_at is not None

    def test_attempt_is_counted(self, queued_run: ImportLog, monkeypatch) -> None:
        succeed_with(monkeypatch, RESULT)

        run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        assert queued_run.attempts == 1

    def test_source_is_taken_from_the_journal(
        self, queued_run: ImportLog, monkeypatch
    ) -> None:
        calls = succeed_with(monkeypatch, RESULT)

        run_logged_import(queued_run.pk)

        assert calls == [(queued_run.shop_id, URL)]

    def test_result_is_returned(self, queued_run: ImportLog, monkeypatch) -> None:
        succeed_with(monkeypatch, RESULT)

        assert run_logged_import(queued_run.pk) == RESULT


@pytest.mark.django_db
class TestTerminalFailure:
    """Терминальная ошибка завершает запуск отказом."""

    def test_status_becomes_failed(self, queued_run: ImportLog, monkeypatch) -> None:
        fail_with(monkeypatch, PriceParseError("битый прайс"))

        with pytest.raises(PriceParseError):
            run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        assert queued_run.status == ImportStatus.FAILED

    def test_error_is_recorded(self, queued_run: ImportLog, monkeypatch) -> None:
        fail_with(monkeypatch, PriceParseError("битый прайс"))

        with pytest.raises(PriceParseError):
            run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        assert queued_run.error_code == ImportErrorCode.PARSE_ERROR
        assert queued_run.error_message == "битый прайс"
        assert queued_run.finished_at is not None

    def test_counters_stay_empty(self, queued_run: ImportLog, monkeypatch) -> None:
        fail_with(monkeypatch, PriceParseError("битый прайс"))

        with pytest.raises(PriceParseError):
            run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        assert queued_run.offers_total == 0
        assert queued_run.created == 0

    @pytest.mark.parametrize(
        ("error", "code"),
        [
            (InsecurePriceSource("только https"), ImportErrorCode.INSECURE_SOURCE),
            (PriceFileTooLarge("слишком большой"), ImportErrorCode.FILE_TOO_LARGE),
            (PriceDownloadError("404"), ImportErrorCode.DOWNLOAD_ERROR),
            (PriceParseError("битый прайс"), ImportErrorCode.PARSE_ERROR),
            (InvalidPriceData("пустой прайс"), ImportErrorCode.INVALID_PRICE_DATA),
            (ShopMetadataMismatch("чужой прайс"), ImportErrorCode.SHOP_METADATA_MISMATCH),
            (ShopNotFound("нет магазина"), ImportErrorCode.SHOP_NOT_FOUND),
            (UnknownShop("нет магазина"), ImportErrorCode.SHOP_NOT_FOUND),
            (ValueError("что-то пошло не так"), ImportErrorCode.INTERNAL_ERROR),
        ],
        ids=[
            "insecure-source",
            "too-large",
            "download",
            "parse",
            "validation",
            "metadata",
            "shop-not-found",
            "unknown-shop",
            "unexpected",
        ],
    )
    def test_error_code_matches_the_exception(
        self, queued_run: ImportLog, monkeypatch, error: Exception, code: str
    ) -> None:
        fail_with(monkeypatch, error)

        with pytest.raises(type(error)):
            run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        assert queued_run.error_code == code


@pytest.mark.django_db
class TestRetryableFailure:
    """Повторяемая ошибка транспорта запуск не завершает (ADR-018)."""

    def test_run_stays_in_progress(self, queued_run: ImportLog, monkeypatch) -> None:
        fail_with(monkeypatch, PriceSourceUnavailable("503"))

        with pytest.raises(PriceSourceUnavailable):
            run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        assert queued_run.status == ImportStatus.RUNNING
        assert queued_run.finished_at is None
        assert queued_run.error_code == ""

    def test_retries_share_one_record(self, queued_run: ImportLog, monkeypatch) -> None:
        fail_with(monkeypatch, PriceSourceUnavailable("503"))

        for _ in range(3):
            with pytest.raises(PriceSourceUnavailable):
                run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        assert ImportLog.objects.count() == 1
        assert queued_run.attempts == 3

    def test_retry_can_still_succeed(self, queued_run: ImportLog, monkeypatch) -> None:
        fail_with(monkeypatch, PriceSourceUnavailable("503"))

        with pytest.raises(PriceSourceUnavailable):
            run_logged_import(queued_run.pk)

        succeed_with(monkeypatch, RESULT)
        run_logged_import(queued_run.pk)

        queued_run.refresh_from_db()
        assert queued_run.status == ImportStatus.SUCCESS
        assert queued_run.attempts == 2


@pytest.mark.django_db
class TestMissingRun:
    """Запуск без записи журнала выполнить нельзя."""

    def test_unknown_log_is_rejected(self, monkeypatch) -> None:
        succeed_with(monkeypatch, RESULT)

        with pytest.raises(ImportRunNotFound):
            run_logged_import(404)


@pytest.mark.django_db
class TestRetriesExhausted:
    """Исчерпание повторов завершает запуск отказом (ADR-021)."""

    def test_running_run_becomes_failed(self, queued_run: ImportLog, monkeypatch) -> None:
        fail_with(monkeypatch, PriceSourceUnavailable("503"))

        with pytest.raises(PriceSourceUnavailable):
            run_logged_import(queued_run.pk)

        mark_run_exhausted(queued_run.pk, PriceSourceUnavailable("503"))

        queued_run.refresh_from_db()
        assert queued_run.status == ImportStatus.FAILED
        assert queued_run.error_code == ImportErrorCode.RETRIES_EXHAUSTED
        assert queued_run.error_message == "503"
        assert queued_run.finished_at is not None

    def test_terminal_failure_keeps_its_own_code(
        self, queued_run: ImportLog, monkeypatch
    ) -> None:
        fail_with(monkeypatch, PriceParseError("битый прайс"))

        with pytest.raises(PriceParseError):
            run_logged_import(queued_run.pk)

        mark_run_exhausted(queued_run.pk, PriceParseError("битый прайс"))

        queued_run.refresh_from_db()
        assert queued_run.error_code == ImportErrorCode.PARSE_ERROR

    def test_successful_run_is_not_touched(
        self, queued_run: ImportLog, monkeypatch
    ) -> None:
        succeed_with(monkeypatch, RESULT)
        run_logged_import(queued_run.pk)

        mark_run_exhausted(queued_run.pk, PriceSourceUnavailable("503"))

        queued_run.refresh_from_db()
        assert queued_run.status == ImportStatus.SUCCESS
        assert queued_run.error_code == ""

    def test_attempts_are_preserved(self, queued_run: ImportLog, monkeypatch) -> None:
        fail_with(monkeypatch, PriceSourceUnavailable("503"))

        for _ in range(2):
            with pytest.raises(PriceSourceUnavailable):
                run_logged_import(queued_run.pk)

        mark_run_exhausted(queued_run.pk, PriceSourceUnavailable("503"))

        queued_run.refresh_from_db()
        assert queued_run.attempts == 2
