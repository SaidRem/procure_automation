"""Сериализаторы приложения users.

Сериализаторы отвечают только за представление и валидацию формата данных.
Бизнес-правила находятся в `users.services` (ADR-006).
"""

from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from users.models import Contact, User


class PasswordField(serializers.CharField):
    """Поле пароля с проверкой парольных политик Django."""

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("write_only", True)
        kwargs.setdefault("style", {"input_type": "password"})
        super().__init__(**kwargs)

    def run_validation(self, data: object = serializers.empty) -> str:
        value = super().run_validation(data)
        try:
            validate_password(value)
        except DjangoValidationError as error:
            raise serializers.ValidationError(list(error.messages)) from error
        return value


class RegistrationSerializer(serializers.ModelSerializer):
    """Данные регистрации нового пользователя."""

    password = PasswordField()

    class Meta:
        model = User
        fields = (
            "email",
            "password",
            "first_name",
            "last_name",
            "company",
            "position",
            "type",
        )
        extra_kwargs = {
            "email": {"required": True},
            "first_name": {"required": False},
            "last_name": {"required": False},
        }


class UserSerializer(serializers.ModelSerializer):
    """Профиль текущего пользователя.

    Email и тип пользователя доступны только для чтения: смена email
    требует повторного подтверждения адреса, смена типа — изменения
    бизнес-роли; ни то, ни другое не входит в профиль (см. docs/api.md).
    """

    class Meta:
        model = User
        fields = ("id", "email", "type", "company", "position")
        read_only_fields = ("id", "email", "type")


class EmailConfirmationSerializer(serializers.Serializer):
    """Данные подтверждения email."""

    uid = serializers.CharField()
    token = serializers.CharField()


class PasswordResetRequestSerializer(serializers.Serializer):
    """Запрос на восстановление пароля."""

    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Установка нового пароля по токену восстановления."""

    uid = serializers.CharField()
    token = serializers.CharField()
    password = PasswordField()


class ContactSerializer(serializers.ModelSerializer):
    """Точка доставки пользователя: получатель и адрес (ADR-027).

    Владелец не приходит из запроса: он подставляется из текущего
    пользователя во view.

    Обязательность полей получателя выражена здесь, а не схемой:
    `Contact.last_name` и `Contact.first_name` объявлены `blank=True`,
    чтобы миграция не вписывала заглушку в существующие строки
    (ADR-027). Поэтому `required` задаётся явно — по умолчанию
    `ModelSerializer` вывел бы из `blank=True` необязательное поле.

    `email` получателя — реквизит доставки, а не канал связи сервиса:
    письма отправляются на `User.email` и только на него (ADR-027).
    """

    # PATCH остаётся частичным: DRF не требует отсутствующие поля при
    # `partial=True`. Строгими являются создание и полная замена (PUT),
    # то есть операции, задающие контакт целиком.
    last_name = serializers.CharField(max_length=150)
    first_name = serializers.CharField(max_length=150)

    class Meta:
        model = Contact
        fields = (
            "id",
            "last_name",
            "first_name",
            "middle_name",
            "email",
            "city",
            "street",
            "house",
            "structure",
            "building",
            "apartment",
            "phone",
        )
