"""API приложения catalog (ADR-025).

Выдача фильтрует только `is_active=True`. Приём заказов поставщиком
(`Shop.state`) и нулевой остаток на видимость не влияют: отключение
приёма заказов — временное состояние поставщика, а не снятие товаров с
продажи. Доступность к заказу — отдельная проверка, живущая в
`orders.services`.
"""

from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, permissions, viewsets

from catalog.models import ProductInfo
from catalog.serializers import CatalogOfferSerializer


@extend_schema(tags=["catalog"])
@extend_schema_view(
    list=extend_schema(
        summary="Каталог предложений",
        description=(
            "Активные предложения поставщиков. Предложения поставщика, "
            "временно не принимающего заказы, остаются в выдаче с "
            "признаком `shop_accepts_orders=false`.\n\n"
            "Фильтрация — по магазину и категории, поиск (`search`) — по "
            "названию товара, модели, категории и названию магазина."
        ),
    ),
    retrieve=extend_schema(summary="Предложение по идентификатору"),
)
class CatalogOfferViewSet(viewsets.ReadOnlyModelViewSet):
    """Каталог товаров: список и карточка предложения."""

    serializer_class = CatalogOfferSerializer
    permission_classes = (permissions.IsAuthenticated,)

    # Поиск подключается на уровне представления, а не глобально: он
    # осмыслен для каталога и бесполезен для остальных разделов.
    filter_backends = (DjangoFilterBackend, filters.SearchFilter)

    # Фильтры выражены полями предложения. Признак приёма заказов сюда
    # не входит: он не влияет на видимость товара (ADR-025), а фильтр по
    # нему предлагал бы покупателю прятать часть каталога.
    filterset_fields = ("shop", "product__category")

    search_fields = (
        "product__name",
        "model",
        "product__category__name",
        "shop__name",
    )

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
