"""Сериализаторы приложения catalog.

Каталог доступен только на чтение: запись выполняет импорт прайса
(ADR-008, ADR-016). Выдача строится по `ProductInfo` — предложению
конкретного поставщика, а не по логическому товару (ADR-001, ADR-025).
"""

from __future__ import annotations

from rest_framework import serializers

from catalog.models import ProductInfo, ProductParameter


class ProductParameterSerializer(serializers.ModelSerializer):
    """Характеристика товара: название и значение."""

    name = serializers.CharField(source="parameter.name", read_only=True)

    class Meta:
        model = ProductParameter
        fields = ("name", "value")


class CatalogOfferSerializer(serializers.ModelSerializer):
    """Предложение товара поставщиком в каталожной выдаче.

    Ответ содержит признак приёма заказов поставщиком и остаток
    (ADR-025): предложение остаётся видимым, когда поставщик временно
    не принимает заказы, и без этих полей клиент узнавал бы о
    невозможности заказа только по ошибке при добавлении в корзину.
    """

    product_name = serializers.CharField(source="product.name", read_only=True)
    category = serializers.CharField(source="product.category.name", read_only=True)
    shop = serializers.CharField(source="shop.name", read_only=True)
    shop_accepts_orders = serializers.BooleanField(source="shop.state", read_only=True)
    parameters = ProductParameterSerializer(
        source="product_parameters",
        many=True,
        read_only=True,
    )

    class Meta:
        model = ProductInfo
        fields = (
            "id",
            "product_name",
            "category",
            "model",
            "shop",
            "shop_accepts_orders",
            "price",
            "price_rrc",
            "quantity",
            "parameters",
        )
