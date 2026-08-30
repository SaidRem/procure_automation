"""Маршруты API приложения catalog: /api/catalog/."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from catalog.views import CatalogOfferViewSet

app_name = "catalog"

router = DefaultRouter()
router.register("products", CatalogOfferViewSet, basename="product")

urlpatterns = [
    path("", include(router.urls)),
]
