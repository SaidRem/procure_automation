"""Токены подтверждения email и работа с идентификатором пользователя в ссылке.

Токен подтверждения не хранится в БД: используется stateless-генератор на
основе `PasswordResetTokenGenerator` (ADR-010). Повторное использование
исключено тем, что в хеш токена входит флаг `is_active`: после активации
пользователя ранее выданный токен перестаёт проходить проверку.
"""

from __future__ import annotations

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from users.models import User


class EmailConfirmationTokenGenerator(PasswordResetTokenGenerator):
    """Генератор одноразовых токенов подтверждения email."""

    key_salt = "users.tokens.EmailConfirmationTokenGenerator"

    def _make_hash_value(self, user: User, timestamp: int) -> str:
        """Добавить `is_active` в хеш, чтобы активация обесценивала токен."""
        return f"{super()._make_hash_value(user, timestamp)}{user.is_active}"


email_confirmation_token_generator = EmailConfirmationTokenGenerator()


def encode_uid(user: User) -> str:
    """Закодировать идентификатор пользователя для передачи в ссылке."""
    return urlsafe_base64_encode(force_bytes(user.pk))


def get_user_by_uid(uid: str) -> User | None:
    """Вернуть пользователя по закодированному идентификатору или None."""
    try:
        pk = urlsafe_base64_decode(uid).decode()
    except (TypeError, ValueError, UnicodeDecodeError):
        return None

    return User.objects.filter(pk=pk).first()
