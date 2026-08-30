"""Модели приложения orders: заказ и его позиции.

Корзина не является отдельной моделью: это `Order` в состоянии
`basket`, а её позиции — обычные `OrderItem` (ADR-009). Оформление
заказа — смена состояния, а не копирование данных между таблицами.

Схема хранит только текущее состояние заказа. Допустимые переходы
между состояниями задаются кодом сервисного слоя и в базе не
выражаются (ADR-022); модели истории смен статуса нет.

Историчность обеспечивается snapshot-полями: `OrderItem` хранит
наименование, магазин и цены на момент подтверждения (ADR-003),
`Order` — получателя и адрес доставки (ADR-024, ADR-027). Поэтому ни
изменение каталога импортом, ни правка или удаление контакта не меняют
уже оформленный заказ.
"""

from __future__ import annotations

from typing import NoReturn

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.deletion import ProtectedError


class OrderState(models.TextChoices):
    """Состояние заказа (ADR-022).

    `BASKET` — единственное начальное состояние, `DELIVERED` и
    `CANCELED` — терминальные. Набор закрыт: значение вне этого списка
    отклоняется ограничением уровня базы.
    """

    BASKET = "basket", "Корзина"
    NEW = "new", "Новый"
    CONFIRMED = "confirmed", "Подтверждён"
    ASSEMBLED = "assembled", "Собран"
    SENT = "sent", "Отправлен"
    DELIVERED = "delivered", "Доставлен"
    CANCELED = "canceled", "Отменён"


class OrderQuerySet(models.QuerySet):
    """Выборки заказов, отделяющие корзины от оформленных заказов."""

    def orders(self) -> OrderQuerySet:
        """Оформленные заказы, без корзин.

        История клиента, заказы поставщика, админка и накладные обязаны
        исключать корзины (ADR-009). Условие живёт здесь, а не
        повторяется в каждом месте вызова: незакрытый фильтр означает
        попадание чужих корзин в историю заказов и в письма.
        """
        return self.exclude(state=OrderState.BASKET)

    def baskets(self) -> OrderQuerySet:
        """Корзины пользователей."""
        return self.filter(state=OrderState.BASKET)


