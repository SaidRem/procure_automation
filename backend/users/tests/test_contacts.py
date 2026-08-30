"""Тесты точек доставки пользователя: получатель и адрес (ADR-027)."""

from __future__ import annotations

import pytest
from django.urls import reverse

from users.models import Contact

LIST_URL = reverse("users:contact-list")

# Поля получателя, обязательные при создании и полной замене контакта.
REQUIRED_RECIPIENT_FIELDS = ("last_name", "first_name")


def detail_url(contact: Contact) -> str:
    return reverse("users:contact-detail", args=[contact.pk])


@pytest.fixture
def contact_payload() -> dict[str, str]:
    """Полный контакт: получатель и адрес."""
    return {
        "last_name": "Петров",
        "first_name": "Пётр",
        "middle_name": "Петрович",
        "email": "recipient@example.com",
        "city": "Москва",
        "street": "Тверская",
        "house": "1",
        "phone": "+70000000000",
    }


@pytest.fixture
def legacy_contact(active_user) -> Contact:
    """Контакт без данных получателя.

    Воспроизводит строку, созданную до миграции `0002_contact_recipient`:
    поля получателя пустые, потому что backfill намеренно не выполнялся
    (ADR-027).
    """
    return Contact.objects.create(
        user=active_user,
        city="Москва",
        street="Тверская",
        house="1",
        phone="+70000000000",
    )


@pytest.mark.django_db
class TestContacts:
    """/api/users/contacts/."""

    def test_create_contact(self, auth_client, active_user, contact_payload) -> None:
        response = auth_client.post(LIST_URL, contact_payload, format="json")

        assert response.status_code == 201
        contact = Contact.objects.get(pk=response.data["id"])
        assert contact.user == active_user
        assert contact.city == "Москва"
        assert contact.last_name == "Петров"
        assert contact.first_name == "Пётр"
        assert contact.middle_name == "Петрович"
        assert contact.email == "recipient@example.com"

    def test_response_exposes_recipient_fields(self, auth_client, contact_payload) -> None:
        response = auth_client.post(LIST_URL, contact_payload, format="json")

        assert response.status_code == 201
        for field, expected in contact_payload.items():
            assert response.data[field] == expected

    def test_create_requires_city_and_phone(self, auth_client) -> None:
        response = auth_client.post(LIST_URL, {"street": "Тверская"}, format="json")

        assert response.status_code == 400
        assert "city" in response.data
        assert "phone" in response.data

    @pytest.mark.parametrize("missing", REQUIRED_RECIPIENT_FIELDS)
    def test_create_requires_recipient_name(
        self, auth_client, contact_payload, missing
    ) -> None:
        """Заказ не должен уходить в накладную без имени получателя (ADR-027)."""
        contact_payload.pop(missing)

        response = auth_client.post(LIST_URL, contact_payload, format="json")

        assert response.status_code == 400
        assert missing in response.data

    @pytest.mark.parametrize("blank", REQUIRED_RECIPIENT_FIELDS)
    def test_create_rejects_blank_recipient_name(
        self, auth_client, contact_payload, blank
    ) -> None:
        """Пустая строка не заменяет имя получателя."""
        contact_payload[blank] = ""

        response = auth_client.post(LIST_URL, contact_payload, format="json")

        assert response.status_code == 400
        assert blank in response.data

    @pytest.mark.parametrize("optional", ("middle_name", "email"))
    def test_middle_name_and_email_are_optional(
        self, auth_client, contact_payload, optional
    ) -> None:
        """Отчество есть не у всех, email получателя не обязателен (ADR-027)."""
        contact_payload.pop(optional)

        response = auth_client.post(LIST_URL, contact_payload, format="json")

        assert response.status_code == 201
        assert response.data[optional] == ""

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

    def test_update_keeps_recipient_untouched(
        self, auth_client, active_user, contact_payload
    ) -> None:
        """PATCH адреса не затрагивает получателя."""
        contact = Contact.objects.create(user=active_user, **contact_payload)

        response = auth_client.patch(
            detail_url(contact), {"city": "Тверь"}, format="json"
        )

        assert response.status_code == 200
        contact.refresh_from_db()
        assert contact.city == "Тверь"
        assert contact.last_name == "Петров"
        assert contact.first_name == "Пётр"

    def test_full_replace_requires_recipient_name(
        self, auth_client, active_user, contact_payload
    ) -> None:
        """PUT задаёт контакт целиком, поэтому получатель обязателен."""
        contact = Contact.objects.create(user=active_user, **contact_payload)
        del contact_payload["last_name"]

        response = auth_client.put(
            detail_url(contact), contact_payload, format="json"
        )

        assert response.status_code == 400
        assert "last_name" in response.data

    def test_delete_own_contact(self, auth_client, active_user, contact_payload) -> None:
        """Контакт — запись адресной книги и удаляется (ADR-024)."""
        contact = Contact.objects.create(user=active_user, **contact_payload)

        response = auth_client.delete(detail_url(contact))

        assert response.status_code == 204
        assert not Contact.objects.filter(pk=contact.pk).exists()

    def test_delete_foreign_contact_is_not_found(
        self, auth_client, other_user, contact_payload
    ) -> None:
        """Чужой контакт неотличим от несуществующего."""
        foreign = Contact.objects.create(user=other_user, **contact_payload)

        assert auth_client.delete(detail_url(foreign)).status_code == 404
        assert Contact.objects.filter(pk=foreign.pk).exists()

    def test_anonymous_access_is_denied(self, api_client) -> None:
        assert api_client.get(LIST_URL).status_code == 401


@pytest.mark.django_db
class TestLegacyContacts:
    """Контакты, созданные до появления полей получателя (ADR-027).

    Backfill намеренно не выполнялся, поэтому такие строки существуют с
    пустым получателем. Они не должны ломать чтение и изменение: неполнота
    обнаруживается при оформлении заказа, а не при работе с адресной
    книгой.
    """

    def test_legacy_contact_is_readable(self, auth_client, legacy_contact) -> None:
        response = auth_client.get(detail_url(legacy_contact))

        assert response.status_code == 200
        assert response.data["city"] == "Москва"
        assert response.data["last_name"] == ""
        assert response.data["first_name"] == ""
        assert response.data["middle_name"] == ""
        assert response.data["email"] == ""

    def test_legacy_contact_is_listed(self, auth_client, legacy_contact) -> None:
        response = auth_client.get(LIST_URL)

        assert response.status_code == 200
        assert [item["id"] for item in response.data["results"]] == [legacy_contact.pk]

    def test_legacy_contact_address_is_patchable(
        self, auth_client, legacy_contact
    ) -> None:
        """Частичное изменение адреса не требует данных получателя."""
        response = auth_client.patch(
            detail_url(legacy_contact), {"city": "Тверь"}, format="json"
        )

        assert response.status_code == 200
        legacy_contact.refresh_from_db()
        assert legacy_contact.city == "Тверь"
        assert legacy_contact.last_name == ""

    def test_legacy_contact_can_be_completed(
        self, auth_client, legacy_contact
    ) -> None:
        """Недостающего получателя пользователь дописывает через PATCH."""
        response = auth_client.patch(
            detail_url(legacy_contact),
            {"last_name": "Петров", "first_name": "Пётр"},
            format="json",
        )

        assert response.status_code == 200
        legacy_contact.refresh_from_db()
        assert legacy_contact.last_name == "Петров"
        assert legacy_contact.first_name == "Пётр"
