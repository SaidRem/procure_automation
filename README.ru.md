# Procure Automation

[English](README.md) | **Русский**

Backend-сервис автоматизации закупок в розничной сети: покупатели собирают
заказ из каталога нескольких поставщиков, поставщики обновляют прайс и
управляют приёмом заказов. Взаимодействие — через REST API.

Проект разрабатывается как Django modular monolith: бизнес-функциональность
разделена на независимые Django-приложения, бизнес-логика вынесена в
сервисный слой, все значимые архитектурные решения зафиксированы в ADR.

## Технологии

| Слой | Инструменты |
|---|---|
| Backend | Python 3.14, Django 5.2, Django REST Framework |
| Аутентификация | JWT (`djangorestframework-simplejwt`) |
| Документация API | drf-spectacular (OpenAPI 3) |
| Хранилище | PostgreSQL 16 |
| Фоновые задачи | Celery 5, Redis 7 |
| Тесты | pytest, pytest-django |
| Управление зависимостями | uv |

## Статус

Реализовано:

- **users** — кастомная модель пользователя (вход по email, типы
  `buyer`/`shop`), регистрация с подтверждением email, JWT-аутентификация,
  восстановление пароля, профиль, контакты (адреса доставки).
- **suppliers** — модель `Shop`, загрузка прайса по ссылке (https,
  таймауты, лимит размера, защита от SSRF), разбор YAML, оркестрация
  импорта, Celery-задача импорта с политикой повторов.
- **catalog** — категории, товары, предложения поставщиков,
  характеристики; сервис импорта прайса (upsert по `(shop, external_id)`,
  мягкая деактивация исчезнувших предложений, реактивация вернувшихся).

В работе:

- API поставщика (запуск импорта, включение/отключение приёма заказов);
- каталог: список товаров с фильтрацией и поиском;
- **orders** — корзина, оформление заказа, история;
- **notifications** — письма клиенту, администратору и поставщику;
- админка склада, экспорт прайса, Docker-образ приложения.

## Быстрый старт

Требуются [uv](https://docs.astral.sh/uv/) и Docker.

```bash
# 1. Инфраструктура: PostgreSQL на порту 5433 и Redis на 6379
docker compose up -d

# 2. Зависимости
uv sync

# 3. Переменные окружения
cp .env.example .env
# заполнить как минимум DJANGO_SECRET_KEY, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
# значения БД по умолчанию — в docker-compose.yml

# 4. Миграции и суперпользователь
cd backend
uv run python manage.py migrate
uv run python manage.py createsuperuser

# 5. Запуск
uv run python manage.py runserver
```

Фоновые задачи (импорт прайса, письма) выполняет отдельный процесс:

```bash
cd backend
uv run celery -A config worker -l info
```

Без запущенного воркера письма и импорт остаются в очереди Redis: HTTP-ответ
приходит сразу, обработка происходит асинхронно.

### Переменные окружения

Полный список — в `.env.example`. Ключевые:

| Переменная | Назначение |
|---|---|
| `DJANGO_SECRET_KEY` | ключ подписи Django и JWT |
| `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | режим и разрешённые хосты |
| `POSTGRES_*` | подключение к базе (порт по умолчанию — 5433) |
| `REDIS_*`, `CELERY_*` | брокер и result backend Celery |
| `DJANGO_EMAIL_BACKEND`, `EMAIL_*` | отправка почты; по умолчанию письма печатаются в консоль |
| `FRONTEND_URL` | база для ссылок в письмах |
| `PASSWORD_RESET_TIMEOUT` | срок жизни токенов подтверждения email и сброса пароля |

## API

Базовый префикс — `/api/`. Аутентификация — JWT: `Authorization: Bearer <access>`.

| Метод | Endpoint | Доступ |
|---|---|---|
| POST | `/api/auth/register/` | публичный |
| POST | `/api/auth/register/confirm/` | публичный |
| POST | `/api/auth/login/` | публичный |
| POST | `/api/auth/token/refresh/` | публичный |
| POST | `/api/auth/password-reset/` | публичный |
| POST | `/api/auth/password-reset/confirm/` | публичный |
| GET, PATCH | `/api/users/profile/` | по токену |
| GET, POST | `/api/users/contacts/` | по токену |
| GET, PUT, PATCH | `/api/users/contacts/{id}/` | по токену |

Интерактивная документация — `/api/schema/swagger-ui/` и
`/api/schema/redoc/`, машинная схема — `/api/schema/`.

Подробное описание запросов, ответов и кодов ошибок: [docs/api.md](docs/api.md).

## Структура

```
backend/
  config/      настройки проекта, URL-маршруты, Celery-приложение
  users/       пользователи, аутентификация, контакты
  suppliers/   поставщики, загрузка и разбор прайса, Celery-задача импорта
    importers/   транспорт и формат файла прайса
    services/    оркестрация импорта
  catalog/     категории, товары, предложения поставщиков
    services/    импорт прайса в каталог (публичный интерфейс домена)
docs/          документация проекта
```

Приложение отвечает за свой домен; обращение к чужому домену идёт только
через его публичный сервисный слой (`<app>.services`). Направление
зависимостей на уровне моделей: `catalog → suppliers → users`.

## Разработка

```bash
cd backend

uv run pytest                                  # тесты
uv run python manage.py check                  # проверки Django
uv run python manage.py makemigrations --check # миграции соответствуют моделям
uv run python manage.py spectacular --validate --fail-on-warn --file schema.yaml
```

Правила, которых придерживается проект:

- бизнес-логика — в `services/`, представления остаются тонкими;
- модели описывают структуру данных и ограничения, а не процессы;
- исторические данные не удаляются: вместо удаления используется
  деактивация и snapshot состояния на момент операции;
- каждая функциональность сопровождается тестами и обновлением документации.

## Документация

| Документ | Содержание |
|---|---|
| [docs/api.md](docs/api.md) | endpoints, форматы запросов и ответов |
| [docs/database.md](docs/database.md) | сущности, связи, ограничения, индексы |
| [docs/decisions.md](docs/decisions.md) | архитектурные решения (ADR) |
| [docs/deployment.md](docs/deployment.md) | развёртывание |

Решения фиксируются в формате ADR: контекст, решение, обоснование и
последствия. Принятые ADR не переписываются задним числом — уточнения
добавляются отдельными датированными блоками. Изменение архитектуры
начинается с нового ADR, а не с кода.
