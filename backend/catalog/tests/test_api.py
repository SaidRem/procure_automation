"""Тесты каталожного API (ADR-025)."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from catalog.models import (
    Category,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
)
from users.models import User

LIST_URL = reverse("catalog:product-list")


def detail_url(offer: ProductInfo) -> str:
    return reverse("catalog:product-detail", args=[offer.pk])


@pytest.fixture
def buyer(db) -> User:
    return User.objects.create_user(
        email="buyer@example.com", password="StrongPass123!", is_active=True
    )


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def auth_client(api_client: APIClient, buyer: User) -> APIClient:
    access = RefreshToken.for_user(buyer).access_token
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return api_client


@pytest.mark.django_db
class TestCatalogList:
    """GET /api/catalog/products/."""

    def test_lists_active_offers(self, auth_client, product_info) -> None:
        response = auth_client.get(LIST_URL)

        assert response.status_code == 200
        assert [item["id"] for item in response.data["results"]] == [product_info.pk]

    def test_offer_fields(self, auth_client, product_info, parameter) -> None:
        ProductParameter.objects.create(
            product_info=product_info, parameter=parameter, value="золотистый"
        )

        item = auth_client.get(LIST_URL).data["results"][0]

        assert item["product_name"] == product_info.product.name
        assert item["category"] == product_info.product.category.name
        assert item["shop"] == product_info.shop.name
        assert item["shop_accepts_orders"] is True
        assert item["quantity"] == product_info.quantity
        assert item["parameters"] == [{"name": "Цвет", "value": "золотистый"}]

    def test_inactive_offer_is_hidden(self, auth_client, product_info) -> None:
        """Снятое с продажи предложение не показывается (ADR-025)."""
        product_info.is_active = False
        product_info.save(update_fields=["is_active"])

        response = auth_client.get(LIST_URL)

        assert response.data["count"] == 0

    def test_offer_of_disabled_shop_is_visible(
        self, auth_client, product_info, shop
    ) -> None:
        """Приём заказов не влияет на видимость, только на заказуемость."""
        shop.state = False
        shop.save(update_fields=["state"])

        item = auth_client.get(LIST_URL).data["results"][0]

        assert item["id"] == product_info.pk
        assert item["shop_accepts_orders"] is False

    def test_zero_stock_offer_is_visible(self, auth_client, product_info) -> None:
        """Нулевой остаток не скрывает товар (ADR-008, ADR-025)."""
        product_info.quantity = 0
        product_info.save(update_fields=["quantity"])

        assert auth_client.get(LIST_URL).data["count"] == 1

    def test_pagination(self, auth_client, shop, category) -> None:
        for index in range(25):
            product = Product.objects.create(name=f"Товар {index}", category=category)
            ProductInfo.objects.create(
                product=product,
                shop=shop,
                external_id=index,
                quantity=5,
                price="100.00",
                price_rrc="120.00",
            )

        response = auth_client.get(LIST_URL)

        assert response.data["count"] == 25
        assert len(response.data["results"]) == 20
        assert response.data["next"] is not None

        second = auth_client.get(response.data["next"])
        assert len(second.data["results"]) == 5

    def test_queries_do_not_grow_with_offers(
        self, auth_client, shop, category, django_assert_max_num_queries
    ) -> None:
        """select_related/prefetch_related защищают от N+1."""
        parameter = Parameter.objects.create(name="Цвет")
        for index in range(10):
            product = Product.objects.create(name=f"Товар {index}", category=category)
            offer = ProductInfo.objects.create(
                product=product,
                shop=shop,
                external_id=index,
                quantity=5,
                price="100.00",
                price_rrc="120.00",
            )
            ProductParameter.objects.create(
                product_info=offer, parameter=parameter, value="синий"
            )

        with django_assert_max_num_queries(6):
            auth_client.get(LIST_URL)


@pytest.mark.django_db
class TestCatalogDetail:
    """GET /api/catalog/products/{id}/."""

    def test_returns_offer(self, auth_client, product_info) -> None:
        response = auth_client.get(detail_url(product_info))

        assert response.status_code == 200
        assert response.data["id"] == product_info.pk

    def test_inactive_offer_is_not_found(self, auth_client, product_info) -> None:
        product_info.is_active = False
        product_info.save(update_fields=["is_active"])

        assert auth_client.get(detail_url(product_info)).status_code == 404


@pytest.mark.django_db
class TestCatalogPermissions:
    """Каталог доступен аутентифицированным пользователям (ADR-025)."""

    def test_anonymous_access_is_denied(self, api_client, product_info) -> None:
        assert api_client.get(LIST_URL).status_code == 401
        assert api_client.get(detail_url(product_info)).status_code == 401

    def test_write_methods_are_not_allowed(self, auth_client, product_info) -> None:
        """Каталог только на чтение: запись выполняет импорт."""
        assert auth_client.post(LIST_URL, {}, format="json").status_code == 405
        assert auth_client.delete(detail_url(product_info)).status_code == 405


@pytest.mark.django_db
class TestCatalogFilteringAndSearch:
    """Фильтрация и поиск (private/screens.md)."""

    @pytest.fixture
    def second_offer(self, other_shop, db) -> ProductInfo:
        category = Category.objects.create(name="Ноутбуки")
        product = Product.objects.create(name="Ноутбук Lenovo IdeaPad", category=category)
        return ProductInfo.objects.create(
            product=product,
            shop=other_shop,
            external_id=999,
            quantity=3,
            price="60000.00",
            price_rrc="65000.00",
        )

    def test_filter_by_shop(self, auth_client, product_info, second_offer) -> None:
        response = auth_client.get(LIST_URL, {"shop": product_info.shop_id})

        assert [item["id"] for item in response.data["results"]] == [product_info.pk]

    def test_filter_by_category(self, auth_client, product_info, second_offer) -> None:
        response = auth_client.get(
            LIST_URL, {"product__category": second_offer.product.category_id}
        )

        assert [item["id"] for item in response.data["results"]] == [second_offer.pk]

    def test_search_by_product_name(self, auth_client, product_info, second_offer) -> None:
        response = auth_client.get(LIST_URL, {"search": "Lenovo"})

        assert [item["id"] for item in response.data["results"]] == [second_offer.pk]

    def test_search_by_shop_name(self, auth_client, product_info, second_offer) -> None:
        response = auth_client.get(LIST_URL, {"search": product_info.shop.name})

        assert [item["id"] for item in response.data["results"]] == [product_info.pk]

    def test_search_by_category(self, auth_client, product_info, second_offer) -> None:
        response = auth_client.get(LIST_URL, {"search": "Ноутбуки"})

        assert [item["id"] for item in response.data["results"]] == [second_offer.pk]

    def test_search_is_case_insensitive(self, auth_client, second_offer) -> None:
        assert auth_client.get(LIST_URL, {"search": "lenovo"}).data["count"] == 1

    def test_filter_does_not_reveal_inactive(
        self, auth_client, product_info, second_offer
    ) -> None:
        """Фильтр не обходит правило видимости (ADR-025)."""
        product_info.is_active = False
        product_info.save(update_fields=["is_active"])

        response = auth_client.get(LIST_URL, {"shop": product_info.shop_id})

        assert response.data["count"] == 0

    def test_no_match_returns_empty_page(self, auth_client, product_info) -> None:
        response = auth_client.get(LIST_URL, {"search": "нет такого товара"})

        assert response.status_code == 200
        assert response.data["count"] == 0
