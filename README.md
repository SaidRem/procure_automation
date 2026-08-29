# Procure Automation

**English** | [Русский](README.ru.md)

Backend service for procurement automation in a retail network: buyers
assemble an order from a catalog supplied by several vendors, while suppliers
update their price lists and control whether they accept orders. All
interaction happens over a REST API.

The project is built as a Django modular monolith: business functionality is
split into independent Django applications, business logic lives in a service
layer, and every significant architectural decision is recorded as an ADR.

## Tech stack

| Layer | Tools |
|---|---|
| Backend | Python 3.14, Django 5.1, Django REST Framework |
| Authentication | JWT (`djangorestframework-simplejwt`) |
| API documentation | drf-spectacular (OpenAPI 3) |
| Storage | PostgreSQL 16 |
| Background jobs | Celery 5, Redis 7 |
| Tests | pytest, pytest-django |
| Dependency management | uv |

## Status

Implemented:

- **users** — custom user model (email as login, `buyer`/`shop` types),
  registration with email confirmation, JWT authentication, password reset,
  profile, contacts (delivery addresses).
- **suppliers** — the `Shop` model, price list download over a link (https
  only, timeouts, size limit, SSRF protection), YAML parsing, import
  orchestration, a Celery import task with an explicit retry policy.
- **catalog** — categories, products, supplier offers and product parameters;
  the price import service (upsert by `(shop, external_id)`, soft
  deactivation of offers that disappeared from the price list, reactivation
  of returning ones).

In progress:

- supplier API (triggering an import, switching order acceptance on and off);
- catalog: product listing with filtering and search;
- **orders** — shopping cart, order placement, order history;
- **notifications** — emails to the customer, the administrator and the supplier;
- warehouse admin, price list export, an application Docker image.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
# 1. Infrastructure: PostgreSQL on port 5433 and Redis on 6379
docker compose up -d

# 2. Dependencies
uv sync

# 3. Environment variables
cp .env.example .env
# fill in at least DJANGO_SECRET_KEY, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
# the default database values are in docker-compose.yml

# 4. Migrations and a superuser
cd backend
uv run python manage.py migrate
uv run python manage.py createsuperuser

# 5. Run
uv run python manage.py runserver
```

Background jobs (price import, emails) run in a separate process:

```bash
cd backend
uv run celery -A config worker -l info
```

Without a running worker, emails and imports stay queued in Redis: the HTTP
response returns immediately and the work is processed asynchronously.

### Environment variables

The full list lives in `.env.example`. The important ones:

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django and JWT signing key |
| `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | mode and allowed hosts |
| `POSTGRES_*` | database connection (default port is 5433) |
| `REDIS_*`, `CELERY_*` | Celery broker and result backend |
| `DJANGO_EMAIL_BACKEND`, `EMAIL_*` | mail delivery; by default emails are printed to the console |
| `FRONTEND_URL` | base for links inside emails |
| `PASSWORD_RESET_TIMEOUT` | lifetime of email confirmation and password reset tokens |

## API

Base prefix is `/api/`. Authentication is JWT: `Authorization: Bearer <access>`.

| Method | Endpoint | Access |
|---|---|---|
| POST | `/api/auth/register/` | public |
| POST | `/api/auth/register/confirm/` | public |
| POST | `/api/auth/login/` | public |
| POST | `/api/auth/token/refresh/` | public |
| POST | `/api/auth/password-reset/` | public |
| POST | `/api/auth/password-reset/confirm/` | public |
| GET, PATCH | `/api/users/profile/` | authenticated |
| GET, POST | `/api/users/contacts/` | authenticated |
| GET, PUT, PATCH | `/api/users/contacts/{id}/` | authenticated |

Interactive documentation is served at `/api/schema/swagger-ui/` and
`/api/schema/redoc/`, the machine-readable schema at `/api/schema/`.

Request and response formats and error codes are described in
[docs/api.md](docs/api.md) (in Russian).

## Layout

```
backend/
  config/      project settings, URL routes, Celery application
  users/       users, authentication, contacts
  suppliers/   suppliers, price list download and parsing, Celery import task
    importers/   transport and file format
    services/    import orchestration
  catalog/     categories, products, supplier offers
    services/    price import into the catalog (the domain's public interface)
docs/          project documentation
```

Every application owns its domain; another domain is reached only through its
public service layer (`<app>.services`). The model-level dependency direction
is `catalog → suppliers → users`.

## Development

```bash
cd backend

uv run pytest                                  # tests
uv run python manage.py check                  # Django checks
uv run python manage.py makemigrations --check # migrations match the models
uv run python manage.py spectacular --validate --fail-on-warn --file schema.yaml
```

Rules the project follows:

- business logic belongs in `services/`, views stay thin;
- models describe data structure and constraints, not processes;
- historical data is never deleted: deactivation and a snapshot of the state
  at the moment of the operation are used instead;
- every feature comes with tests and a documentation update.

## Documentation

Project documentation is maintained in Russian.

| Document | Contents |
|---|---|
| [docs/api.md](docs/api.md) | endpoints, request and response formats |
| [docs/database.md](docs/database.md) | entities, relations, constraints, indexes |
| [docs/decisions.md](docs/decisions.md) | architecture decision records (ADR) |
| [docs/deployment.md](docs/deployment.md) | deployment |

Decisions are recorded as ADRs: context, decision, rationale and
consequences. Accepted ADRs are never rewritten after the fact — clarifications
are appended as separate dated blocks. An architectural change starts with a
new ADR, not with code.
