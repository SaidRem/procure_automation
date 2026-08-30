"""Регистрация пользователя и подтверждение email."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import transaction

from notifications.services import send_email_async
from users.models import User
from users.services.exceptions import InvalidConfirmationToken
from users.tokens import email_confirmation_token_generator, encode_uid, get_user_by_uid

logger = logging.getLogger(__name__)

CONFIRMATION_SUBJECT = "Подтверждение регистрации"


@transaction.atomic
def register_user(*, email: str, password: str, **extra_fields: Any) -> User:
    """Создать неактивного пользователя и отправить письмо с подтверждением.

    Пользователь создаётся с `is_active=False` (ADR-004) и активируется
    только через `confirm_email`.
    """
    user = User.objects.create_user(email=email, password=password, **extra_fields)
    logger.info("User registered: id=%s email=%s type=%s", user.pk, user.email, user.type)

    send_confirmation_email(user=user)
    return user


def send_confirmation_email(*, user: User) -> None:
    """Отправить пользователю письмо со ссылкой подтверждения email."""
    uid = encode_uid(user)
    token = email_confirmation_token_generator.make_token(user)
    link = f"{settings.FRONTEND_URL}/auth/confirm-email?uid={uid}&token={token}"

    send_email_async(
        subject=CONFIRMATION_SUBJECT,
        body=(
            "Для завершения регистрации подтвердите email.\n\n"
            f"Ссылка: {link}\n\n"
            f"uid: {uid}\ntoken: {token}"
        ),
        recipient=user.email,
    )


def confirm_email(*, uid: str, token: str) -> User:
    """Активировать пользователя по токену подтверждения.

    Повторное использование токена невозможно: после активации значение
    `is_active` входит в хеш токена и проверка перестаёт проходить.
    """
    user = get_user_by_uid(uid)

    if user is None or not email_confirmation_token_generator.check_token(user, token):
        logger.warning("Email confirmation failed: uid=%s", uid)
        raise InvalidConfirmationToken

    user.is_active = True
    user.save(update_fields=["is_active"])
    logger.info("Email confirmed: user_id=%s", user.pk)
    return user
