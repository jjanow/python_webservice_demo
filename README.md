# Inventory & Orders API

A demo backend service — a small B2B inventory and order-management API — built with **FastAPI** to show practical patterns for production-style Python web services: async SQLAlchemy, JWT auth with role-based access control, transactional business logic, input validation, rate limiting, structured logging, and a Prometheus metrics endpoint.

## Why FastAPI

Chosen over Flask for this demo because it gives type-hint-driven request/response validation, automatic OpenAPI docs (`/docs`), and native async support — all of which line up well with how the rest of the stack (SQLAlchemy async, async test client) is built.

## Domain

- **Product** — SKU, price, stock quantity. Soft-deleted (`is_active=false`) rather than hard-deleted, since past orders reference it.
- **Customer** — a business customer placing orders (not a login account).
- **Order / OrderItem** — created against a customer and a list of products/quantities. Stock is validated for *every* line item before *any* of them is decremented, so a single insufficient-stock item can't leave the order half-applied. `unit_price` is snapshotted onto each `OrderItem` at order time, so a later product price change never rewrites history. `total_amount` is always computed server-side, never trusted from the client.
- **User** — internal staff accounts (`admin` or `staff` role) used to authenticate against the API. Separate from `Customer`.

### Role-based access control

| Action | admin | staff |
|---|---|---|
| Read products/customers/orders | ✅ | ✅ |
| Create/update/delete products | ✅ | ❌ (403) |
| Create/update customers | ✅ | ✅ |
| Delete customers | ✅ | ❌ (403) |
| Create orders / change order status | ✅ | ✅ |

There is **no** `/auth/register`-as-admin path. Exactly one admin account is seeded at startup from `ADMIN_EMAIL`/`ADMIN_PASSWORD`; `POST /auth/register` always creates a `staff` account server-side regardless of what a client sends in the request body — this avoids a privilege-escalation hole.

### Order status transitions

```
pending -> paid -> shipped
pending -> cancelled
paid    -> cancelled
```

Any other transition (e.g. `shipped -> pending`, or out of `shipped`/`cancelled`) is rejected with `409`. Cancelling a `pending` or `paid` order restocks all of its items.

