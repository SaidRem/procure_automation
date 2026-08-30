"""API приложения suppliers (ADR-026).

Views остаются тонкими: разбор запроса, вызов сервисного слоя и
формирование ответа. Ни очерёдность запусков, ни источник прайса, ни
проверки транспорта здесь не решаются — импорт целиком принадлежит
`suppliers.services` (ADR-006, ADR-018).

Раздел доступен только пользователям типа `shop`: поставщик работает
через API и доступа в админку не получает (ADR-023).
"""

from __future__ import annotations

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from orders import services as order_services
from suppliers import services
from suppliers.models import ImportLog, Shop
from suppliers.serializers import (
    ImportLogSerializer,
    ImportRunSerializer,
    ShopSerializer,
    ShopStateSerializer,
    SupplierOrderSerializer,
)
from users.models import UserType


class IsSupplier(permissions.IsAuthenticated):
    """Доступ только пользователям типа `shop` (ADR-023, ADR-004)."""

    message = "Раздел доступен только поставщикам."

    def has_permission(self, request: Request, view: object) -> bool:
        return super().has_permission(request, view) and (
            request.user.type == UserType.SHOP
        )


@extend_schema(tags=["suppliers"])
@extend_schema_view(
    create=extend_schema(
        summary="Создание магазина",
        description=(
            "Заводит магазин текущего поставщика. Магазин не создаётся "
            "как побочный эффект импорта (ADR-012); импорт запускается "
            "отдельным запросом."
        ),
    ),
    retrieve=extend_schema(summary="Свой магазин"),
)
class ShopViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Магазин поставщика, запуск импорта и журнал запусков."""

    serializer_class = ShopSerializer
    permission_classes = (IsSupplier,)

    def get_queryset(self) -> QuerySet[Shop]:
        """Ограничить выборку магазином текущего пользователя.

        Чужой магазин неотличим от несуществующего: обращение к нему
        возвращает `404`, а не `403`.
        """
        if getattr(self, "swagger_fake_view", False):
            # Генерация OpenAPI-схемы выполняется без пользователя.
            return Shop.objects.none()

        return Shop.objects.filter(user=self.request.user)

    def perform_create(self, serializer: ShopSerializer) -> None:
        """Владелец магазина берётся из токена (ADR-012)."""
        serializer.save(user=self.request.user)

    @extend_schema(
        summary="Запуск импорта прайса",
        description=(
            "Ставит импорт в очередь и возвращает идентификатор записи "
            "журнала. Ответ не означает успешного импорта: результат "
            "читается из журнала запусков (ADR-021). Источник — ссылка "
            "магазина."
        ),
        request=None,
        responses={
            202: ImportRunSerializer,
            400: OpenApiResponse(description="У магазина не указана ссылка на прайс"),
            409: OpenApiResponse(description="Импорт этого магазина уже выполняется"),
        },
    )
    @action(detail=True, methods=("post",), url_path="import", url_name="import")
    def import_(self, request: Request, pk: int) -> Response:
        """Запустить импорт прайса своего магазина."""
        shop = self.get_object()

        try:
            run = services.request_price_import(
                shop_id=shop.pk, initiated_by=request.user
            )
        except services.PriceSourceNotConfigured as error:
            raise ValidationError({"url": [str(error)]}) from error
        except services.ImportAlreadyRunning as error:
            return Response(
                {"detail": str(error), "code": "import_already_running"},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {"import_id": run.pk, "status": run.status},
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        summary="Журнал запусков импорта",
        responses={200: ImportLogSerializer(many=True)},
    )
    @action(detail=True, methods=("get",))
    def imports(self, request: Request, pk: int) -> Response:
        """Вернуть историю запусков импорта своего магазина."""
        shop = self.get_object()
        runs = ImportLog.objects.filter(shop=shop)

        page = self.paginate_queryset(runs)
        serializer = ImportLogSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        summary="Переключение приёма заказов",
        description=(
            "Включает и отключает приём заказов магазином. На видимость "
            "товаров в каталоге не влияет: отключённый приём заказов — "
            "временное состояние поставщика, а не снятие товаров с "
            "продажи (ADR-025)."
        ),
        request=ShopStateSerializer,
        responses={200: ShopSerializer},
    )
    @action(detail=True, methods=("patch",), url_path="state", url_name="state")
    def state(self, request: Request, pk: int) -> Response:
        """Переключить приём заказов своего магазина."""
        shop = self.get_object()
        serializer = ShopStateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = services.set_shop_state(
            shop.pk, state=serializer.validated_data["state"]
        )

        return Response(ShopSerializer(updated).data)

    @extend_schema(
        summary="Заказы с товарами поставщика",
        description=(
            "Оформленные заказы, содержащие позиции из прайса этого "
            "магазина. Заказ показан только своими позициями: товары "
            "других поставщиков в одном заказе поставщику не видны. "
            "Корзины в выдачу не попадают."
        ),
        responses={200: SupplierOrderSerializer(many=True)},
    )
    @action(detail=True, methods=("get",))
    def orders(self, request: Request, pk: int) -> Response:
        """Вернуть заказы с товарами своего магазина."""
        shop = self.get_object()
        found = order_services.supplier_orders(shop_id=shop.pk)

        page = self.paginate_queryset(found)
        serializer = SupplierOrderSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)
