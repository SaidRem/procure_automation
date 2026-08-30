"""Тесты админки приложения users (ADR-004, ADR-019)."""

from __future__ import annotations

import pytest
from django.contrib.admin.sites import site
from django.test import Client, RequestFactory
from django.urls import reverse

from users.models import User, UserType

CHANGELIST = reverse("admin:users_user_changelist")


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


def admin_request(superuser: User):
    """Запрос от имени администратора."""
    request = RequestFactory().get("/")
    request.user = superuser
    return request


def rendered(response) -> str:
    """Вернуть отрисованную страницу, убедившись, что она не пуста."""
    assert response.status_code == 200, response.status_code

    body = response.content.decode()
    assert len(body) > 500, f"подозрительно короткая страница: {len(body)} байт"

    return body


@pytest.mark.django_db
class TestCustomUserModelIsSupported:
    """Админка работает с моделью без поля `username` (ADR-004)."""

    def test_changelist_is_rendered(
        self, admin_browser: Client, superuser: User
    ) -> None:
        body = rendered(admin_browser.get(CHANGELIST))

        assert superuser.email in body

    def test_add_page_is_rendered(self, admin_browser: Client) -> None:
        body = rendered(admin_browser.get(reverse("admin:users_user_add")))

        assert 'name="email"' in body
        assert 'name="password1"' in body
        assert 'name="password2"' in body
        assert 'name="username"' not in body

    def test_change_page_is_rendered(
        self, admin_browser: Client, superuser: User
    ) -> None:
        url = reverse("admin:users_user_change", args=[superuser.pk])

        body = rendered(admin_browser.get(url))

        assert superuser.email in body
        assert 'name="is_staff"' in body
        assert 'name="type"' in body
        assert 'name="username"' not in body

    def test_change_page_has_no_delete_button(
        self, admin_browser: Client, superuser: User
    ) -> None:
        url = reverse("admin:users_user_change", args=[superuser.pk])
        delete_url = reverse("admin:users_user_delete", args=[superuser.pk])

        body = rendered(admin_browser.get(url))

        assert delete_url not in body

    def test_changelist_offers_no_bulk_deletion(
        self, admin_browser: Client, superuser: User
    ) -> None:
        body = rendered(admin_browser.get(CHANGELIST))

        assert "delete_selected" not in body

    def test_change_form_is_built(self, superuser: User) -> None:
        form = site._registry[User].get_form(admin_request(superuser), superuser)()

        assert "email" in form.fields
        assert "username" not in form.fields

    def test_add_form_is_built(self, superuser: User) -> None:
        model_admin = site._registry[User]
        request = admin_request(superuser)

        form = model_admin.get_form(request, obj=None, change=False)()

        assert "email" in form.fields
        assert "password1" in form.fields

    def test_new_user_can_be_created(self, superuser: User) -> None:
        model_admin = site._registry[User]
        request = admin_request(superuser)
        form_class = model_admin.get_form(request, obj=None, change=False)

        form = form_class(
            data={
                "email": "buyer@example.com",
                "type": UserType.BUYER,
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            }
        )

        assert form.is_valid(), form.errors
        created = form.save()
        assert created.email == "buyer@example.com"
        assert created.check_password("StrongPass123!")

    def test_ordering_is_by_email(self) -> None:
        assert site._registry[User].ordering == ("email",)


@pytest.mark.django_db
class TestDeletionIsForbidden:
    """Пользователь не удаляется из админки (ADR-019)."""

    def test_delete_page_is_denied(self, admin_browser: Client, superuser: User) -> None:
        url = reverse("admin:users_user_delete", args=[superuser.pk])

        assert admin_browser.get(url).status_code == 403

    def test_delete_selected_is_absent(self, superuser: User) -> None:
        actions = site._registry[User].get_actions(admin_request(superuser))

        assert "delete_selected" not in actions

    def test_user_survives_a_delete_request(
        self, admin_browser: Client, superuser: User
    ) -> None:
        buyer = User.objects.create_user(
            email="buyer@example.com",
            password="StrongPass123!",
            is_active=True,
        )
        url = reverse("admin:users_user_delete", args=[buyer.pk])

        admin_browser.post(url, {"post": "yes"})

        assert User.objects.filter(pk=buyer.pk).exists()


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
