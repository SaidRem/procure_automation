"""Сквозной сценарий базовой части (private/step-5.md).

Проверяется связка приложений целиком, а не отдельные шаги: регистрация
-> подтверждение email -> вход -> каталог -> контакт -> корзина ->
оформление -> история заказов. Каждый шаг выполняется через HTTP, токен
подтверждения читается из настоящего письма — так проверяется, что
ссылка из письма действительно работает.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import Category, Product, ProductInfo
from orders.models import OrderState
from suppliers.models import Shop
from users.models import User

EMAIL = "buyer@example.com"
PASSWORD = "StrongPass123!"


@pytest.fixture(autouse=True)
def celery_eager(settings) -> None:
    """Выполнять Celery-задачи синхронно, без брокера."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture
def offer(db) -> ProductInfo:
    """Активное предложение поставщика, принимающего заказы."""
    shop = Shop.objects.create(name="Связной", state=True)
    category = Category.objects.create(name="Смартфоны")
    product = Product.objects.create(name="Смартфон Apple iPhone XS Max", category=category)
    return ProductInfo.objects.create(
        product=product,
        shop=shop,
        external_id=4216292,
        model="apple/iphone/xs-max",
        quantity=14,
        price=Decimal("110000.00"),
        price_rrc=Decimal("116990.00"),
    )


def extract(pattern: str, text: str) -> str:
    """Достать значение из письма."""
    match = re.search(pattern, text)
    assert match is not None, f"{pattern!r} не найден в письме:\n{text}"
    return match.group(1)


@pytest.mark.django_db
class TestBaseScenario:
    """Полный путь покупателя от регистрации до истории заказов."""

    def test_full_purchase_flow(
        self, offer, mailoutbox, django_capture_on_commit_callbacks
    ) -> None:
        client = APIClient()

        # 1. Регистрация: пользователь создаётся неактивным (ADR-004).
        with django_capture_on_commit_callbacks(execute=True):
            registration = client.post(
                reverse("auth:register"),
                {
                    "email": EMAIL,
                    "password": PASSWORD,
                    "first_name": "Иван",
                    "last_name": "Иванов",
                },
                format="json",
            )

        assert registration.status_code == 201
        assert User.objects.get(email=EMAIL).is_active is False

        # До подтверждения вход невозможен.
        assert client.post(
            reverse("auth:login"), {"email": EMAIL, "password": PASSWORD}, format="json"
        ).status_code == 401

        # 2. Подтверждение email по ссылке из письма (ADR-011).
        assert len(mailoutbox) == 1
        letter = mailoutbox[0].body
        confirmation = client.post(
            reverse("auth:register-confirm"),
            {
                "uid": extract(r"uid: (\S+)", letter),
                "token": extract(r"token: (\S+)", letter),
            },
            format="json",
        )

        assert confirmation.status_code == 200
        assert User.objects.get(email=EMAIL).is_active is True

        # 3. Вход: пара JWT-токенов (ADR-007).
        login = client.post(
            reverse("auth:login"), {"email": EMAIL, "password": PASSWORD}, format="json"
        )

        assert login.status_code == 200
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        # 4. Каталог: видно активное предложение (ADR-025).
        catalog = client.get(reverse("catalog:product-list"))

        assert catalog.status_code == 200
        assert catalog.data["count"] == 1
        listed = catalog.data["results"][0]
        assert listed["id"] == offer.pk
        assert listed["shop_accepts_orders"] is True

        # 5. Контакт: получатель и адрес (ADR-027).
        contact = client.post(
            reverse("users:contact-list"),
            {
                "last_name": "Петров",
                "first_name": "Пётр",
                "middle_name": "Петрович",
                "email": "recipient@example.com",
                "city": "Москва",
                "street": "Тверская",
                "house": "1",
                "phone": "+70000000000",
            },
            format="json",
        )

        assert contact.status_code == 201

        # 6. Корзина: добавление товара.
        added = client.post(
            reverse("orders:cart-items"),
            {"product_info": offer.pk, "quantity": 2},
            format="json",
        )

        assert added.status_code == 201

        cart = client.get(reverse("orders:cart"))
        assert Decimal(cart.data["total"]) == offer.price * 2

        # 7. Оформление заказа: basket -> new (ADR-022).
        mailoutbox.clear()
        with django_capture_on_commit_callbacks(execute=True):
            checkout = client.post(
                reverse("orders:checkout"),
                {"contact": contact.data["id"]},
                format="json",
            )

        assert checkout.status_code == 201
        assert checkout.data["state"] == OrderState.NEW
        assert checkout.data["confirmed_at"] is not None

        # Письма: подтверждение клиенту и накладная администратору.
        recipients = [letter.to[0] for letter in mailoutbox]
        assert EMAIL in recipients
        assert len(mailoutbox) == 2

        # 8. История заказов: «Номер, Дата, Сумма, Статус».
        history = client.get(reverse("orders:order-list"))

        assert history.status_code == 200
        assert history.data["count"] == 1
        placed = history.data["results"][0]
        assert placed["id"] == checkout.data["id"]
        assert placed["state"] == OrderState.NEW
        assert Decimal(placed["total"]) == offer.price * 2

        # Карточка заказа: snapshot позиций и адреса (ADR-003, ADR-024).
        detail = client.get(reverse("orders:order-detail", args=[placed["id"]]))

        assert detail.data["items"][0]["product_name"] == offer.product.name
        assert Decimal(detail.data["items"][0]["price"]) == offer.price
        assert detail.data["delivery"]["city"] == "Москва"
        assert detail.data["delivery"]["last_name"] == "Петров"

        # Корзина после оформления пуста, остаток не списан (ADR-022).
        offer.refresh_from_db()
        assert client.get(reverse("orders:cart")).data["items"] == []
        assert offer.quantity == 14
