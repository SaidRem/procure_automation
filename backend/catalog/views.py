"""API приложения catalog (ADR-025).

Выдача фильтрует только `is_active=True`. Приём заказов поставщиком
(`Shop.state`) и нулевой остаток на видимость не влияют: отключение
приёма заказов — временное состояние поставщика, а не снятие товаров с
продажи. Доступность к заказу — отдельная проверка, живущая в
`orders.services`.
"""

from __future__ import annotations

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets

from catalog.models import ProductInfo
from catalog.serializers import CatalogOfferSerializer


@extend_schema(tags=["catalog"])
@extend_schema_view(
    list=extend_schema(
        summary="Каталог предложений",
        description=(
            "Активные предложения поставщиков. Предложения поставщика, "
            "временно не принимающего заказы, остаются в выдаче с "
            "признаком `shop_accepts_orders=false`."
        ),
    ),
    retrieve=extend_schema(summary="Предложение по идентификатору"),
)
class CatalogOfferViewSet(viewsets.ReadOnlyModelViewSet):
    """Каталог товаров: список и карточка предложения."""

    serializer_class = CatalogOfferSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self) -> QuerySet[ProductInfo]:
        """Активные предложения с предзагрузкой связей.

        `select_related` и `prefetch_related` обязательны: карточка
        содержит товар, категорию, магазин и характеристики, и без
        предзагрузки выдача даёт N+1 (`coding_rules.md`).
        """
        return (
            ProductInfo.objects.filter(is_active=True)
            .select_related("product", "product__category", "shop")
            .prefetch_related("product_parameters__parameter")
            .order_by("id")
        )
