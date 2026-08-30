from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """Конфигурация приложения notifications."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
    verbose_name = "Уведомления"
