"""Тесты API поставщика (ADR-012, ADR-021, ADR-026)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from suppliers.models import ImportLog, ImportStatus, Shop
from users.models import User, UserType

LIST_URL = reverse("suppliers:shop-list")
PRICE_URL = "https://supplier.example/price.yaml"


def detail_url(shop: Shop) -> str:
    return reverse("suppliers:shop-detail", args=[shop.pk])


def import_url(shop: Shop) -> str:
    return reverse("suppliers:shop-import", args=[shop.pk])


def imports_url(shop: Shop) -> str:
    return reverse("suppliers:shop-imports", args=[shop.pk])


def authenticate(user: User) -> APIClient:
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}"
    )
    return client


@pytest.fixture(autouse=True)
def celery_eager(settings) -> None:
    """Не обращаться к реальному брокеру из тестов."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture
def queued_task():
    """Подменить постановку Celery-задачи.

    `_enqueue` записывает `task.id` в журнал точечным `update()`, и
    голый `MagicMock` в это поле не пишется — идентификатор должен
    быть строкой.
    """
    with patch("suppliers.tasks.import_supplier_price_task.delay") as delay:
        delay.return_value.id = "task-1"
        yield delay


@pytest.fixture
def supplier(db) -> User:
    return User.objects.create_user(
        email="supplier@example.com",
        password="StrongPass123!",
        is_active=True,
        type=UserType.SHOP,
    )


@pytest.fixture
def other_supplier(db) -> User:
    return User.objects.create_user(
        email="other@example.com",
        password="StrongPass123!",
        is_active=True,
        type=UserType.SHOP,
    )


@pytest.fixture
def buyer(db) -> User:
    return User.objects.create_user(
        email="buyer@example.com", password="StrongPass123!", is_active=True
    )


@pytest.fixture
def supplier_client(supplier: User) -> APIClient:
    return authenticate(supplier)


@pytest.fixture
def shop(supplier: User) -> Shop:
    return Shop.objects.create(name="Связной", url=PRICE_URL, user=supplier)


@pytest.fixture
def other_shop(other_supplier: User) -> Shop:
    return Shop.objects.create(name="Мвидео", url=PRICE_URL, user=other_supplier)


@pytest.mark.django_db
class TestCreateShop:
    """POST /api/suppliers/."""

    def test_creates_shop_for_current_user(self, supplier_client, supplier) -> None:
        response = supplier_client.post(
            LIST_URL, {"name": "Связной", "url": PRICE_URL}, format="json"
        )

        assert response.status_code == 201
        shop = Shop.objects.get(pk=response.data["id"])
        assert shop.user == supplier
        assert shop.url == PRICE_URL
        assert shop.state is True

    def test_owner_is_not_taken_from_request(
        self, supplier_client, supplier, other_supplier
    ) -> None:
        """Владелец берётся из токена, а не из тела запроса (ADR-012)."""
        response = supplier_client.post(
            LIST_URL,
            {"name": "Связной", "url": PRICE_URL, "user": other_supplier.pk},
            format="json",
        )

        assert Shop.objects.get(pk=response.data["id"]).user == supplier

    def test_import_is_not_started(self, supplier_client) -> None:
        """Создание магазина импорт не запускает (ADR-012)."""
        supplier_client.post(
            LIST_URL, {"name": "Связной", "url": PRICE_URL}, format="json"
        )

        assert ImportLog.objects.count() == 0

    def test_second_shop_is_rejected(self, supplier_client, shop) -> None:
        """Один пользователь — один магазин (OneToOne, ADR-012)."""
        response = supplier_client.post(
            LIST_URL, {"name": "Второй", "url": PRICE_URL}, format="json"
        )

        assert response.status_code == 400
        assert Shop.objects.filter(user=shop.user).count() == 1

    def test_duplicate_name_is_rejected(self, supplier_client, other_shop) -> None:
        response = supplier_client.post(
            LIST_URL, {"name": other_shop.name, "url": PRICE_URL}, format="json"
        )

        assert response.status_code == 400
        assert "name" in response.data

    def test_state_is_read_only(self, supplier_client) -> None:
        """Приём заказов переключается отдельным действием (ADR-012)."""
        response = supplier_client.post(
            LIST_URL,
            {"name": "Связной", "url": PRICE_URL, "state": False},
            format="json",
        )

        assert Shop.objects.get(pk=response.data["id"]).state is True


@pytest.mark.django_db
class TestRetrieveShop:
    """GET /api/suppliers/{id}/."""

    def test_returns_own_shop(self, supplier_client, shop) -> None:
        response = supplier_client.get(detail_url(shop))

        assert response.status_code == 200
        assert response.data["id"] == shop.pk
        assert response.data["url"] == PRICE_URL

    def test_foreign_shop_is_not_found(self, supplier_client, other_shop) -> None:
        """Чужой магазин неотличим от несуществующего."""
        assert supplier_client.get(detail_url(other_shop)).status_code == 404


