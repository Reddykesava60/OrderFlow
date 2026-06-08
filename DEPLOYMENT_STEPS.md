# Order-Flow Production Deployment Guide (Railway + Supabase)

This guide walks you through deploying the Order-Flow platform to Railway, using Supabase for both PostgreSQL and S3-compatible object storage.

## Phase 1: Supabase Setup

### 1. Create a Supabase Project
1. Go to [Supabase](https://supabase.com/) and create a new project.
2. Save your **Database Password** securely.

### 2. Configure Database
1. Go to **Project Settings -> Database**.
2. Find the **Connection Pooling** section.
3. Check the box for "Use connection pooling" (or ensure the port is `6543`).
4. Copy the **Connection string (URI)**. It should look like this:
   `postgresql://postgres:[YOUR-PASSWORD]@aws-0-[region].pooler.supabase.com:6543/postgres`

### 3. Configure Storage (S3)
1. Go to **Storage** in the sidebar.
2. Click **New Bucket** and name it (e.g., `orderflow-media`). **Make sure it is a Public bucket.**
3. Go to **Storage -> Settings** (or the **S3 Credentials** tab).
4. Note your **S3 Endpoint URL** and **Region**.
5. Click **New Access Key** to generate your S3 credentials. Save the **Access Key ID** and **Secret Access Key**.

---

## Phase 2: Railway Setup

### 1. Create a Railway Project
1. Log in to [Railway](https://railway.app/).
2. Click **New Project** -> **Deploy from GitHub repo**.
3. Select your Order-Flow repository.
4. Railway will automatically detect the `railway.json` file and create your main **Web** service.

### 2. Add Redis
1. In your Railway project, click **New** -> **Database** -> **Add Redis**.
2. Railway will automatically provision a Redis instance.

### 3. Configure Environment Variables for Web Service
Select your GitHub repository service in Railway, go to the **Variables** tab, and add the following:

**Django Settings:**
- `DJANGO_SETTINGS_MODULE`: `dineflow.settings.prod`
- `APP_NAME`: `Order-Flow`
- `APP_SHORT_NAME`: `OF`
- `SECRET_KEY`: *(Generate a random 50-character string)*
- `ALLOWED_HOSTS`: *(Leave blank initially, Railway domains are auto-added)*
- `CSRF_TRUSTED_ORIGINS`: *(Leave blank initially, Railway domains are auto-added)*

**Database & Redis:**
- `DATABASE_URL`: *(Paste the Supabase Connection Pooling URI from Phase 1)*
- `REDIS_URL`: `${{Redis.REDIS_URL}}` *(Railway will auto-link this)*

**Supabase Storage:**
- `AWS_ACCESS_KEY_ID`: *(From Supabase)*
- `AWS_SECRET_ACCESS_KEY`: *(From Supabase)*
- `AWS_STORAGE_BUCKET_NAME`: *(Name of the bucket you created, e.g., orderflow-media)*
- `AWS_S3_ENDPOINT_URL`: `https://[your-project-ref].supabase.co/storage/v1/s3`
- `AWS_S3_REGION_NAME`: *(e.g., ap-south-1)*

### 4. Create the Celery Worker Service
We need to spin up the background worker from the same repository.
1. Click **New** -> **Deploy from GitHub repo** and select your Order-Flow repository *again*.
2. Go to the new service's **Settings**.
3. Change the service name to **Celery Worker**.
4. Scroll down to **Deploy** -> **Start Command** and set it to:
   `celery -A dineflow worker -l info --concurrency=2`
5. Go to the **Variables** tab -> Click **Shared Variables** (or copy all variables from the Web service into this one).

### 5. Create the Celery Beat Service
We need to spin up the scheduler from the same repository.
1. Click **New** -> **Deploy from GitHub repo** and select your Order-Flow repository *a third time*.
2. Go to the new service's **Settings**.
3. Change the service name to **Celery Beat**.
4. Scroll down to **Deploy** -> **Start Command** and set it to:
   `celery -A dineflow beat -l info`
5. Go to the **Variables** tab -> Copy all variables from the Web service into this one.

---

## Phase 3: Finalizing Deployment

1. **Wait for Builds:** Railway will build the Dockerfile and deploy the containers.
2. **Database Migrations:** Because we configured `railway.json`, Railway will automatically run `python manage.py migrate` as part of the startup command (`startCommand`) before Daphne starts the Web service.
3. **Public Domain:**
   - Go to your main **Web** service.
   - Go to **Settings** -> **Networking**.
   - Click **Generate Domain**. Railway will provide a public `up.railway.app` URL.
   - You can now access your application at this URL! Both HTTP and WebSockets (like the Kitchen Display System) will route through this single domain.

## Troubleshooting

- **Static Files Missing?** Ensure the `Dockerfile` collects static files during the build phase (which it currently does).
- **Media Uploads Failing?** Double-check your Supabase S3 credentials and ensure the bucket is set to "Public".
- **Database Connection Issues?** Ensure you are using the Supabase **Connection Pooling** URL (port 6543), not the direct connection (port 5432).
