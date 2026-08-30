"""API приложения users.

Views остаются тонкими: разбор запроса, вызов сервисного слоя и формирование
ответа. Бизнес-правила находятся в `users.services` (ADR-006).
"""

from __future__ import annotations

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from users import services
from users.models import Contact, User
from users.serializers import (
    ContactSerializer,
    EmailConfirmationSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegistrationSerializer,
    UserSerializer,
)


@extend_schema(
    tags=["auth"],
    summary="Регистрация пользователя",
    description=(
        "Создаёт пользователя с `is_active=False` и отправляет письмо со "
        "ссылкой подтверждения email. До подтверждения вход невозможен."
    ),
    request=RegistrationSerializer,
    responses={201: UserSerializer},
)
class RegistrationView(APIView):
    """Регистрация нового пользователя."""

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = services.register_user(**serializer.validated_data)

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["auth"],
    summary="Подтверждение email",
    description=(
        "Активирует пользователя по одноразовому токену из письма. "
        "Повторное использование токена возвращает 400."
    ),
    request=EmailConfirmationSerializer,
    responses={
        200: OpenApiResponse(description="Email подтверждён, пользователь активирован"),
        400: OpenApiResponse(description="Токен недействителен, истёк или уже использован"),
    },
)
class EmailConfirmationView(APIView):
    """Подтверждение email по токену."""

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = EmailConfirmationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            services.confirm_email(**serializer.validated_data)
        except services.InvalidConfirmationToken as error:
            raise ValidationError({"token": ["Недействительный или использованный токен."]}) from error

        return Response({"detail": "Email подтверждён."})


@extend_schema(
    tags=["auth"],
    summary="Запрос восстановления пароля",
    description=(
        "Отправляет письмо со ссылкой установки нового пароля. Ответ не "
        "зависит от того, зарегистрирован ли адрес."
    ),
    request=PasswordResetRequestSerializer,
    responses={200: OpenApiResponse(description="Запрос принят")},
)
class PasswordResetRequestView(APIView):
    """Запрос письма для восстановления пароля."""

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        services.request_password_reset(**serializer.validated_data)

        return Response({"detail": "Если адрес зарегистрирован, письмо отправлено."})


@extend_schema(
    tags=["auth"],
    summary="Установка нового пароля",
    description="Устанавливает новый пароль по токену из письма. Токен одноразовый.",
    request=PasswordResetConfirmSerializer,
    responses={
        200: OpenApiResponse(description="Пароль изменён"),
        400: OpenApiResponse(description="Токен недействителен или пароль не прошёл валидацию"),
    },
)
class PasswordResetConfirmView(APIView):
    """Установка нового пароля по токену восстановления."""

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            services.set_new_password(**serializer.validated_data)
        except services.InvalidPasswordResetToken as error:
            raise ValidationError({"token": ["Недействительный или использованный токен."]}) from error

        return Response({"detail": "Пароль изменён."})


@extend_schema(tags=["users"])
class ProfileView(generics.RetrieveUpdateAPIView):
    """Профиль текущего пользователя."""

    serializer_class = UserSerializer
    permission_classes = (permissions.IsAuthenticated,)
    http_method_names = ("get", "patch", "head", "options")

    def get_object(self) -> User:
        return self.request.user

    @extend_schema(summary="Профиль текущего пользователя")
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Изменение профиля",
        description="Изменяются только `company` и `position`; email и тип пользователя неизменяемы.",
    )
    def patch(self, request: Request, *args: object, **kwargs: object) -> Response:
        return super().patch(request, *args, **kwargs)


@extend_schema(tags=["users"])
@extend_schema_view(
    list=extend_schema(summary="Контакты текущего пользователя"),
    create=extend_schema(summary="Создание контакта"),
    retrieve=extend_schema(summary="Контакт текущего пользователя"),
    update=extend_schema(summary="Замена контакта"),
    partial_update=extend_schema(summary="Изменение контакта"),
    destroy=extend_schema(
        summary="Удаление контакта",
        description=(
            "Удаляет адрес из адресной книги. История заказов не "
            "меняется: оформленный заказ хранит snapshot получателя и "
            "адреса, а ссылка на контакт обнуляется (ADR-024)."
        ),
    ),
)
class ContactViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Точки доставки текущего пользователя: получатель и адрес.

    Удаление разрешено (ADR-024): после появления snapshot в заказе
    контакт является записью адресной книги, а не исторической записью.
    Оформленный заказ хранит получателя и адрес в собственных полях
    `delivery_*`, а `Order.contact` объявлен `SET_NULL` — удаление
    адреса обнуляет ссылку и не трогает ни состав, ни сумму, ни адрес
    доставки заказа.
    """

    serializer_class = ContactSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self) -> QuerySet[Contact]:
        """Ограничить выборку контактами текущего пользователя."""
        if getattr(self, "swagger_fake_view", False):
            # Генерация OpenAPI-схемы выполняется без реального пользователя.
            return Contact.objects.none()

        return Contact.objects.filter(user=self.request.user).order_by("id")

    def perform_create(self, serializer: ContactSerializer) -> None:
        serializer.save(user=self.request.user)
