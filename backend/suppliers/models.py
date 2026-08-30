"""Модели приложения suppliers: поставщик (магазин)."""

from __future__ import annotations

from typing import NoReturn

from django.conf import settings
from django.db import models
from django.db.models.deletion import ProtectedError


class HttpsURLField(models.URLField):
    """Ссылка, у которой схема по умолчанию — `https` (ADR-018).

    Источники прайсов допускаются только по `https`, поэтому адрес,
    введённый без схемы, дополняется именно ею: `supplier.example/p.yaml`
    становится `https://supplier.example/p.yaml`, а не `http://...`.

    Значение задаётся форме: у модельного `URLField` параметра
    `assume_scheme` нет, его принимает `forms.URLField`. Django 6.0
    сделает `https` схемой по умолчанию сам — тогда этот класс можно
    будет заменить обычным `URLField`.

    Подстановка схемы не заменяет проверку транспорта: адрес с явным
    `http://` формой не исправляется и отклоняется загрузчиком (ADR-018).
    """

    def formfield(self, **kwargs: object) -> object:
        """Построить поле формы со схемой `https` по умолчанию."""
        return super().formfield(**{"assume_scheme": "https", **kwargs})

    def deconstruct(self) -> tuple[str, str, list[object], dict[str, object]]:
        """Сериализовать поле как обычный `URLField`.

        Класс меняет только поведение формы, но не схему в базе. Без
        этого миграции фиксировали бы смену пути к классу поля, то есть
        пустую `AlterField` без единой команды SQL.
        """
        name, _, args, kwargs = super().deconstruct()
        return name, "django.db.models.URLField", args, kwargs


class Shop(models.Model):
    """Поставщик товаров.

    Магазин идентифицируется связью с пользователем-поставщиком, а не
    названием из прайса (ADR-012): при импорте название переносится в
    существующую запись и нового магазина не создаёт.
    """

    name = models.CharField("Название", max_length=50, unique=True)
    url = HttpsURLField("Ссылка", blank=True, null=True)
    state = models.BooleanField(
        "Приём заказов",
        default=True,
        help_text="Поставщик принимает заказы. Импорт прайса значение не изменяет.",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        related_name="shop",
        blank=True,
        null=True,
        on_delete=models.PROTECT,
    )

    class Meta:
        verbose_name = "Магазин"
        verbose_name_plural = "Магазины"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def delete(self, *args: object, **kwargs: object) -> NoReturn:
        """Запретить физическое удаление магазина (ADR-012).

        Прекращение работы поставщика выражается через `state=False` и
        деактивацию его предложений, а не удалением записи.

        Ограничение действует на уровне экземпляра; массовое удаление
        через queryset его не проходит и в коде проекта не используется.
        """
        raise ProtectedError(
            "Физическое удаление магазина запрещено (ADR-012): "
            "используйте state=False.",
            {self},
        )


class ImportStatus(models.TextChoices):
    """Состояние запуска импорта прайса (ADR-021)."""

    QUEUED = "queued", "В очереди"
    RUNNING = "running", "Выполняется"
    SUCCESS = "success", "Успешно"
    FAILED = "failed", "Ошибка"


class ImportErrorCode(models.TextChoices):
    """Причина отказа импорта (ADR-021).

    Словарь закрыт: код присваивается по типу исключения, поднятого
    слоем загрузки (ADR-018), разбора и валидации (ADR-017) или
    сервисным слоем. Всё, что не распознано, получает `internal_error`.

    `retries_exhausted` стоит особняком: он не соответствует типу
    исключения, а означает, что повторяемая ошибка транспорта повторялась
    до исчерпания лимита попыток задачи (ADR-018).
    """

    INSECURE_SOURCE = "insecure_source", "Недопустимый источник"
    FILE_TOO_LARGE = "file_too_large", "Файл слишком большой"
    SOURCE_UNAVAILABLE = "source_unavailable", "Источник недоступен"
    DOWNLOAD_ERROR = "download_error", "Ошибка загрузки"
    PARSE_ERROR = "parse_error", "Ошибка разбора прайса"
    INVALID_PRICE_DATA = "invalid_price_data", "Прайс не прошёл проверку"
    SHOP_NOT_FOUND = "shop_not_found", "Магазин не найден"
    SHOP_METADATA_MISMATCH = "shop_metadata_mismatch", "Прайс чужого магазина"
    RETRIES_EXHAUSTED = "retries_exhausted", "Повторы исчерпаны"
    INTERNAL_ERROR = "internal_error", "Внутренняя ошибка"


class ImportLog(models.Model):
    """Журнал запусков импорта прайса поставщика (ADR-021).

    Одна запись соответствует одному запуску импорта, а не одной попытке
    выполнения: повторы Celery при повторяемых ошибках транспорта
    (ADR-018) идут в рамках той же записи и увеличивают `attempts`, а
    `status` отражает итог запуска.

    Счётчики повторяют поля `catalog.services.ImportResult` один в один,
    чтобы результат импорта переносился в журнал без сопоставления имён.
    Поле `created` — количество созданных предложений; момент постановки
    в очередь хранится в `created_at`.
    """

    shop = models.ForeignKey(
        Shop,
        verbose_name="Магазин",
        related_name="import_logs",
        on_delete=models.PROTECT,
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Инициатор",
        related_name="import_logs",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        help_text="Пустое значение — запуск не человеком (поставщик, команда).",
    )
    source_url = HttpsURLField("Источник", max_length=500)
    task_id = models.CharField("Идентификатор задачи", max_length=64, blank=True)
    status = models.CharField(
        "Состояние",
        max_length=7,
        choices=ImportStatus.choices,
        default=ImportStatus.QUEUED,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(
        "Попыток выполнения",
        default=0,
        help_text="Число обращений воркера к задаче, включая повторы.",
    )

    created_at = models.DateTimeField("Поставлен в очередь", auto_now_add=True)
    started_at = models.DateTimeField("Начало выполнения", blank=True, null=True)
    finished_at = models.DateTimeField("Завершение", blank=True, null=True)

    offers_total = models.PositiveIntegerField("Позиций в прайсе", default=0)
    created = models.PositiveIntegerField("Создано предложений", default=0)
    updated = models.PositiveIntegerField("Обновлено предложений", default=0)
    reactivated = models.PositiveIntegerField("Реактивировано", default=0)
    deactivated = models.PositiveIntegerField("Деактивировано", default=0)
    products_created = models.PositiveIntegerField("Создано товаров", default=0)
    categories_linked = models.PositiveIntegerField("Категорий в прайсе", default=0)

    error_code = models.CharField(
        "Код ошибки",
        max_length=32,
        choices=ImportErrorCode.choices,
        blank=True,
    )
    error_message = models.TextField("Текст ошибки", blank=True)

    class Meta:
        verbose_name = "Запуск импорта"
        verbose_name_plural = "Запуски импорта"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("shop", "-created_at"),
                name="suppliers_importlog_shop_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.shop} — {self.get_status_display()}"

    def delete(self, *args: object, **kwargs: object) -> NoReturn:
        """Запретить физическое удаление записи журнала (ADR-021).

        Журнал импорта — историческая запись о бизнес-операции и хранится
        бессрочно.

        Ограничение действует на уровне экземпляра; массовое удаление
        через queryset его не проходит и в коде проекта не используется.
        """
        raise ProtectedError(
            "Физическое удаление записи журнала импорта запрещено (ADR-021).",
            {self},
        )
