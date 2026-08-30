"""Модели приложения users: пользователь и контактные данные."""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from users.managers import UserManager


class UserType(models.TextChoices):
    """Тип пользователя сервиса (ADR-004)."""

    BUYER = "buyer", "Покупатель"
    SHOP = "shop", "Магазин"


class User(AbstractUser):
    """Пользователь сервиса.

    Логин выполняется по email, поле username не используется (ADR-004).
    Пользователь неактивен до подтверждения email.
    """

    username = None
    first_name = models.CharField("Имя", max_length=150, blank=True)
    last_name = models.CharField("Фамилия", max_length=150, blank=True)
    email = models.EmailField(_("email address"), unique=True)
    company = models.CharField("Компания", max_length=40, blank=True)
    position = models.CharField("Должность", max_length=40, blank=True)
    type = models.CharField(
        "Тип пользователя",
        max_length=5,
        choices=UserType.choices,
        default=UserType.BUYER,
    )
    is_active = models.BooleanField(
        _("active"),
        default=False,
        help_text="Пользователь активируется после подтверждения email.",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        ordering = ("email",)

    def __str__(self) -> str:
        return self.email


class Contact(models.Model):
    """Точка доставки пользователя: получатель и адрес (ADR-027).

    Модель описывает не только адрес, но и того, кому передаётся заказ.
    Получатель не выводится из `User`: заказ оформляет сотрудник, а
    принимает товар кладовщик или сотрудник другого магазина сети, и
    подстановка имени владельца учётной записи выдавала бы оформившего
    за принимающего.

    Поля получателя объявлены `blank=True` намеренно (ADR-027):
    существующие строки не могут задним числом обрести имя получателя, а
    миграция со значением по умолчанию вписала бы в них заглушку.
    Обязательность `last_name` и `first_name` выражена сериализатором и
    правилом перехода `basket` -> `new` (ADR-022), а не схемой.
    """

    user = models.ForeignKey(
        User,
        verbose_name="Пользователь",
        related_name="contacts",
        on_delete=models.CASCADE,
    )

    # Получатель заказа. Длина 150 совпадает с одноимёнными полями User,
    # чтобы значение, скопированное из учётной записи, не усекалось.
    last_name = models.CharField("Фамилия получателя", max_length=150, blank=True)
    first_name = models.CharField("Имя получателя", max_length=150, blank=True)
    middle_name = models.CharField("Отчество получателя", max_length=150, blank=True)
    email = models.EmailField(
        "Email получателя",
        blank=True,
        help_text=(
            "Реквизит доставки. Письма сервиса отправляются на email "
            "учётной записи и только на него (ADR-027)."
        ),
    )

    city = models.CharField("Город", max_length=50)
    street = models.CharField("Улица", max_length=100)
    house = models.CharField("Дом", max_length=15, blank=True)
    structure = models.CharField("Корпус", max_length=15, blank=True)
    building = models.CharField("Строение", max_length=15, blank=True)
    apartment = models.CharField("Квартира", max_length=15, blank=True)
    phone = models.CharField("Телефон", max_length=20)

    class Meta:
        verbose_name = "Контакт пользователя"
        verbose_name_plural = "Контакты пользователей"

    def __str__(self) -> str:
        return f"{self.city}, {self.street} {self.house}".strip()
