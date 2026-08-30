"""Тесты моделей приложения users."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from users.models import Contact, UserType

User = get_user_model()


@pytest.mark.django_db
class TestUserModel:
    """Проверки кастомной модели пользователя (ADR-004)."""

    def test_username_field_is_email(self) -> None:
        assert User.USERNAME_FIELD == "email"
        assert User.REQUIRED_FIELDS == []

    def test_username_attribute_removed(self) -> None:
        field_names = {field.name for field in User._meta.get_fields()}
        assert "username" not in field_names

    def test_create_user_defaults(self) -> None:
        user = User.objects.create_user(email="buyer@example.com", password="pass12345")

        assert user.email == "buyer@example.com"
        assert user.check_password("pass12345")
        assert user.type == UserType.BUYER
        assert user.is_active is False
        assert user.is_staff is False

    def test_create_user_requires_email(self) -> None:
        with pytest.raises(ValueError):
            User.objects.create_user(email="", password="pass12345")

    def test_email_is_unique(self) -> None:
        User.objects.create_user(email="shop@example.com", password="pass12345")

        with pytest.raises(IntegrityError):
            User.objects.create_user(email="shop@example.com", password="pass12345")

    def test_create_superuser_is_active(self) -> None:
        admin = User.objects.create_superuser(email="admin@example.com", password="pass12345")

        assert admin.is_staff is True
        assert admin.is_superuser is True
        assert admin.is_active is True

    def test_shop_user_type(self) -> None:
        user = User.objects.create_user(
            email="supplier@example.com",
            password="pass12345",
            type=UserType.SHOP,
        )

        assert user.type == UserType.SHOP


@pytest.mark.django_db
class TestContactModel:
    """Проверки модели контактных данных."""

    def test_contact_belongs_to_user(self) -> None:
        user = User.objects.create_user(email="buyer@example.com", password="pass12345")
        contact = Contact.objects.create(
            user=user,
            city="Москва",
            street="Тверская",
            house="1",
            phone="+70000000000",
        )

        assert contact in user.contacts.all()
        assert str(contact) == "Москва, Тверская 1"

    def test_recipient_fields_are_optional_at_schema_level(self) -> None:
        """Схема допускает контакт без получателя (ADR-027).

        Обязательность выражена сериализатором и правилом оформления
        заказа: строки, созданные до миграции, не могут задним числом
        обрести имя получателя, а значение по умолчанию было бы
        заглушкой в накладной.
        """
        user = User.objects.create_user(email="buyer@example.com", password="pass12345")

        contact = Contact.objects.create(
            user=user,
            city="Москва",
            street="Тверская",
            phone="+70000000000",
        )
        contact.full_clean()

        assert contact.last_name == ""
        assert contact.first_name == ""
        assert contact.middle_name == ""
        assert contact.email == ""

    def test_contact_stores_recipient(self) -> None:
        user = User.objects.create_user(email="buyer@example.com", password="pass12345")

        contact = Contact.objects.create(
            user=user,
            last_name="Петров",
            first_name="Пётр",
            middle_name="Петрович",
            email="recipient@example.com",
            city="Москва",
            street="Тверская",
            phone="+70000000000",
        )
        contact.full_clean()

        assert contact.email != user.email
