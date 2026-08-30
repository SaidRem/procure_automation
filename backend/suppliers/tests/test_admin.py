"""Тесты админки приложения suppliers (ADR-019, ADR-021)."""

from __future__ import annotations

import warnings

import pytest
from django.contrib.admin.sites import site
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils.deprecation import RemovedInDjango60Warning

from suppliers import admin as suppliers_admin
from suppliers.models import ImportLog, Shop
from users.models import User

CHANGELIST = reverse("admin:suppliers_shop_changelist")


@pytest.fixture
def superuser(db) -> User:
    """Администратор с полными правами."""
    return User.objects.create_superuser(
        email="admin@example.com",
        password="StrongPass123!",
    )


@pytest.fixture
def admin_browser(client: Client, superuser: User) -> Client:
    """Клиент, вошедший в админку администратором."""
    client.force_login(superuser)
    return client


@pytest.fixture
def import_log(shop: Shop) -> ImportLog:
    """Запись журнала импорта."""
    return ImportLog.objects.create(
        shop=shop,
        source_url="https://supplier.example/price.yaml",
    )


def actions_of(model: type, superuser: User) -> dict[str, object]:
    """Список действий админки для указанной модели."""
    request = RequestFactory().get("/")
    request.user = superuser
    return site._registry[model].get_actions(request)


def rendered(response) -> str:
    """Вернуть отрисованную страницу, убедившись, что она не пуста."""
    assert response.status_code == 200, response.status_code

    body = response.content.decode()
    assert len(body) > 500, f"подозрительно короткая страница: {len(body)} байт"

    return body


@pytest.mark.django_db
class TestOrderAcceptanceActions:
    """Действия переключения приёма заказов."""

    def test_actions_are_available(self, superuser: User) -> None:
        actions = actions_of(Shop, superuser)

        assert "enable_order_acceptance" in actions
        assert "disable_order_acceptance" in actions

    def test_disable_action_changes_the_shop(
        self, admin_browser: Client, shop: Shop
    ) -> None:
        response = admin_browser.post(
            CHANGELIST,
            {"action": "disable_order_acceptance", "_selected_action": [shop.pk]},
            follow=True,
        )

        assert "Магазинов изменено: 1." in rendered(response)

        shop.refresh_from_db()
        assert shop.state is False

    def test_enable_action_changes_the_shop(
        self, admin_browser: Client, shop: Shop
    ) -> None:
        Shop.objects.filter(pk=shop.pk).update(state=False)

        admin_browser.post(
            CHANGELIST,
            {"action": "enable_order_acceptance", "_selected_action": [shop.pk]},
        )

        shop.refresh_from_db()
        assert shop.state is True

    def test_action_delegates_to_the_service(
        self, admin_browser: Client, shop: Shop, monkeypatch
    ) -> None:
        calls: list[tuple[int, bool]] = []

        def fake_set_state(shop_id: int, *, state: bool) -> Shop:
            calls.append((shop_id, state))
            return shop

        monkeypatch.setattr(suppliers_admin, "set_shop_state", fake_set_state)

        admin_browser.post(
            CHANGELIST,
            {"action": "disable_order_acceptance", "_selected_action": [shop.pk]},
        )

        assert calls == [(shop.pk, False)]

    def test_service_is_called_for_every_selected_shop(
        self, admin_browser: Client, shop: Shop, monkeypatch
    ) -> None:
        other = Shop.objects.create(name="Ситилинк")
        calls: list[int] = []

        monkeypatch.setattr(
            suppliers_admin,
            "set_shop_state",
            lambda shop_id, *, state: calls.append(shop_id),
        )

        admin_browser.post(
            CHANGELIST,
            {
                "action": "disable_order_acceptance",
                "_selected_action": [shop.pk, other.pk],
            },
        )

        assert sorted(calls) == sorted([shop.pk, other.pk])


