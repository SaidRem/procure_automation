"""Сериализаторы приложения suppliers.

Сериализаторы отвечают за формат данных. Правила домена — идентификация
магазина пользователем (ADR-012), очерёдность запусков и источник прайса
(ADR-026) — живут в `suppliers.services` (ADR-006).
"""

from __future__ import annotations

from rest_framework import serializers

from suppliers.models import ImportLog, Shop


class ShopSerializer(serializers.ModelSerializer):
    """Магазин поставщика.

    Владелец не приходит из запроса: он берётся из токена. Приём заказов
    только читается — это отдельное действие поставщика, а не поле формы
    (ADR-012).
    """

    class Meta:
        model = Shop
        fields = ("id", "name", "url", "state")
        read_only_fields = ("id", "state")

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Отклонить второй магазин у того же пользователя (ADR-012).

        Ограничение выражено `OneToOneField`, но без этой проверки оно
        доходило бы до базы и возвращало `500` вместо внятного отказа:
        владелец в запросе не передаётся, и валидатор уникальности
        построить его сам не может.
        """
        user = self.context["request"].user

        if self.instance is None and Shop.objects.filter(user=user).exists():
            raise serializers.ValidationError(
                "У пользователя уже есть магазин: на одного поставщика "
                "приходится один магазин."
            )

        return attrs


class ImportLogSerializer(serializers.ModelSerializer):
    """Запись журнала импорта — только для чтения (ADR-021).

    Журнал ведёт сервисный слой; для поставщика это единственный канал
    обратной связи по асинхронной операции.
    """

    class Meta:
        model = ImportLog
        fields = (
            "id",
            "status",
            "attempts",
            "source_url",
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
        read_only_fields = fields


class ImportRunSerializer(serializers.Serializer):
    """Ответ на запуск импорта: идентификатор запуска и его состояние."""

    import_id = serializers.IntegerField()
    status = serializers.CharField()
