"""Маршруты API приложения orders: /api/orders/.

Маршруты корзины и оформления объявлены до маршрутов роутера: иначе
`cart` и `checkout` попали бы в детальный маршрут заказа как значение
идентификатора.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from orders.views import (
    CartItemDetailView,
    CartItemsView,
    CartView,
    CheckoutView,
    OrderViewSet,
)

app_name = "orders"

router = DefaultRouter()
router.register("", OrderViewSet, basename="order")

urlpatterns = [
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/", CartItemsView.as_view(), name="cart-items"),
    path("cart/items/<int:pk>/", CartItemDetailView.as_view(), name="cart-item"),
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("", include(router.urls)),
]
