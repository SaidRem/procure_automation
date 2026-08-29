from django.apps import AppConfig


class SuppliersConfig(AppConfig):
    """Конфигурация приложения suppliers."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "suppliers"
    verbose_name = "Поставщики"
