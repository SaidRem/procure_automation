"""Админка приложения users (ADR-004, ADR-019).

Используется стандартный `django.contrib.auth.admin.UserAdmin`: он
приносит форму смены пароля, работу с группами и правами. Переопределено
только то, что необходимо, — упоминания отсутствующего поля `username`
(ADR-004) и запрет удаления (ADR-019).
"""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from users.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Пользователи сервиса.

    Удаление запрещено: пользователь участвует в истории заказов, а при
    наличии магазина его удаление и так упирается в `PROTECT` (ADR-012).
    Прекращение доступа выражается снятием `is_active`.

    Внимание: снятие `is_active` у подтверждённого пользователя снова
    делает валидным ранее выданный токен подтверждения email — известное
    ограничение ADR-011.
    """

    # Наборы полей заданы заново: значения по умолчанию ссылаются на
    # `username`, которого у модели нет (ADR-004).
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        ("Организация", {"fields": ("company", "position", "type")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "type", "password1", "password2"),
            },
        ),
    )

    list_display = ("email", "first_name", "last_name", "type", "is_active", "is_staff")
    list_filter = ("type", "is_active", "is_staff", "is_superuser", "groups")
    search_fields = ("email", "first_name", "last_name", "company")
    ordering = ("email",)

    def has_delete_permission(
        self, request: HttpRequest, obj: object | None = None
    ) -> bool:
        """Удаление запрещено всегда, включая суперпользователя."""
        return False

    def get_actions(self, request: HttpRequest) -> dict[str, object]:
        """Убрать массовое удаление из списка действий (ADR-019)."""
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions
