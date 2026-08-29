"""Публичный сервисный слой приложения users.

Другие домены и слой представления обращаются к бизнес-операциям только
через этот пакет (ADR-006).
"""

from users.services.exceptions import (
    InvalidConfirmationToken,
    InvalidPasswordResetToken,
    UsersServiceError,
)
from users.services.password_reset import request_password_reset, set_new_password
from users.services.registration import confirm_email, register_user, send_confirmation_email

__all__ = (
    "InvalidConfirmationToken",
    "InvalidPasswordResetToken",
    "UsersServiceError",
    "confirm_email",
    "register_user",
    "request_password_reset",
    "send_confirmation_email",
    "set_new_password",
)
