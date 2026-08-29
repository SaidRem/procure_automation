"""Модели приложения suppliers: поставщик (магазин)."""

from __future__ import annotations

from typing import NoReturn

from django.conf import settings
from django.db import models
from django.db.models.deletion import ProtectedError


class Shop(models.Model):
    """Поставщик товаров.

    Магазин идентифицируется связью с пользователем-поставщиком, а не
    названием из прайса (ADR-012): при импорте название переносится в
    существующую запись и нового магазина не создаёт.
    """

    name = models.CharField("Название", max_length=50, unique=True)
    url = models.URLField("Ссылка", blank=True, null=True)
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
