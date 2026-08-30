"""Тесты постановки импорта в очередь (ADR-005, ADR-021)."""

from __future__ import annotations

import pytest
from django.db import transaction

from catalog.services import ImportResult
from suppliers import tasks
from suppliers.models import ImportLog, ImportStatus, Shop
from suppliers.services import PriceSourceNotConfigured, schedule_price_import
from users.models import User

URL = "https://supplier.example/price.yaml"


@pytest.fixture
def runner(monkeypatch) -> list[int]:
    """Подменить выполнение импорта, вернув список запусков."""
    started: list[int] = []

    def fake_run(log_id: int) -> ImportResult:
        started.append(log_id)
        return ImportResult(offers_total=1, created=1)

    monkeypatch.setattr(tasks, "run_logged_import", fake_run)
    return started


@pytest.mark.django_db
class TestScheduling:
    """Запись журнала создаётся до постановки задачи."""

    def test_run_is_registered_as_queued(self, shop: Shop, runner) -> None:
        log = schedule_price_import(shop_id=shop.pk, url=URL)

        assert log.status == ImportStatus.QUEUED
        assert log.attempts == 0
        assert log.shop == shop
        assert log.source_url == URL

    def test_initiator_is_stored(self, shop: Shop, runner) -> None:
        operator = User.objects.create_user(
            email="operator@example.com",
            password="StrongPass123!",
            is_active=True,
            is_staff=True,
        )

        log = schedule_price_import(shop_id=shop.pk, url=URL, initiated_by=operator)

        assert log.initiated_by == operator

    def test_initiator_is_optional(self, shop: Shop, runner) -> None:
        log = schedule_price_import(shop_id=shop.pk, url=URL)

        assert log.initiated_by is None

    def test_shop_without_url_is_rejected(self, shop: Shop, runner) -> None:
        with pytest.raises(PriceSourceNotConfigured):
            schedule_price_import(shop_id=shop.pk, url="")

        assert not ImportLog.objects.exists()


@pytest.mark.django_db
class TestTaskDispatch:
    """Задача уходит в очередь только после коммита (ADR-005)."""

    def test_task_is_not_sent_before_commit(
        self, shop: Shop, runner, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks() as callbacks:
            schedule_price_import(shop_id=shop.pk, url=URL)

            assert runner == []

        assert len(callbacks) == 1

    def test_task_runs_after_commit(
        self, shop: Shop, runner, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            log = schedule_price_import(shop_id=shop.pk, url=URL)

        assert runner == [log.pk]

    def test_task_id_is_stored(
        self, shop: Shop, runner, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            log = schedule_price_import(shop_id=shop.pk, url=URL)

        log.refresh_from_db()
        assert log.task_id != ""


@pytest.mark.django_db
class TestTransactionRollback:
    """Откат транзакции не оставляет ни журнала, ни задачи."""

    def test_rollback_leaves_nothing(
        self, shop: Shop, runner, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    schedule_price_import(shop_id=shop.pk, url=URL)
                    raise RuntimeError("сбой после регистрации запуска")

        assert callbacks == []
        assert not ImportLog.objects.exists()
        assert runner == []
