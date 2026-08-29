"""Маршруты API приложения users."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from users.views import (
    ContactViewSet,
    EmailConfirmationView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ProfileView,
    RegistrationView,
)

app_name = "users"

# Публичные маршруты аутентификации: /api/auth/
auth_urlpatterns = [
    path("register/", RegistrationView.as_view(), name="register"),
    path("register/confirm/", EmailConfirmationView.as_view(), name="register-confirm"),
    path("login/", TokenObtainPairView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password-reset"),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
]

router = DefaultRouter()
router.register("contacts", ContactViewSet, basename="contact")

# Маршруты авторизованного пользователя: /api/users/
urlpatterns = [
    path("profile/", ProfileView.as_view(), name="profile"),
    path("", include(router.urls)),
]
