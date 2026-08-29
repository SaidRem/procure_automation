"""Исключения слоя импорта прайса поставщика."""


class PriceParseError(Exception):
    """Прайс не удалось разобрать или он не прошёл проверку.

    Единый тип отказа для вызывающей стороны: и ошибки формата файла, и
    нарушения правил прайса (ADR-017) приводят к этому исключению.
    """


class PriceDownloadError(Exception):
    """Прайс не удалось загрузить по ссылке (ADR-018).

    Атрибут `retryable` показывает, имеет ли смысл повторить загрузку:
    по нему настраивается поведение будущей Celery-задачи (ADR-005).
    """

    retryable = False


class InsecurePriceSource(PriceDownloadError):
    """Ссылка нарушает правила транспорта: схема или адрес назначения."""


class PriceFileTooLarge(PriceDownloadError):
    """Размер файла прайса превышает допустимый."""


class PriceSourceUnavailable(PriceDownloadError):
    """Источник временно недоступен: таймаут, обрыв связи, 5xx, 429."""

    retryable = True
