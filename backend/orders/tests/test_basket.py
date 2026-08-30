"""Тесты сервиса корзины (ADR-009, ADR-025)."""

from __future__ import annotations

import pytest

from orders.models import Order, OrderItem, OrderState
from orders.services import (
    BasketItemNotFound,
    InsufficientStock,
    InvalidQuantity,
    OfferGone,
    OfferInactive,
    ShopNotAcceptingOrders,
    add_item,
    get_or_create_basket,
    remove_item,
    update_item_quantity,
)


@pytest.mark.django_db
class TestGetOrCreateBasket:
    """get_or_create_basket."""

    def test_creates_basket(self, buyer) -> None:
        basket = get_or_create_basket(buyer)

        assert basket.state == OrderState.BASKET
        assert basket.user == buyer
        assert basket.confirmed_at is None

    def test_returns_the_same_basket(self, buyer) -> None:
        """Повторный вызов не создаёт вторую корзину (ADR-009)."""
        first = get_or_create_basket(buyer)
        second = get_or_create_basket(buyer)

        assert first.pk == second.pk
        assert Order.objects.baskets().filter(user=buyer).count() == 1

    def test_users_have_separate_baskets(self, buyer, other_buyer) -> None:
        assert get_or_create_basket(buyer).pk != get_or_create_basket(other_buyer).pk

    def test_placed_order_does_not_become_basket(self, buyer) -> None:
        """После оформления следующий вызов создаёт новую корзину."""
        placed = get_or_create_basket(buyer)
        placed.state = OrderState.NEW
        placed.save(update_fields=["state"])

        assert get_or_create_basket(buyer).pk != placed.pk


@pytest.mark.django_db
class TestAddItem:
    """add_item."""

    def test_adds_item(self, buyer, product_info) -> None:
        item = add_item(buyer, product_info, 2)

        assert item.quantity == 2
        assert item.product_info == product_info
        assert item.order.state == OrderState.BASKET

    def test_snapshot_is_not_filled_in_basket(self, buyer, product_info) -> None:
        """До оформления цена берётся из каталога (ADR-003)."""
        item = add_item(buyer, product_info, 1)

        assert item.product_name == ""
        assert item.shop_name == ""
        assert item.price is None
        assert item.price_rrc is None

    def test_repeated_add_increases_quantity(self, buyer, product_info) -> None:
        """Одно предложение — одна строка корзины."""
        add_item(buyer, product_info, 2)
        item = add_item(buyer, product_info, 3)

        assert item.quantity == 5
        assert OrderItem.objects.filter(product_info=product_info).count() == 1

    def test_items_from_different_shops_coexist(
        self, buyer, product_info, other_product_info
    ) -> None:
        """В одном заказе товары от разных предложений."""
        add_item(buyer, product_info, 1)
        add_item(buyer, other_product_info, 1)

        assert get_or_create_basket(buyer).items.count() == 2

    @pytest.mark.parametrize("quantity", (0, -1))
    def test_non_positive_quantity_is_rejected(
        self, buyer, product_info, quantity
    ) -> None:
        with pytest.raises(InvalidQuantity):
            add_item(buyer, product_info, quantity)

        assert OrderItem.objects.count() == 0

    def test_inactive_offer_is_rejected(self, buyer, product_info) -> None:
        """Снятое с продажи предложение заказать нельзя (ADR-025)."""
        product_info.is_active = False
        product_info.save(update_fields=["is_active"])

        with pytest.raises(OfferInactive):
            add_item(buyer, product_info, 1)

        assert OrderItem.objects.count() == 0

    def test_shop_not_accepting_orders_is_rejected(
        self, buyer, product_info, shop
    ) -> None:
        """Отключённый приём заказов не скрывает товар, но не даёт заказать."""
        shop.state = False
        shop.save(update_fields=["state"])

        with pytest.raises(ShopNotAcceptingOrders):
            add_item(buyer, product_info, 1)

    def test_quantity_over_stock_is_rejected(self, buyer, product_info) -> None:
        with pytest.raises(InsufficientStock):
            add_item(buyer, product_info, product_info.quantity + 1)

    def test_repeated_add_checks_total_quantity(self, buyer, product_info) -> None:
        """Остатка должно хватать на позицию целиком, а не на добавку."""
        add_item(buyer, product_info, product_info.quantity)

        with pytest.raises(InsufficientStock):
            add_item(buyer, product_info, 1)

        assert get_or_create_basket(buyer).items.get().quantity == product_info.quantity


@pytest.mark.django_db
class TestUpdateItemQuantity:
    """update_item_quantity."""

    def test_changes_quantity(self, buyer, product_info) -> None:
        item = add_item(buyer, product_info, 2)

        updated = update_item_quantity(buyer, item.pk, 5)

        assert updated.quantity == 5
        item.refresh_from_db()
        assert item.quantity == 5

    @pytest.mark.parametrize("quantity", (0, -3))
    def test_non_positive_quantity_is_rejected(
        self, buyer, product_info, quantity
    ) -> None:
        """Ноль не удаляет позицию: для этого есть remove_item."""
        item = add_item(buyer, product_info, 2)

        with pytest.raises(InvalidQuantity):
            update_item_quantity(buyer, item.pk, quantity)

        item.refresh_from_db()
        assert item.quantity == 2

    def test_quantity_over_stock_is_rejected(self, buyer, product_info) -> None:
        item = add_item(buyer, product_info, 1)

        with pytest.raises(InsufficientStock):
            update_item_quantity(buyer, item.pk, product_info.quantity + 1)

    def test_foreign_item_is_not_found(self, buyer, other_buyer, product_info) -> None:
        """Чужая позиция неотличима от несуществующей."""
        item = add_item(other_buyer, product_info, 1)

        with pytest.raises(BasketItemNotFound):
            update_item_quantity(buyer, item.pk, 2)

        item.refresh_from_db()
        assert item.quantity == 1

    def test_item_of_deleted_offer_reports_offer_gone(
        self, buyer, product_info
    ) -> None:
        """Позиция есть, предложения нет: причина отказа своя."""
        item = add_item(buyer, product_info, 1)
        product_info.delete()

        with pytest.raises(OfferGone):
            update_item_quantity(buyer, item.pk, 2)

    def test_item_of_deleted_offer_can_be_removed(
        self, buyer, product_info
    ) -> None:
        """Удалить такую позицию из корзины покупатель может."""
        item = add_item(buyer, product_info, 1)
        product_info.delete()

        remove_item(buyer, item.pk)

        assert not OrderItem.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
class TestRemoveItem:
    """remove_item."""

    def test_removes_item(self, buyer, product_info) -> None:
        item = add_item(buyer, product_info, 2)

        remove_item(buyer, item.pk)

        assert not OrderItem.objects.filter(pk=item.pk).exists()

    def test_basket_survives_removal(self, buyer, product_info) -> None:
        """Опустошение корзины удаляет позиции, а не саму корзину."""
        item = add_item(buyer, product_info, 1)
        basket = item.order

        remove_item(buyer, item.pk)

        assert Order.objects.filter(pk=basket.pk).exists()
        assert basket.items.count() == 0

    def test_foreign_item_is_not_found(self, buyer, other_buyer, product_info) -> None:
        item = add_item(other_buyer, product_info, 1)

        with pytest.raises(BasketItemNotFound):
            remove_item(buyer, item.pk)

        assert OrderItem.objects.filter(pk=item.pk).exists()

    def test_unknown_item_is_not_found(self, buyer) -> None:
        with pytest.raises(BasketItemNotFound):
            remove_item(buyer, 10_000)