## Endpoints

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/auth/register` | none | creates a `staff` user; 5/min rate limit |
| POST | `/auth/login` | none | OAuth2 password flow, returns a JWT; 5/min rate limit |
| GET | `/auth/me` | any | current user's profile |
| GET | `/products` | any | pagination, filtering (`min_price`, `max_price`, `in_stock`, `search`), sorting |
| POST | `/products` | admin | create |
| GET/PATCH/DELETE | `/products/{id}` | any (write: admin) | DELETE is a soft delete |
| GET | `/customers` | any | search by name/email |
| POST/PATCH | `/customers/{id}`... | admin/staff | create/update |
| DELETE | `/customers/{id}` | admin | 409 if the customer has orders |
| POST | `/orders` | admin/staff | atomic stock validation + decrement |
| GET | `/orders`, `/orders/{id}` | admin/staff | filter by status, customer |
| PATCH | `/orders/{id}/status` | admin/staff | enforces valid transitions, restocks on cancel |
| GET | `/health/live` | none | liveness |
| GET | `/health/ready` | none | checks DB connectivity |
| GET | `/metrics` | none | Prometheus exposition format |
| GET | `/docs` | none | interactive OpenAPI docs |

Full request/response schemas are in the auto-generated docs at `/docs` once the server is running.

## Security & operational notes

- Passwords hashed with `bcrypt` directly (not via `passlib`, which is incompatible with `bcrypt>=4.1`). Since bcrypt silently truncates input past 72 bytes instead of erroring, password input is explicitly rejected above 72 UTF-8 bytes rather than being silently weakened.
- JWTs signed with `PyJWT` (chosen over `python-jose`, which is unmaintained and has had algorithm-confusion CVEs).
- `SECRET_KEY` is required to be a real value (not empty/placeholder) whenever `ENVIRONMENT=production` — the app refuses to start otherwise.
- Closed-by-default CORS (`CORS_ORIGINS` is empty unless configured) and a standard set of security response headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security`).
- `/auth/login` is rate-limited (5/min/IP) against brute-force; failed logins return the same generic message whether the email exists or not.
- Every response carries an `X-Request-ID` header (generated if the client doesn't supply one), and logs are single-line JSON tagged with that request ID, so a request can be traced across a log stream.
- Every error response (validation, HTTP errors, and unhandled exceptions) is shaped consistently as `{"error": {"code": ..., "message": ...}}`; unhandled exceptions are logged with a full traceback server-side but only return a generic message to the client.

### Deliberate demo simplifications (and the production path)

This is a demo, and a few corners were deliberately cut for simplicity rather than by oversight — worth naming explicitly:

- **Schema migrations**: tables are created with `Base.metadata.create_all` on startup. A real deployment with an evolving schema needs **Alembic** migrations instead.
- **Rate limiting**: `slowapi`'s in-memory backend only works correctly for a single process/instance. Running more than one replica needs a shared backend (**Redis**).
- **Database**: SQLite is fine for a single-instance demo; a real deployment with concurrent writers should use **PostgreSQL** (the async SQLAlchemy layer makes that mostly a `DATABASE_URL` change plus swapping `aiosqlite` for `asyncpg`).
- **No refresh tokens**: only short-lived access tokens are issued; a production app would likely add refresh tokens / token revocation.
- **No row-level locking on stock**: two concurrent order requests could both pass the stock check before either decrements it, allowing overselling. SQLite serializes writes so this doesn't surface in this demo, but the production fix is `SELECT ... FOR UPDATE` row locking on Postgres around the stock check-and-decrement.

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: at minimum set a real SECRET_KEY, e.g.
python -c "import secrets; print(secrets.token_urlsafe(64))"

uvicorn app.main:app --reload
```

Then visit `http://127.0.0.1:8000/docs`, or:

```bash
curl http://127.0.0.1:8000/health/ready

# register a staff account
curl -X POST localhost:8000/auth/register -H "Content-Type: application/json" \
  -d '{"email":"staff@example.com","password":"staffpass123"}'

# log in (the seeded admin works too, with ADMIN_EMAIL/ADMIN_PASSWORD from .env)
curl -X POST localhost:8000/auth/login -d "username=staff@example.com&password=staffpass123"

# use the returned access_token as a bearer token on any other endpoint
curl localhost:8000/products -H "Authorization: Bearer <token>"
```

## Running with Docker

```bash
cp .env.example .env   # edit SECRET_KEY etc. first
docker compose up --build
```

The app listens on `localhost:8000`; SQLite data persists in a named volume (`app_data`) across container restarts.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

The suite uses an in-memory SQLite database (via `StaticPool`, since the default async pooling otherwise gives each connection its own throwaway in-memory DB) and an `httpx.AsyncClient` against the app directly — no real server or network calls. It covers auth (registration, login, RBAC, rate limiting), products/customers (CRUD, soft-delete, filtering/sorting/pagination), orders (atomic stock handling, status transitions, restocking), and the health/error/metrics endpoints.

## Linting

```bash
ruff check .
```

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs `ruff check` and the full `pytest` suite on every push and pull request to `main`.

## Project layout

```
app/
  main.py            # app factory: logging -> middleware -> exception handlers -> routers -> lifespan
  config.py          # pydantic-settings, fail-fast on insecure production config
  database.py        # async engine/session, Base, get_db dependency
  models.py          # SQLAlchemy ORM models
  schemas.py         # pydantic request/response models
  security.py        # bcrypt password hashing, PyJWT helpers
  dependencies.py    # get_current_user, require_role(*roles)
  middleware.py       # request ID, security headers, Prometheus metrics
  logging_config.py   # JSON line logging
  exceptions.py        # unified error envelope
  routers/             # auth, products, customers, orders, health
tests/                  # pytest suite (see above)
Dockerfile, docker-compose.yml, .dockerignore
.github/workflows/ci.yml
```
