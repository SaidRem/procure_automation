"""URL configuration for config project.

API приложения users подключается по двум префиксам (см. docs/api.md):

- /api/auth/  — публичные endpoints регистрации, входа и сброса пароля;
- /api/users/ — endpoints авторизованного пользователя.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from users.urls import auth_urlpatterns

urlpatterns = [
    path('admin/', admin.site.urls),

    path('api/auth/', include((auth_urlpatterns, 'auth'))),
    path('api/users/', include('users.urls')),
    path('api/catalog/', include('catalog.urls')),
    path('api/orders/', include('orders.urls')),

    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path(
        'api/schema/swagger-ui/',
        SpectacularSwaggerView.as_view(url_name='schema'),
        name='swagger-ui',
    ),
    path(
        'api/schema/redoc/',
        SpectacularRedocView.as_view(url_name='schema'),
        name='redoc',
    ),
]