@pytest.mark.django_db
class TestShopPagesRender:
    """Страницы магазинов отрисовываются и показывают ожидаемое."""

    def test_changelist_shows_shops_and_actions(
        self, admin_browser: Client, shop: Shop
    ) -> None:
        body = rendered(admin_browser.get(CHANGELIST))

        assert shop.name in body
        assert "Включить приём заказов" in body
        assert "Отключить приём заказов" in body

    def test_changelist_offers_no_bulk_deletion(
        self, admin_browser: Client, shop: Shop
    ) -> None:
        body = rendered(admin_browser.get(CHANGELIST))

        assert "delete_selected" not in body

    def test_change_form_is_rendered(self, admin_browser: Client, shop: Shop) -> None:
        url = reverse("admin:suppliers_shop_change", args=[shop.pk])

        body = rendered(admin_browser.get(url))

        assert 'name="name"' in body
        assert 'name="url"' in body

    def test_change_form_has_no_delete_button(
        self, admin_browser: Client, shop: Shop
    ) -> None:
        url = reverse("admin:suppliers_shop_change", args=[shop.pk])
        delete_url = reverse("admin:suppliers_shop_delete", args=[shop.pk])

        body = rendered(admin_browser.get(url))

        assert delete_url not in body

    def test_index_lists_both_models(self, admin_browser: Client) -> None:
        body = rendered(admin_browser.get(reverse("admin:index")))

        assert "Магазины" in body
        assert "Запуски импорта" in body

    def test_change_form_renders_without_deprecation_warnings(
        self, admin_browser: Client, shop: Shop
    ) -> None:
        url = reverse("admin:suppliers_shop_change", args=[shop.pk])

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rendered(admin_browser.get(url))

        deprecations = [
            str(item.message)
            for item in caught
            if issubclass(item.category, RemovedInDjango60Warning)
        ]

        assert deprecations == []


@pytest.mark.django_db
class TestShopDeletionIsForbidden:
    """Магазин не удаляется из админки (ADR-012, ADR-019)."""

    def test_delete_page_is_denied(self, admin_browser: Client, shop: Shop) -> None:
        url = reverse("admin:suppliers_shop_delete", args=[shop.pk])

        assert admin_browser.get(url).status_code == 403

    def test_delete_selected_is_absent(self, superuser: User) -> None:
        assert "delete_selected" not in actions_of(Shop, superuser)

    def test_shop_survives_a_delete_request(
        self, admin_browser: Client, shop: Shop
    ) -> None:
        url = reverse("admin:suppliers_shop_delete", args=[shop.pk])

        admin_browser.post(url, {"post": "yes"})

        assert Shop.objects.filter(pk=shop.pk).exists()


@pytest.mark.django_db
class TestImportLogIsReadOnly:
    """Журнал импорта доступен только для просмотра (ADR-021)."""

    def test_changelist_is_rendered(
        self, admin_browser: Client, import_log: ImportLog
    ) -> None:
        url = reverse("admin:suppliers_importlog_changelist")

        body = rendered(admin_browser.get(url))

        assert "Связной" in body
        assert "В очереди" in body

    def test_detail_page_shows_values_without_inputs(
        self, admin_browser: Client, import_log: ImportLog
    ) -> None:
        url = reverse("admin:suppliers_importlog_change", args=[import_log.pk])

        body = rendered(admin_browser.get(url))

        assert import_log.task_id in body
        assert import_log.source_url in body
        assert 'name="status"' not in body
        assert 'name="attempts"' not in body
        assert 'name="error_code"' not in body

    def test_every_field_is_readonly(self) -> None:
        model_fields = {
            field.name
            for field in ImportLog._meta.get_fields()
            if field.concrete and field.name != "id"
        }

        assert set(site._registry[ImportLog].readonly_fields) == model_fields

    def test_counters_are_readonly(self) -> None:
        readonly = set(site._registry[ImportLog].readonly_fields)
        counters = {
            "offers_total",
            "created",
            "updated",
            "reactivated",
            "deactivated",
            "products_created",
            "categories_linked",
        }

        assert counters <= readonly

    def test_adding_is_denied(self, admin_browser: Client) -> None:
        url = reverse("admin:suppliers_importlog_add")

        assert admin_browser.get(url).status_code == 403

    def test_delete_page_is_denied(
        self, admin_browser: Client, import_log: ImportLog
    ) -> None:
        url = reverse("admin:suppliers_importlog_delete", args=[import_log.pk])

        assert admin_browser.get(url).status_code == 403

    def test_delete_selected_is_absent(self, superuser: User) -> None:
        assert "delete_selected" not in actions_of(ImportLog, superuser)


@pytest.mark.django_db
class TestAccess:
    """Админка закрыта для пользователей без прав персонала (ADR-023)."""

    def test_anonymous_is_redirected(self, client: Client) -> None:
        assert client.get(CHANGELIST).status_code == 302

    def test_non_staff_is_redirected(self, client: Client) -> None:
        buyer = User.objects.create_user(
            email="buyer@example.com",
            password="StrongPass123!",
            is_active=True,
        )
        client.force_login(buyer)

        assert client.get(CHANGELIST).status_code == 302
