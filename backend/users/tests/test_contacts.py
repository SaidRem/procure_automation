"""Тесты контактов (адресов доставки) пользователя."""

from __future__ import annotations

import pytest
from django.urls import reverse

from users.models import Contact

LIST_URL = reverse("users:contact-list")


def detail_url(contact: Contact) -> str:
    return reverse("users:contact-detail", args=[contact.pk])


@pytest.fixture
def contact_payload() -> dict[str, str]:
    return {
        "city": "Москва",
        "street": "Тверская",
        "house": "1",
        "phone": "+70000000000",
    }


@pytest.mark.django_db
class TestContacts:
    """/api/users/contacts/."""

    def test_create_contact(self, auth_client, active_user, contact_payload) -> None:
        response = auth_client.post(LIST_URL, contact_payload, format="json")

        assert response.status_code == 201
        contact = Contact.objects.get(pk=response.data["id"])
        assert contact.user == active_user
        assert contact.city == "Москва"

    def test_create_requires_city_and_phone(self, auth_client) -> None:
        response = auth_client.post(LIST_URL, {"street": "Тверская"}, format="json")

        assert response.status_code == 400
        assert "city" in response.data
        assert "phone" in response.data

    def test_list_returns_only_own_contacts(
        self, auth_client, active_user, other_user, contact_payload
    ) -> None:
        own = Contact.objects.create(user=active_user, **contact_payload)
        Contact.objects.create(user=other_user, **contact_payload)

        response = auth_client.get(LIST_URL)

        assert response.status_code == 200
        assert [item["id"] for item in response.data["results"]] == [own.pk]

    def test_foreign_contact_is_not_accessible(
        self, auth_client, other_user, contact_payload
    ) -> None:
        foreign = Contact.objects.create(user=other_user, **contact_payload)

        assert auth_client.get(detail_url(foreign)).status_code == 404
        assert auth_client.patch(
            detail_url(foreign), {"city": "Тверь"}, format="json"
        ).status_code == 404

        foreign.refresh_from_db()
        assert foreign.city == "Москва"

    def test_update_own_contact(self, auth_client, active_user, contact_payload) -> None:
        contact = Contact.objects.create(user=active_user, **contact_payload)

        response = auth_client.patch(
            detail_url(contact), {"city": "Тверь"}, format="json"
        )

        assert response.status_code == 200
        contact.refresh_from_db()
        assert contact.city == "Тверь"

    def test_delete_is_not_allowed(self, auth_client, active_user, contact_payload) -> None:
        contact = Contact.objects.create(user=active_user, **contact_payload)

        response = auth_client.delete(detail_url(contact))

        assert response.status_code == 405
        assert Contact.objects.filter(pk=contact.pk).exists()

    def test_anonymous_access_is_denied(self, api_client) -> None:
        assert api_client.get(LIST_URL).status_code == 401
