# Local Development Setup

Two ways to get this running locally: a lightweight native setup (fastest
to iterate with, good for working on most features) and the full Docker
Compose stack (closer to production, needed if you're working on anything
involving Celery, Redis, or Nginx specifically).

## Option A — Native setup (fastest)

### 1. Python environment

```bash
python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -r requirements.txt
 python manage.py runserver --settings=dineflow.settings.dev
```

### 2. Environment variables

Copy `.env.example` to `.env`. The only variable with no default that's
*required* even for local dev is `SECRET_KEY` and `DATABASE_URL` (both are
read via `python-decouple`'s `config()` with no fallback in
`dineflow/settings/base.py`).

For the simplest possible local database, point `DATABASE_URL` at SQLite
instead of Postgres:

```ini
DJANGO_SETTINGS_MODULE=dineflow.settings.dev
SECRET_KEY=any-long-random-string-for-local-dev
DATABASE_URL=sqlite:///db.sqlite3
```

If you want a closer-to-production setup, run Postgres via the Docker
Compose `db` service instead (see Option B) and point `DATABASE_URL` at
that.

### 3. Background jobs without Redis

If you don't have Redis running locally, set:

```ini
PAYMENT_JOBS_INLINE=True
```

This makes every Celery task usually dispatched with `.delay()` run
synchronously in the same process instead — payments and webhooks still
work end-to-end, just without the actual queue. (This is also exactly what
happens automatically in the test suite.) If you *do* want to exercise the
real queueing behavior, run Redis (the Compose `redis` service is the
easiest source) and leave this unset.

### 4. Database and a superuser

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Run the server

WebSocket support (the KDS real-time channel) requires an ASGI server —
`runserver` works for most development since Django dispatches to ASGI
under the hood when Channels is installed, but if you hit WebSocket
issues, run Daphne directly the same way production does:

```bash
python manage.py runserver
# or, closer to production:
daphne -b 0.0.0.0 -p 8000 dineflow.asgi:application
```

### 6. (Optional) Run Celery, for real queueing/scheduling behavior

```bash
celery -A dineflow worker -Q celery,payments -l info
celery -A dineflow beat -l info
```

### 7. Frontend CSS (Tailwind)

The compiled CSS is checked in (`core/static/css/tailwind.out.css`), so you
don't need this step just to run the app. If you're changing styles:

```bash
npm install
npm run watch:css     # rebuilds on change
npm run build:css     # one-off minified build
```

## Option B — Docker Compose (closer to production)

```bash
cp .env.example .env   # fill in DB/Redis values to match docker-compose.yml
docker compose up -d --build
```

This brings up `web`, `worker`, `beat`, `db` (Postgres), `redis`, and
`nginx` as separate containers — the same topology described in
[Deployment Guide](../operations/01-deployment-guide.md), just running on
your machine. Useful when you specifically need to reproduce a
Celery-queue or Nginx/WebSocket-proxying issue that the native setup can't
surface.

## First thing to set up after migrating

A fresh database has no restaurant in it. Through `/admin/`, create a
`Restaurant` (the `slug` you choose becomes the menu URL,
`/r/<slug>/`) — a `RestaurantConfig` and `RestaurantPaymentConfig` are
auto-created for it via a signal. Without at least one restaurant, there's
nothing to view at `/r/...` and nothing for a staff account to log into.

## Running tests

```bash
python manage.py test
```

Each app's tests live in its own `tests.py`
(`core/tests.py`, `ordering/tests.py`, `kitchen/tests.py`,
`owner/tests.py`). `dineflow/settings/test.py` is used automatically by
the test runner and forces `PAYMENT_JOBS_INLINE = True` so payment-related
tests don't depend on a real broker.

## Next

If you're getting ready to actually deploy this somewhere, switch to the
[Deployment Guide](../operations/01-deployment-guide.md).
