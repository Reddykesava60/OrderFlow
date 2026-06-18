# Application Deployment Guide

This guide covers deploying the Dineflow platform to production. The codebase is already configured for zero-downtime PaaS deployment (specifically [Railway.app](https://railway.app/)), making it the easiest path for a startup to launch.

---

## 1. Prerequisites

Before deploying, ensure you have active accounts for:
- **[Railway](https://railway.app/)** (Hosting, Database, Redis)
- **[Razorpay](https://razorpay.com/)** (Payment Gateway)
- **[Supabase](https://supabase.com/)** (Used as an S3-compatible bucket for menu images)

## 2. Deploying on Railway (Recommended)

Railway is an infrastructure platform that natively supports our `Procfile`, `Dockerfile`, and `railway.json`.

### Step A: Provision Infrastructure
1. Log in to Railway and click **"New Project"**.
2. Click **"New"** and select **"Provision Redis"** (Required for WebSockets and Celery).
3. Click **"New"** and select **"GitHub Repo"**, then select your Dineflow repository.

*Note on Database*: You mentioned using **Supabase**. Supabase is an excellent choice for a production PostgreSQL database! Because you are using Supabase for your database, you **do not** need to provision PostgreSQL on Railway. You will simply connect Railway to your Supabase database using an environment variable.

### Step B: Configure Environment Variables
Click on your newly deployed GitHub repository in the Railway dashboard, navigate to the **Variables** tab, and click **"Raw Editor"**. Paste your production environment variables:

```ini
DEBUG=False
SECRET_KEY=generate-a-very-long-random-string-here
PAYMENT_ENCRYPTION_KEY=generate-a-distinct-long-random-string-here
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,dineflow.up.railway.app
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://dineflow.up.railway.app
DJANGO_SETTINGS_MODULE=dineflow.settings.prod

# Supabase PostgreSQL Connection String
# (Go to Supabase -> Database -> Settings -> Connection String -> URI)
# *Important*: Use the transaction connection pooler string (usually port 6543)
DATABASE_URL=postgres://postgres.yourproject:yourpassword@aws-0-region.pooler.supabase.com:6543/postgres

# Supabase (Media Storage)
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key

# Railway will automatically inject REDIS_URL for you!

# Optional: Sentry for Error Tracking
SENTRY_DSN=your_sentry_dsn
```

### Step C: Define the Services (Procfile)
Because our codebase includes a `Procfile`, Railway will automatically detect that we have multiple processes.
In the Railway Dashboard, right-click the canvas and click **"Service"** -> **"Empty Service"**. You need to create three services from the same repository:

1. **Web Service (Daphne/ASGI)**
   - **Start Command**: *Leave this blank!* (Click "Remove start command" if you added one). Railway will automatically use the command built into the `Dockerfile`, which properly handles the dynamic `$PORT` variable.
   - **Networking**: Generate a domain for this service. This is your public URL.
2. **Worker Service (Celery)**
   - **Start Command**: `celery -A dineflow worker -Q celery,payments -l info --concurrency=2`
3. **Beat Service (Celery Beat)**
   - **Start Command**: `celery -A dineflow beat -l info`

*Note: The `railway.json` file in the repo will automatically run `python manage.py migrate` before the Web service boots up.*

---

## 3. Post-Deployment Steps

Once the deployment shows green on Railway, you need to configure the application logic.

### 1. Create the Superuser
Open the Railway CLI or use the Railway dashboard "Command" palette for the Web service:
```bash
python manage.py createsuperuser
```
Log in to `https://yourdomain.com/admin/` with this user.

### 2. Configure the Restaurant Tenant
1. Navigate to **Restaurants** in the Django Admin.
2. Create your restaurant. The `slug` you choose will dictate the URL (e.g., `slug='pizza-hut'` means the menu is at `/r/pizza-hut/`).

### 3. Link Razorpay Webhooks
1. Log into your Razorpay Dashboard (Live Mode).
2. Navigate to **Settings > Webhooks**.
3. Add a new Webhook pointing to: `https://yourdomain.com/payments/webhook/`
4. Select the following events:
   - `order.paid`
   - `payment.captured`
   - `payment.failed`
5. Generate a **Secret**.
6. Back in the Django Admin, go to **Restaurant Payment Configs**, select your restaurant, and paste your Razorpay Key ID, Key Secret, and Webhook Secret.

---

## 4. Alternate Deployment: VPS (Docker Compose)

If you prefer to host this on AWS EC2, DigitalOcean, or Hetzner, the repository includes a `docker-compose.yml` file.

1. SSH into your Ubuntu server.
2. Clone the repository.
3. Copy `.env.example` to `.env` and fill in the secrets (including setting up your own Postgres and Redis URLs).
4. Run the stack:
   ```bash
   docker compose up -d --build
   ```
5. You must put Nginx or Caddy in front of the `web` container (running on port `8000`) to handle SSL/HTTPS termination. WebSockets (`/ws/`) must be proxied correctly.