class Order(models.Model):
    """Заказ покупателя; в состоянии `basket` — его корзина (ADR-009).

    Получатель и адрес доставки хранятся snapshot-полями `delivery_*`,
    заполняемыми один раз при переходе `basket` -> `new` (ADR-024).
    Связь с `Contact` остаётся только трассируемостью: контакт может
    быть изменён или удалён, а история заказа меняться не должна.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Покупатель",
        related_name="orders",
        on_delete=models.PROTECT,
    )
    contact = models.ForeignKey(
        "users.Contact",
        verbose_name="Контакт",
        related_name="orders",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        help_text=(
            "Только трассируемость: получатель и адрес оформленного "
            "заказа читаются из полей delivery_* (ADR-024)."
        ),
    )
    state = models.CharField(
        "Состояние",
        max_length=9,
        choices=OrderState.choices,
        default=OrderState.BASKET,
        db_index=True,
    )

    dt = models.DateTimeField("Создан", auto_now_add=True)
    confirmed_at = models.DateTimeField(
        "Оформлен",
        blank=True,
        null=True,
        help_text="Момент перехода basket -> new; у корзины не задан.",
    )

    # Snapshot получателя на момент подтверждения заказа (ADR-024,
    # ADR-027). Длины повторяют одноимённые поля users.Contact, чтобы
    # копирование не усекало значения.
    delivery_last_name = models.CharField("Фамилия получателя", max_length=150, blank=True)
    delivery_first_name = models.CharField("Имя получателя", max_length=150, blank=True)
    delivery_middle_name = models.CharField("Отчество получателя", max_length=150, blank=True)
    delivery_email = models.EmailField("Email получателя", blank=True)
    delivery_phone = models.CharField("Телефон получателя", max_length=20, blank=True)

    # Snapshot адреса доставки на момент подтверждения заказа (ADR-024).
    delivery_city = models.CharField("Город", max_length=50, blank=True)
    delivery_street = models.CharField("Улица", max_length=100, blank=True)
    delivery_house = models.CharField("Дом", max_length=15, blank=True)
    delivery_structure = models.CharField("Корпус", max_length=15, blank=True)
    delivery_building = models.CharField("Строение", max_length=15, blank=True)
    delivery_apartment = models.CharField("Квартира", max_length=15, blank=True)

    objects = OrderQuerySet.as_manager()

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ("-confirmed_at", "-id")
        constraints = [
            # Не более одной корзины на пользователя (ADR-009). Условие
            # частичное: оформленных заказов у пользователя сколько
            # угодно.
            models.UniqueConstraint(
                fields=("user",),
                condition=Q(state=OrderState.BASKET),
                name="unique_basket_per_user",
            ),
            # Набор состояний закрыт (ADR-022). `choices` проверяются
            # только формой и `full_clean()`, поэтому ограничение
            # продублировано на уровне базы: состояние заказа читают
            # выборки истории, накладные и админка.
            models.CheckConstraint(
                condition=Q(state__in=OrderState.values),
                name="order_state_is_known",
            ),
        ]

    def __str__(self) -> str:
        return f"Заказ №{self.pk} — {self.get_state_display()}"

    def delete(self, *args: object, **kwargs: object) -> NoReturn:
        """Запретить физическое удаление заказа (ADR-022).

        Заказ — историческая запись о бизнес-операции. Отмена
        выражается состоянием `canceled`, а не удалением строки.
        Правило распространяется и на корзину: она является заказом, и
        опустошение корзины — удаление её позиций, а не самой записи.

        Ограничение действует на уровне экземпляра; массовое удаление
        через queryset его не проходит и в коде проекта не
        используется.
        """
        raise ProtectedError(
            "Физическое удаление заказа запрещено (ADR-022): "
            "используйте состояние canceled.",
            {self},
        )


class OrderItem(models.Model):
    """Позиция заказа со snapshot товара на момент подтверждения.

    Пока заказ находится в состоянии `basket`, цена и наименование
    берутся из текущего `catalog.ProductInfo`; после подтверждения —
    из snapshot-полей самой позиции (ADR-003, ADR-009). Поэтому
    snapshot допускает пустое значение: до оформления он не заполнен.

    Ссылка на предложение поставщика сохраняется как переход к
    актуальной карточке товара, но не как источник расчёта: импорт
    может деактивировать предложение, а `SET_NULL` — обнулить ссылку.
    """

    order = models.ForeignKey(
        Order,
        verbose_name="Заказ",
        related_name="items",
        on_delete=models.CASCADE,
    )
    product_info = models.ForeignKey(
        "catalog.ProductInfo",
        verbose_name="Предложение поставщика",
        related_name="order_items",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    quantity = models.PositiveIntegerField("Количество")

    # Snapshot товара на момент подтверждения заказа (ADR-003). Длины
    # повторяют catalog.Product.name и suppliers.Shop.name; денежные
    # поля — DecimalField(12, 2), float не используется (ADR-015).
    product_name = models.CharField("Товар", max_length=80, blank=True)
    shop_name = models.CharField("Магазин", max_length=50, blank=True)
    price = models.DecimalField(
        "Цена",
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )
    price_rrc = models.DecimalField(
        "Рекомендуемая розничная цена",
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказа"
        ordering = ("id",)
        constraints = [
            # Одно предложение — одна позиция: повторное добавление
            # товара увеличивает количество, а не создаёт вторую
            # строку. Ограничение не действует после обнуления ссылки
            # (SET_NULL): NULL в PostgreSQL не конфликтует с NULL, и
            # это ожидаемо — позиции удалённых предложений остаются
            # историей.
            models.UniqueConstraint(
                fields=("order", "product_info"),
                name="unique_order_item_product_info",
            ),
            # Позиция с нулевым количеством не имеет смысла ни в
            # корзине, ни в накладной; PositiveIntegerField ноль
            # допускает.
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="order_item_quantity_is_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product_name or self.product_info} × {self.quantity}"

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        """Разрешить удаление позиции только в корзине (ADR-022).

        Требования прямо предусматривают удаление товара из корзины, но
        позиция оформленного заказа — историческая запись: она входит в
        сумму заказа и в накладную. Поэтому запрет привязан к состоянию
        заказа, а не к модели целиком.

        Ограничение действует на уровне экземпляра; массовое удаление
        через queryset его не проходит и в коде проекта не
        используется.
        """
        if self.order.state != OrderState.BASKET:
            raise ProtectedError(
                "Физическое удаление позиции оформленного заказа "
                "запрещено (ADR-022, ADR-003).",
                {self},
            )

        return super().delete(*args, **kwargs)
