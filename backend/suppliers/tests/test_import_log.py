"""Тесты модели журнала импорта (ADR-021)."""

from __future__ import annotations

from dataclasses import fields

import pytest
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from catalog.services import ImportResult
from suppliers.models import ImportErrorCode, ImportLog, ImportStatus, Shop
from users.models import User

URL = "https://supplier.example/price.yaml"


@pytest.fixture
def import_log(shop: Shop) -> ImportLog:
    """Запуск импорта в состоянии по умолчанию."""
    return ImportLog.objects.create(shop=shop, source_url=URL)


class TestDefaults:
    """Состояние записи сразу после постановки в очередь."""

    def test_new_run_is_queued(self, import_log: ImportLog) -> None:
        assert import_log.status == ImportStatus.QUEUED

    def test_attempts_start_at_zero(self, import_log: ImportLog) -> None:
        assert import_log.attempts == 0

    def test_counters_start_at_zero(self, import_log: ImportLog) -> None:
        counters = [field.name for field in fields(ImportResult)]

        assert [getattr(import_log, name) for name in counters] == [0] * len(counters)

    def test_queued_run_has_no_execution_timestamps(self, import_log: ImportLog) -> None:
        assert import_log.created_at is not None
        assert import_log.started_at is None
        assert import_log.finished_at is None

    def test_error_is_empty(self, import_log: ImportLog) -> None:
        assert import_log.error_code == ""
        assert import_log.error_message == ""

    def test_str_shows_shop_and_status(self, import_log: ImportLog) -> None:
        assert str(import_log) == "Связной — В очереди"


class TestImportResultContract:
    """Счётчики журнала повторяют поля `ImportResult` (ADR-021)."""

    def test_every_counter_has_a_field(self, shop: Shop) -> None:
        result = ImportResult(
            offers_total=7,
            created=3,
            updated=2,
            reactivated=1,
            deactivated=4,
            products_created=5,
            categories_linked=6,
        )

        log = ImportLog.objects.create(shop=shop, source_url=URL, **result.to_dict())

        assert {name: getattr(log, name) for name in result.to_dict()} == result.to_dict()


class TestDeletionIsForbidden:
    """Журнал импорта — исторические данные и не удаляется (ADR-021)."""

    def test_delete_raises(self, import_log: ImportLog) -> None:
        with pytest.raises(ProtectedError):
            import_log.delete()

    def test_record_survives_delete_attempt(self, import_log: ImportLog) -> None:
        with pytest.raises(ProtectedError):
            import_log.delete()

        assert ImportLog.objects.filter(pk=import_log.pk).exists()


class TestRelations:
    """Правила удаления связанных объектов."""

    def test_shop_with_logs_is_protected(self, import_log: ImportLog) -> None:
        # Массовое удаление минует `Shop.delete()`, но упирается в PROTECT.
        with pytest.raises(ProtectedError):
            Shop.objects.filter(pk=import_log.shop_id).delete()

    def test_initiator_removal_keeps_the_run(self, shop: Shop) -> None:
        operator = User.objects.create_user(
            email="operator@example.com",
            password="StrongPass123!",
            is_active=True,
            is_staff=True,
        )
        log = ImportLog.objects.create(
            shop=shop,
            source_url=URL,
            initiated_by=operator,
        )

        operator.delete()
        log.refresh_from_db()

        assert log.initiated_by is None


class TestOrdering:
    """Список запусков — от новых к старым."""

    def test_newest_first(self, shop: Shop) -> None:
        first = ImportLog.objects.create(shop=shop, source_url=URL)
        second = ImportLog.objects.create(shop=shop, source_url=URL)

        assert list(ImportLog.objects.all()) == [second, first]


class TestErrorCode:
    """Код ошибки берётся из закрытого словаря."""

    def test_unknown_code_is_rejected(self, import_log: ImportLog) -> None:
        import_log.status = ImportStatus.FAILED
        import_log.error_code = "something_went_wrong"

        with pytest.raises(ValidationError):
            import_log.full_clean()

    def test_known_code_is_accepted(self, import_log: ImportLog) -> None:
        import_log.status = ImportStatus.FAILED
        import_log.error_code = ImportErrorCode.PARSE_ERROR
        import_log.error_message = "Прайс не удалось разобрать."

        import_log.full_clean()
