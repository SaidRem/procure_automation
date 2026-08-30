"""Админка приложения suppliers (ADR-019, ADR-021).

Классы этого модуля — слой представления: они не содержат бизнес-правил
и не пишут в домен напрямую. Изменение состояния магазина выполняет
`suppliers.services` (ADR-006).

Модели `catalog` здесь не импортируются: переход к предложениям
поставщика возможен только ссылкой на changelist каталога (ADR-002,
ADR-016).
"""

from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from suppliers.models import ImportLog, Shop
from suppliers.services import set_shop_state


class NoDeleteMixin:
    """Запрет физического удаления записей (ADR-019).

    Ограничение выражено дважды намеренно: `has_delete_permission`
    убирает кнопку и закрывает страницу удаления, а изъятие
    `delete_selected` закрывает массовое удаление. Второе не следует из
    первого автоматически, а именно оно обходит защиту `delete()`
    модели, выполняя `queryset.delete()`.
    """

    def has_delete_permission(
        self, request: HttpRequest, obj: object | None = None
    ) -> bool:
        """Удаление запрещено всегда, включая суперпользователя."""
        return False

    def get_actions(self, request: HttpRequest) -> dict[str, object]:
        """Убрать массовое удаление из списка действий."""
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(Shop)
class ShopAdmin(NoDeleteMixin, admin.ModelAdmin):
    """Магазины поставщиков.

    Приём заказов переключается действиями, а не правкой поля: это
    доменная операция, и её владелец — сервисный слой (ADR-012).
    """

    list_display = ("name", "user", "state")
    list_filter = ("state",)
    search_fields = ("name", "user__email")
    list_select_related = ("user",)
    actions = ("enable_order_acceptance", "disable_order_acceptance")

    @admin.action(description="Включить приём заказов")
    def enable_order_acceptance(
        self, request: HttpRequest, queryset: QuerySet[Shop]
    ) -> None:
        """Включить приём заказов у выбранных магазинов."""
        self._apply_state(request, queryset, state=True)

    @admin.action(description="Отключить приём заказов")
    def disable_order_acceptance(
        self, request: HttpRequest, queryset: QuerySet[Shop]
    ) -> None:
        """Отключить приём заказов у выбранных магазинов."""
        self._apply_state(request, queryset, state=False)

    def _apply_state(
        self, request: HttpRequest, queryset: QuerySet[Shop], *, state: bool
    ) -> None:
        """Передать переключение сервисному слою для каждого магазина.

        Массовое `queryset.update()` здесь недопустимо: оно обошло бы
        сервис, а вместе с ним журналирование и правила ADR-012.
        """
        shop_ids = list(queryset.values_list("pk", flat=True))

        for shop_id in shop_ids:
            set_shop_state(shop_id, state=state)

        self.message_user(request, f"Магазинов изменено: {len(shop_ids)}.")


@admin.register(ImportLog)
class ImportLogAdmin(NoDeleteMixin, admin.ModelAdmin):
    """Журнал запусков импорта — только просмотр (ADR-021).

    Записи создаёт и обновляет сервисный слой; ручное редактирование
    исказило бы историю выполнения, а удаление запрещено правилом о
    сохранности исторических данных.
    """

    list_display = ("shop", "status", "attempts", "created_at", "finished_at")
    list_filter = ("status", "error_code", "shop", "created_at")
    search_fields = ("task_id", "shop__name")
    list_select_related = ("shop", "initiated_by")
    ordering = ("-created_at",)

    readonly_fields = (
        "shop",
        "initiated_by",
        "source_url",
        "task_id",
        "status",
        "attempts",
        "created_at",
        "started_at",
        "finished_at",
        "offers_total",
        "created",
        "updated",
        "reactivated",
        "deactivated",
        "products_created",
        "categories_linked",
        "error_code",
        "error_message",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Запуск регистрируется сервисом, а не создаётся вручную."""
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: object | None = None
    ) -> bool:
        """Запись отражает ход выполнения и вручную не правится."""
        return False
