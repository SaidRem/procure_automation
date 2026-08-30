"""Тесты управления магазином поставщика (ADR-012)."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from suppliers.models import Shop
from suppliers.services import ShopNotFound, set_shop_state


@pytest.mark.django_db
class TestOrderAcceptance:
    """Включение и отключение приёма заказов."""

    def test_acceptance_is_disabled(self, shop: Shop) -> None:
        set_shop_state(shop.pk, state=False)

        shop.refresh_from_db()
        assert shop.state is False

    def test_acceptance_is_enabled(self, shop: Shop) -> None:
        Shop.objects.filter(pk=shop.pk).update(state=False)

        set_shop_state(shop.pk, state=True)

        shop.refresh_from_db()
        assert shop.state is True

    def test_updated_shop_is_returned(self, shop: Shop) -> None:
        updated = set_shop_state(shop.pk, state=False)

        assert updated.pk == shop.pk
        assert updated.state is False


@pytest.mark.django_db
class TestIdempotence:
    """Повторный вызов с тем же значением ничего не ломает."""

    def test_repeated_call_keeps_the_state(self, shop: Shop) -> None:
        set_shop_state(shop.pk, state=False)
        set_shop_state(shop.pk, state=False)

        shop.refresh_from_db()
        assert shop.state is False

    def test_unchanged_state_is_returned(self, shop: Shop) -> None:
        assert set_shop_state(shop.pk, state=True).state is True


@pytest.mark.django_db
class TestOtherFieldsAreUntouched:
    """Операция пишет только приём заказов."""

    def test_only_state_column_is_written(self, shop: Shop) -> None:
        # Проверяется сам SQL: сравнение значений после вызова прошло бы
        # и без `update_fields`, потому что сервис перечитывает магазин
        # и полное сохранение записало бы те же данные обратно.
        with CaptureQueriesContext(connection) as queries:
            set_shop_state(shop.pk, state=False)

        updates = [
            query["sql"]
            for query in queries.captured_queries
            if query["sql"].lstrip().upper().startswith("UPDATE")
        ]

        assert len(updates) == 1
        assert '"state"' in updates[0]
        assert '"name"' not in updates[0]
        assert '"url"' not in updates[0]

    def test_name_and_url_survive(self, shop: Shop) -> None:
        set_shop_state(shop.pk, state=False)

        shop.refresh_from_db()
        assert shop.name == "Связной"
        assert shop.url is None


@pytest.mark.django_db
class TestMissingShop:
    """Несуществующий магазин переключить нельзя."""

    def test_unknown_shop_is_rejected(self) -> None:
        with pytest.raises(ShopNotFound):
            set_shop_state(404, state=False)
