"""Модели приложения catalog: категории, товары, предложения поставщиков.

Логический товар (`Product`) и предложение конкретного поставщика
(`ProductInfo`) — разные сущности (ADR-001). Зависимость на уровне ORM
однонаправленная: catalog ссылается на suppliers, обратный импорт
моделей не допускается (ADR-002).
"""

from __future__ import annotations

from django.db import models


class Category(models.Model):
    """Категория каталога, общая для всех поставщиков.

    Идентифицируется собственным первичным ключом и названием;
    идентификатор категории из прайса поставщика не хранится (ADR-013).
    """

    name = models.CharField("Название", max_length=40, unique=True)
    shops = models.ManyToManyField(
        "suppliers.Shop",
        verbose_name="Магазины",
        related_name="categories",
        blank=True,
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    """Логический товар, независимый от поставщика (ADR-001).

    Идентифицируется парой «название + категория» (ADR-014).
    """

    name = models.CharField("Название", max_length=80)
    category = models.ForeignKey(
        Category,
        verbose_name="Категория",
        related_name="products",
        on_delete=models.PROTECT,
    )

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("name", "category"),
                name="unique_product_name_category",
            ),
        ]
        indexes = [
            models.Index(fields=("name",), name="catalog_product_name_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class ProductInfo(models.Model):
    """Предложение товара конкретным поставщиком (ADR-001).

    Ключ предложения — пара `(shop, external_id)`: по ней выполняется
    upsert при импорте прайса, а отсутствующие в новом прайсе записи
    помечаются `is_active=False` вместо удаления (ADR-008).
    """

    product = models.ForeignKey(
        Product,
        verbose_name="Товар",
        related_name="product_infos",
        on_delete=models.CASCADE,
    )
    shop = models.ForeignKey(
        "suppliers.Shop",
        verbose_name="Магазин",
        related_name="product_infos",
        on_delete=models.CASCADE,
    )
    external_id = models.PositiveIntegerField("Внешний ИД")
    model = models.CharField("Модель", max_length=80, blank=True)
    quantity = models.PositiveIntegerField("Количество")
    price = models.DecimalField("Цена", max_digits=12, decimal_places=2)
    price_rrc = models.DecimalField(
        "Рекомендуемая розничная цена",
        max_digits=12,
        decimal_places=2,
    )
    is_active = models.BooleanField(
        "Активно",
        default=True,
        db_index=True,
        help_text="Снимается при импорте, если предложение исчезло из прайса.",
    )

    class Meta:
        verbose_name = "Предложение поставщика"
        verbose_name_plural = "Предложения поставщиков"
        ordering = ("shop", "external_id")
        constraints = [
            models.UniqueConstraint(
                fields=("shop", "external_id"),
                name="unique_product_info_shop_external_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=("shop", "is_active"),
                name="catalog_pinfo_shop_active_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product} — {self.shop}"


class Parameter(models.Model):
    """Название характеристики товара."""

    name = models.CharField("Название", max_length=40, unique=True)

    class Meta:
        verbose_name = "Характеристика"
        verbose_name_plural = "Характеристики"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class ProductParameter(models.Model):
    """Значение характеристики для предложения поставщика.

    Значения в прайсе могут быть числами; приведение к строке выполняется
    при импорте, а не моделью (ADR-016).
    """

    product_info = models.ForeignKey(
        ProductInfo,
        verbose_name="Предложение поставщика",
        related_name="product_parameters",
        on_delete=models.CASCADE,
    )
    parameter = models.ForeignKey(
        Parameter,
        verbose_name="Характеристика",
        related_name="product_parameters",
        on_delete=models.PROTECT,
    )
    value = models.CharField("Значение", max_length=100)

    class Meta:
        verbose_name = "Значение характеристики"
        verbose_name_plural = "Значения характеристик"
        constraints = [
            models.UniqueConstraint(
                fields=("product_info", "parameter"),
                name="unique_product_parameter",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parameter}: {self.value}"
