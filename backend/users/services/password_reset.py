"""Восстановление пароля пользователя.

Используется стандартный Django-механизм (`default_token_generator`) без
дополнительных моделей и без сторонних библиотек. Токен одноразовый: его
хеш включает текущий пароль, поэтому после смены пароля он невалиден.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator

from users.models import User
from users.services.exceptions import InvalidPasswordResetToken
from users.services.notifications import send_email_async
from users.tokens import encode_uid, get_user_by_uid

logger = logging.getLogger(__name__)

RESET_SUBJECT = "Восстановление пароля"


def request_password_reset(*, email: str) -> None:
    """Отправить письмо со ссылкой сброса пароля, если пользователь существует.

    Функция всегда завершается успешно: наличие адреса в системе не
    раскрывается вызывающей стороне.
    """
    user = User.objects.filter(email__iexact=email, is_active=True).first()

    if user is None:
        logger.info("Password reset requested for unknown or inactive email")
        return

    uid = encode_uid(user)
    token = default_token_generator.make_token(user)
    link = f"{settings.FRONTEND_URL}/auth/password-reset?uid={uid}&token={token}"

    send_email_async(
        subject=RESET_SUBJECT,
        message=(
            "Для установки нового пароля перейдите по ссылке.\n\n"
            f"Ссылка: {link}\n\n"
            f"uid: {uid}\ntoken: {token}"
        ),
        recipient=user.email,
    )


def set_new_password(*, uid: str, token: str, password: str) -> User:
    """Установить новый пароль пользователя по токену сброса."""
    user = get_user_by_uid(uid)

    if user is None or not user.is_active or not default_token_generator.check_token(user, token):
        logger.warning("Password reset failed: uid=%s", uid)
        raise InvalidPasswordResetToken

    user.set_password(password)
    user.save(update_fields=["password"])
    logger.info("Password changed: user_id=%s", user.pk)
    return user
