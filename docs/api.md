# API

REST API на Django REST Framework.

Базовый префикс: `/api/`.

Формат обмена — JSON. Аутентификация — JWT (ADR-007), заголовок:

```
Authorization: Bearer <access>
```

По умолчанию все endpoints требуют аутентификации
(`DEFAULT_PERMISSION_CLASSES = IsAuthenticated`); публичные точки входа
помечены ниже явно.

Список выдаётся постранично (`PAGE_SIZE = 20`), ответ содержит
`count`, `next`, `previous`, `results`.


## OpenAPI

Схема генерируется drf-spectacular:

| URL | Назначение |
|---|---|
| `GET /api/schema/` | OpenAPI 3 схема (YAML) |
| `GET /api/schema/swagger-ui/` | Swagger UI |
| `GET /api/schema/redoc/` | ReDoc |

Проверка схемы (из каталога `backend/`):

```
uv run python manage.py spectacular --validate --fail-on-warn --file schema.yaml
```


## Реализовано

Приложение `users` (шаг 2). Endpoints каталога, корзины и заказов
появятся вместе с приложениями `catalog`, `suppliers`, `orders`.


### Аутентификация и регистрация — `/api/auth/`

Все endpoints раздела публичные (`AllowAny`).

| Метод | URL | Назначение |
|---|---|---|
| POST | `/api/auth/register/` | регистрация пользователя |
| POST | `/api/auth/register/confirm/` | подтверждение email |
| POST | `/api/auth/login/` | получение пары JWT-токенов |
| POST | `/api/auth/token/refresh/` | обновление access-токена |
| POST | `/api/auth/password-reset/` | запрос восстановления пароля |
| POST | `/api/auth/password-reset/confirm/` | установка нового пароля |


#### POST /api/auth/register/

Запрос:

```json
{
  "email": "buyer@example.com",
  "password": "StrongPass123!",
  "first_name": "Иван",
  "last_name": "Иванов",
  "company": "ООО Ромашка",
  "position": "Менеджер",
  "type": "buyer"
}
```

Обязательные поля — `email` и `password`. Пароль проверяется валидаторами
Django (`AUTH_PASSWORD_VALIDATORS`) и не возвращается в ответе.

Ответ `201`:

```json
{"id": 1, "email": "buyer@example.com", "type": "buyer", "company": "", "position": ""}
```

Пользователь создаётся с `is_active=False` (ADR-004); письмо со ссылкой
подтверждения ставится в очередь Celery после коммита транзакции
(ADR-005, ADR-010). До подтверждения вход возвращает `401`.

Ошибки: `400` — email занят, email отсутствует, пароль не прошёл
валидацию.


#### POST /api/auth/register/confirm/

Запрос:

```json
{"uid": "MQ", "token": "de2zpa-d718bd48abf09570ea62040ca24fb648"}
```

`uid` и `token` приходят пользователю в письме (ссылка вида
`{FRONTEND_URL}/auth/confirm-email?uid=...&token=...`).

Ответ `200`: `{"detail": "Email подтверждён."}` — пользователь получает
`is_active=True`.

Ошибки: `400` — токен неверный, истёк, принадлежит другому пользователю
или уже использован. Токен одноразовый и живёт `PASSWORD_RESET_TIMEOUT`
секунд — в проекте 24 часа (ADR-011).


#### POST /api/auth/login/

Запрос: `{"email": "...", "password": "..."}`.

Ответ `200`: `{"access": "...", "refresh": "..."}`.
Время жизни: access — 60 минут, refresh — 1 сутки.

Ошибки: `401` — неверные данные либо неподтверждённый пользователь
(ответ намеренно не различает эти случаи).


#### POST /api/auth/token/refresh/

Запрос: `{"refresh": "..."}`. Ответ `200`: `{"access": "..."}`.

Rotation и blacklist не используются (ADR-007).


#### POST /api/auth/password-reset/

Запрос: `{"email": "..."}`.

Ответ `200` возвращается всегда, независимо от того, зарегистрирован ли
адрес: наличие пользователя в системе не раскрывается. Письмо отправляется
только активному пользователю и содержит ссылку вида
`{FRONTEND_URL}/auth/password-reset?uid=...&token=...`.


#### POST /api/auth/password-reset/confirm/

Запрос:

```json
{"uid": "MQ", "token": "...", "password": "AnotherStrong456!"}
```

Ответ `200`: `{"detail": "Пароль изменён."}`.

Ошибки: `400` — токен неверный/истёк/уже использован либо новый пароль не
прошёл валидацию. Токен одноразовый: после смены пароля он невалиден.
Срок жизни — общий для обоих типов токенов `PASSWORD_RESET_TIMEOUT`,
в проекте 24 часа (ADR-011).


### Профиль — `/api/users/profile/`

Требуется аутентификация.

| Метод | Назначение |
|---|---|
| GET | профиль текущего пользователя |
| PATCH | изменение `company` и `position` |

Ответ `200`:

```json
{"id": 1, "email": "buyer@example.com", "type": "buyer", "company": "ООО Ромашка", "position": "Менеджер"}
```

`email` и `type` доступны только для чтения. Переданные значения этих
полей игнорируются: смена email потребовала бы повторного подтверждения
адреса, смена `type` — изменения бизнес-роли пользователя.

PUT не поддерживается и возвращает `405`: полная замена профиля не имеет
смысла при двух изменяемых полях.

Ошибки: `401` — запрос без токена.


### Контакты — `/api/users/contacts/`

Требуется аутентификация. Пользователь работает только со своими
контактами: выборка ограничена `request.user`, обращение к чужому
объекту возвращает `404`.

| Метод | URL | Назначение |
|---|---|---|
| GET | `/api/users/contacts/` | список своих контактов |
| POST | `/api/users/contacts/` | создание контакта |
| GET | `/api/users/contacts/{id}/` | контакт по идентификатору |
| PUT / PATCH | `/api/users/contacts/{id}/` | изменение контакта |

Запрос на создание:

```json
{
  "city": "Москва",
  "street": "Тверская",
  "house": "1",
  "structure": "",
  "building": "",
  "apartment": "",
  "phone": "+70000000000"
}
```

Обязательные поля: `city`, `street`, `phone`. Владелец контакта берётся
из токена и не передаётся в запросе.

**DELETE не реализован** и возвращает `405`: адрес доставки участвует в
истории заказов, физическое удаление исторических данных запрещено
правилами проекта (ADR-003). Способ скрытия неактуальных адресов будет
определён при реализации приложения `orders`.
