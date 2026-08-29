"""Исключения сервисного слоя приложения users."""


class UsersServiceError(Exception):
    """Базовая ошибка сервисов приложения users."""


class InvalidConfirmationToken(UsersServiceError):
    """Токен подтверждения email отсутствует, истёк или уже использован."""


class InvalidPasswordResetToken(UsersServiceError):
    """Токен сброса пароля отсутствует, истёк или уже использован."""
