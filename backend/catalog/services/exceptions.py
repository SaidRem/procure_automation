"""Исключения сервисного слоя приложения catalog."""


class CatalogServiceError(Exception):
    """Базовая ошибка сервисов каталога."""


class UnknownShop(CatalogServiceError):
    """Магазин с указанным идентификатором не существует."""


class InvalidPriceData(CatalogServiceError):
    """Данные прайса не прошли проверку и в каталог не записаны."""
