"""Маршруты API приложения suppliers: /api/suppliers/.

Действие запуска импорта объявлено методом `import_`: `import` —
ключевое слово Python. В URL оно выводится как `import/` (ADR-026).
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from suppliers.views import ShopViewSet

app_name = "suppliers"

router = DefaultRouter()
router.register("", ShopViewSet, basename="shop")

urlpatterns = [
    path("", include(router.urls)),
]