@pytest.mark.django_db
class TestStartImport:
    """POST /api/suppliers/{id}/import/."""

    def test_returns_202_with_import_id(
        self, supplier_client, shop, queued_task, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            response = supplier_client.post(import_url(shop))

        assert response.status_code == 202
        assert response.data == {
            "import_id": ImportLog.objects.get().pk,
            "status": ImportStatus.QUEUED,
        }
        assert queued_task.call_count == 1

    def test_creates_import_log(
        self, supplier_client, shop, supplier, queued_task,
        django_capture_on_commit_callbacks,
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            supplier_client.post(import_url(shop))

        run = ImportLog.objects.get()

        assert run.shop == shop
        assert run.initiated_by == supplier
        assert run.source_url == PRICE_URL
        assert run.status == ImportStatus.QUEUED

    def test_second_import_returns_409(
        self, supplier_client, shop, queued_task, django_capture_on_commit_callbacks
    ) -> None:
        """Параллельный запуск отклоняется (ADR-026)."""
        with django_capture_on_commit_callbacks(execute=True):
            supplier_client.post(import_url(shop))

        response = supplier_client.post(import_url(shop))

        assert response.status_code == 409
        assert response.data["code"] == "import_already_running"
        assert ImportLog.objects.count() == 1

    def test_import_is_allowed_after_previous_finished(
        self, supplier_client, shop, queued_task, django_capture_on_commit_callbacks
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            supplier_client.post(import_url(shop))

        ImportLog.objects.update(status=ImportStatus.SUCCESS)

        with django_capture_on_commit_callbacks(execute=True):
            response = supplier_client.post(import_url(shop))

        assert response.status_code == 202
        assert ImportLog.objects.count() == 2

    def test_missing_url_is_rejected(self, supplier_client, supplier) -> None:
        """Импортировать не с чего: ссылка не задана."""
        shop = Shop.objects.create(name="Без ссылки", user=supplier)

        response = supplier_client.post(import_url(shop))

        assert response.status_code == 400
        assert ImportLog.objects.count() == 0

    def test_foreign_shop_is_not_found(self, supplier_client, other_shop) -> None:
        response = supplier_client.post(import_url(other_shop))

        assert response.status_code == 404
        assert ImportLog.objects.count() == 0

    def test_view_does_not_touch_downloader(
        self, supplier_client, shop, queued_task, django_capture_on_commit_callbacks
    ) -> None:
        """View ставит задачу, а не загружает прайс (ADR-018, ADR-026)."""
        with patch("suppliers.importers.downloader.fetch_price_file") as download:
            with django_capture_on_commit_callbacks(execute=True):
                supplier_client.post(import_url(shop))

        assert download.call_count == 0


@pytest.mark.django_db
class TestImportHistory:
    """GET /api/suppliers/{id}/imports/."""

    def test_lists_own_runs(self, supplier_client, shop) -> None:
        run = ImportLog.objects.create(
            shop=shop, source_url=PRICE_URL, status=ImportStatus.SUCCESS
        )

        response = supplier_client.get(imports_url(shop))

        assert response.status_code == 200
        assert [item["id"] for item in response.data["results"]] == [run.pk]

    def test_run_fields(self, supplier_client, shop) -> None:
        ImportLog.objects.create(
            shop=shop,
            source_url=PRICE_URL,
            status=ImportStatus.FAILED,
            attempts=3,
            error_code="source_unavailable",
            error_message="таймаут",
        )

        item = supplier_client.get(imports_url(shop)).data["results"][0]

        assert item["status"] == ImportStatus.FAILED
        assert item["attempts"] == 3
        assert item["error_code"] == "source_unavailable"
        assert item["error_message"] == "таймаут"

    def test_foreign_runs_are_not_visible(
        self, supplier_client, shop, other_shop
    ) -> None:
        """Поставщик не видит журнал чужого магазина."""
        ImportLog.objects.create(
            shop=other_shop, source_url=PRICE_URL, status=ImportStatus.SUCCESS
        )

        response = supplier_client.get(imports_url(shop))

        assert response.data["count"] == 0

    def test_foreign_shop_history_is_not_found(
        self, supplier_client, other_shop
    ) -> None:
        assert supplier_client.get(imports_url(other_shop)).status_code == 404


@pytest.mark.django_db
class TestPermissions:
    """Раздел доступен только поставщикам (ADR-023)."""

    def test_anonymous_access_is_denied(self, shop) -> None:
        client = APIClient()

        assert client.get(LIST_URL).status_code == 401
        assert client.get(detail_url(shop)).status_code == 401
        assert client.post(import_url(shop)).status_code == 401
        assert client.get(imports_url(shop)).status_code == 401

    def test_buyer_is_denied(self, buyer, shop) -> None:
        client = authenticate(buyer)

        assert client.get(detail_url(shop)).status_code == 403
        assert client.post(import_url(shop)).status_code == 403

    def test_delete_is_not_allowed(self, supplier_client, shop) -> None:
        """Физическое удаление магазина не предусмотрено (ADR-012)."""
        assert supplier_client.delete(detail_url(shop)).status_code == 405
        assert Shop.objects.filter(pk=shop.pk).exists()
