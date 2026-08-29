"""Тесты модели Shop (ADR-012)."""

from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError

from suppliers.models import Shop


@pytest.mark.django_db
class TestShopModel:
    """Создание магазина и его ограничения."""

    def test_create_shop_defaults(self) -> None:
        shop = Shop.objects.create(name="Связной")

        assert shop.state is True
        assert shop.url is None
        assert shop.user is None
        assert str(shop) == "Связной"

    def test_create_shop_with_url_and_user(self, shop_user) -> None:
        shop = Shop.objects.create(
            name="Связной",
            url="https://example.com/price.yaml",
            user=shop_user,
        )

        assert shop.user == shop_user
        assert shop_user.shop == shop

    def test_name_is_unique(self) -> None:
        Shop.objects.create(name="Связной")

        with pytest.raises(IntegrityError):
            Shop.objects.create(name="Связной")

    def test_user_can_own_only_one_shop(self, shop_user) -> None:
        Shop.objects.create(name="Связной", user=shop_user)

        with pytest.raises(IntegrityError):
            Shop.objects.create(name="Другой магазин", user=shop_user)

    def test_user_with_shop_cannot_be_deleted(self, shop_user) -> None:
        Shop.objects.create(name="Связной", user=shop_user)

        with pytest.raises(ProtectedError):
            shop_user.delete()

    def test_shop_cannot_be_deleted(self) -> None:
        shop = Shop.objects.create(name="Связной")

        with pytest.raises(ProtectedError):
            shop.delete()

        assert Shop.objects.filter(pk=shop.pk).exists()

    def test_state_can_be_switched_off(self) -> None:
        shop = Shop.objects.create(name="Связной", state=False)

        assert shop.state is False
