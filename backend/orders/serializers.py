"""Сериализаторы приложения orders.

Корзина и оформленный заказ читают цену и наименование из разных
источников (ADR-009): пока заказ в состоянии `basket`, источник —
текущий `catalog.ProductInfo`; после подтверждения — snapshot-поля
самой позиции (ADR-003). Правило выражено двумя разными парами
сериализаторов, а не ветвлением внутри одного: ветвление легко
пропустить, разные классы — нет.

Бизнес-правила остаются в `orders.services` (ADR-006): сериализаторы
проверяют только формат данных.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from catalog.models import ProductInfo
from orders.models import Order, OrderItem
from users.models import Contact


class CartItemSerializer(serializers.ModelSerializer):
    """Позиция корзины: цена и наименование — из текущего каталога."""

    product_info = serializers.PrimaryKeyRelatedField(read_only=True)
    product_name = serializers.CharField(source="product_info.product.name", read_only=True)
    shop = serializers.CharField(source="product_info.shop.name", read_only=True)
    shop_accepts_orders = serializers.BooleanField(
        source="product_info.shop.state", read_only=True
    )
    price = serializers.DecimalField(
        source="product_info.price",
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )
    available = serializers.IntegerField(source="product_info.quantity", read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = (
            "id",
            "product_info",
            "product_name",
            "shop",
            "shop_accepts_orders",
            "price",
            "available",
            "quantity",
            "total",
        )

    def get_total(self, item: OrderItem) -> Decimal:
        """Сумма позиции по текущей цене каталога."""
        return item.product_info.price * item.quantity


class CartSerializer(serializers.ModelSerializer):
    """Корзина покупателя — заказ в состоянии `basket` (ADR-009)."""

    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ("id", "items", "total")

    def get_total(self, order: Order) -> Decimal:
        """Сумма корзины по текущим ценам каталога."""
        return sum(
            (item.product_info.price * item.quantity for item in order.items.all()),
            Decimal("0.00"),
        )


class CartItemCreateSerializer(serializers.Serializer):
    """Добавление предложения в корзину.

    Проверяется только формат: существование предложения и его
    доступность к заказу — правило домена, живущее в
    `orders.services` (ADR-025, ADR-006).
    """

    product_info = serializers.PrimaryKeyRelatedField(queryset=ProductInfo.objects.all())
    quantity = serializers.IntegerField(min_value=1)


class CartItemUpdateSerializer(serializers.Serializer):
    """Изменение количества позиции корзины."""

    quantity = serializers.IntegerField(min_value=1)


class CheckoutSerializer(serializers.Serializer):
    """Оформление заказа по выбранному контакту.

    Принадлежность контакта пользователю и полнота данных получателя
    проверяются сервисом (ADR-024, ADR-027): это правила домена, а не
    формата.
    """

    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.all())


class OrderItemSerializer(serializers.ModelSerializer):
    """Позиция оформленного заказа: данные из snapshot (ADR-003).

    Ни `product_info`, ни каталог здесь не читаются: предложение могло
    измениться, быть деактивировано или удалено, а заказ обязан
    показывать то, что было заказано.
    """

    total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = (
            "id",
            "product_name",
            "shop_name",
            "price",
            "price_rrc",
            "quantity",
            "total",
        )

    def get_total(self, item: OrderItem) -> Decimal:
        """Сумма позиции по зафиксированной цене."""
        return item.price * item.quantity


class OrderListSerializer(serializers.ModelSerializer):
    """Заказ в истории: «Номер, Дата, Сумма, Статус» (private/screens.md)."""

    total = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ("id", "confirmed_at", "state", "total")

    def get_total(self, order: Order) -> Decimal:
        """Сумма заказа по snapshot-ценам позиций."""
        return sum(
            (item.price * item.quantity for item in order.items.all()),
            Decimal("0.00"),
        )


class OrderDetailSerializer(OrderListSerializer):
    """Карточка заказа: позиции и адрес доставки из snapshot."""

    items = OrderItemSerializer(many=True, read_only=True)
    delivery = serializers.SerializerMethodField()

    class Meta(OrderListSerializer.Meta):
        fields = (*OrderListSerializer.Meta.fields, "items", "delivery")

    def get_delivery(self, order: Order) -> dict[str, str]:
        """Получатель и адрес на момент оформления (ADR-024, ADR-027).

        Источник — поля `delivery_*` заказа, а не связанный `Contact`,
        который мог быть изменён или удалён, и не учётная запись
        покупателя: заказ мог быть оформлен на другого получателя.
        """
        return {
            "last_name": order.delivery_last_name,
            "first_name": order.delivery_first_name,
            "middle_name": order.delivery_middle_name,
            "email": order.delivery_email,
            "phone": order.delivery_phone,
            "city": order.delivery_city,
            "street": order.delivery_street,
            "house": order.delivery_house,
            "structure": order.delivery_structure,
            "building": order.delivery_building,
            "apartment": order.delivery_apartment,
        }
