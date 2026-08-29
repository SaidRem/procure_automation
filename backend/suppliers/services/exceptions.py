"""Исключения сервисного слоя приложения suppliers."""


class SupplierServiceError(Exception):
    """Базовая ошибка сервисов приложения suppliers."""


class ShopNotFound(SupplierServiceError):
    """Магазин с указанным идентификатором не существует."""


class ShopMetadataMismatch(SupplierServiceError):
    """Метаданные прайса не совпадают с данными магазина в сервисе."""
