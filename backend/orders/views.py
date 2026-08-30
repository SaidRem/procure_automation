"""API приложения orders.

Views остаются тонкими: разбор запроса, вызов сервисного слоя и
формирование ответа. Ни одно правило корзины или оформления заказа
здесь не проверяется — всё живёт в `orders.services` (ADR-006).

Отказы сервиса переводятся в HTTP одной таблицей соответствия: причина
отказа сохраняется машиночитаемым кодом, потому что причины
недоступности различимы по смыслу и требуют разных действий покупателя
(ADR-025).
"""

from __future__ import annotations

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from orders import services
from orders.models import Order
from orders.serializers import (
    CartItemCreateSerializer,
    CartItemSerializer,
    CartItemUpdateSerializer,
    CartSerializer,
    CheckoutSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
)


# Причина отказа -> машиночитаемый код в ответе. Причины различимы
# намеренно: снятие с продажи окончательно, а отключённый приём заказов
# и нехватка остатка временны, и покупателю это меняет дальнейшие
# действия (ADR-025).
_OFFER_ERROR_CODES = {
    services.OfferInactive: "offer_inactive",
    services.ShopNotAcceptingOrders: "shop_not_accepting_orders",
    services.InsufficientStock: "insufficient_stock",
    services.OfferGone: "offer_gone",
}


def _offer_conflict(error: services.OfferUnavailable) -> Response:
    """Построить ответ 409 с кодом причины отказа.

    409, а не 400: запрос корректен, но конфликтует с состоянием
    системы — предложение снято с продажи, поставщик не принимает
    заказы или остатка не хватает. Тот же код использует отклонение
    параллельного импорта (ADR-026).

    Ответ формируется явно, а не через `APIException`: тот приводит
    значения detail к строкам, и идентификатор предложения уходил бы
    клиенту строкой вместо числа.
    """
    return Response(
        {
            "detail": str(error),
            "code": _OFFER_ERROR_CODES.get(type(error), "offer_unavailable"),
            "product_info": error.product_info_id,
        },
        status=status.HTTP_409_CONFLICT,
    )


@extend_schema(tags=["orders"])
class CartView(APIView):
    """Корзина текущего пользователя."""

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        summary="Корзина текущего пользователя",
        description=(
            "Возвращает корзину, создавая её при первом обращении. "
            "Цены и наименования берутся из текущего каталога."
        ),
        responses={200: CartSerializer},
    )
    def get(self, request: Request) -> Response:
        basket = services.get_or_create_basket(request.user)
        return Response(CartSerializer(_with_items(basket)).data)


@extend_schema(tags=["orders"])
class CartItemsView(GenericAPIView):
    """Добавление позиции в корзину."""

    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = CartItemCreateSerializer

    @extend_schema(
        summary="Добавление товара в корзину",
        description=(
            "Повторное добавление того же предложения увеличивает "
            "количество существующей позиции."
        ),
        responses={
            201: CartItemSerializer,
            409: OpenApiResponse(
                description=(
                    "Товар недоступен: снят с продажи, поставщик не "
                    "принимает заказы или не хватает остатка"
                )
            ),
        },
    )
    def post(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            item = services.add_item(request.user, **serializer.validated_data)
        except services.InvalidQuantity as error:
            raise ValidationError({"quantity": [str(error)]}) from error
        except services.OfferUnavailable as error:
            return _offer_conflict(error)

        return Response(
            CartItemSerializer(item).data, status=status.HTTP_201_CREATED
        )


@extend_schema(tags=["orders"])
class CartItemDetailView(GenericAPIView):
    """Изменение количества и удаление позиции корзины."""

    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = CartItemUpdateSerializer

    @extend_schema(
        summary="Изменение количества позиции",
        responses={200: CartItemSerializer, 404: OpenApiResponse(description="Позиция не найдена")},
    )
    def patch(self, request: Request, pk: int) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            item = services.update_item_quantity(
                request.user, pk, serializer.validated_data["quantity"]
            )
        except services.BasketItemNotFound as error:
            raise NotFound(str(error)) from error
        except services.InvalidQuantity as error:
            raise ValidationError({"quantity": [str(error)]}) from error
        except services.OfferUnavailable as error:
            return _offer_conflict(error)

        return Response(CartItemSerializer(item).data)

    @extend_schema(
        summary="Удаление позиции из корзины",
        description=(
            "Единственный метод удаления в API заказов: позиция корзины "
            "выражает текущее намерение покупателя, а не историю "
            "заказа (ADR-022)."
        ),
        responses={204: OpenApiResponse(description="Позиция удалена")},
    )
    def delete(self, request: Request, pk: int) -> Response:
        try:
            services.remove_item(request.user, pk)
        except services.BasketItemNotFound as error:
            raise NotFound(str(error)) from error

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["orders"])
class CheckoutView(GenericAPIView):
    """Оформление заказа: переход basket -> new (ADR-022)."""

    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = CheckoutSerializer

    @extend_schema(
        summary="Подтверждение заказа",
        description=(
            "Оформляет корзину как заказ: фиксирует получателя, адрес и "
            "цены на момент подтверждения. Остатки не списываются."
        ),
        responses={
            201: OrderDetailSerializer,
            400: OpenApiResponse(description="Пустая корзина, чужой контакт или неполные данные получателя"),
            409: OpenApiResponse(description="Позиция заказа стала недоступна"),
        },
    )
    def post(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = services.checkout_order(
                request.user, serializer.validated_data["contact"].pk
            )
        except services.EmptyBasket as error:
            raise ValidationError({"detail": str(error)}) from error
        except services.ContactNotFound as error:
            raise ValidationError({"contact": [str(error)]}) from error
        except services.IncompleteRecipientData as error:
            raise ValidationError(
                {"contact": [str(error)], "fields": list(error.fields)}
            ) from error
        except services.OfferUnavailable as error:
            return _offer_conflict(error)

        return Response(
            OrderDetailSerializer(_with_items(order)).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["orders"])
@extend_schema_view(
    list=extend_schema(summary="История заказов"),
    retrieve=extend_schema(summary="Заказ по идентификатору"),
)
class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Оформленные заказы текущего пользователя.

    Корзина в выдачу не попадает: незакрытый фильтр означал бы
    попадание корзины в историю заказов (ADR-009).
    """

    permission_classes = (permissions.IsAuthenticated,)

    def get_serializer_class(self) -> type[OrderListSerializer]:
        if self.action == "retrieve":
            return OrderDetailSerializer
        return OrderListSerializer

    def get_queryset(self) -> QuerySet[Order]:
        """Только свои оформленные заказы, с предзагрузкой позиций."""
        if getattr(self, "swagger_fake_view", False):
            # Генерация OpenAPI-схемы выполняется без пользователя.
            return Order.objects.none()

        return (
            Order.objects.orders()
            .filter(user=self.request.user)
            .prefetch_related("items")
        )


def _with_items(order: Order) -> Order:
    """Перечитать заказ с предзагруженными позициями.

    Сериализаторы корзины и заказа обходят позиции и связанные с ними
    товар и магазин; без предзагрузки это даёт N+1 (`coding_rules.md`).
    """
    return (
        Order.objects.filter(pk=order.pk)
        .prefetch_related(
            "items__product_info__product",
            "items__product_info__shop",
        )
        .get()
    )
