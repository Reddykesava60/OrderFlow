# dineflow/settings/prod.py
from .base import *
from django.core.exceptions import ImproperlyConfigured
from urllib.parse import urlparse


def _csv_config(name, *, required=True):
    value = config(name) if required else config(name, default='')
    return [item.strip() for item in value.split(',') if item.strip()]


def _reject_placeholder_list(name, values):
    forbidden = {'*', 'localhost', '127.0.0.1', '0.0.0.0'}
    bad = [value for value in values if value.lower() in forbidden]
    if bad:
        raise ImproperlyConfigured(
            f'{name} contains non-production host values: {", ".join(bad)}'
        )

DEBUG = False
ALLOWED_HOSTS = _csv_config('ALLOWED_HOSTS', required=False)
if config('RAILWAY_PUBLIC_DOMAIN', default=''):
    ALLOWED_HOSTS.append(config('RAILWAY_PUBLIC_DOMAIN'))
# Railway's health checker sends requests with this Host header
ALLOWED_HOSTS.append('healthcheck.railway.app')

# Filter out placeholder values rather than crashing (dev values may leak in)
_forbidden_hosts = {'*', 'localhost', '127.0.0.1', '0.0.0.0'}
_bad_hosts = [h for h in ALLOWED_HOSTS if h.lower() in _forbidden_hosts]
if _bad_hosts:
    import logging
    logging.getLogger('dineflow.settings').warning(
        'Stripping non-production ALLOWED_HOSTS values: %s', ', '.join(_bad_hosts)
    )
    ALLOWED_HOSTS = [h for h in ALLOWED_HOSTS if h.lower() not in _forbidden_hosts]

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        'ALLOWED_HOSTS must not be empty in production. '
        'Set ALLOWED_HOSTS in Railway variables (e.g. your-app.up.railway.app) '
        'or ensure RAILWAY_PUBLIC_DOMAIN is available.'
    )


if SECRET_KEY.startswith('django-insecure-') or len(set(SECRET_KEY)) < 20 or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured('Production SECRET_KEY must be strong and must not be committed.')

REDIS_URL = config('REDIS_URL', default='')

if REDIS_URL:
    redis_url = urlparse(REDIS_URL)
    if redis_url.scheme not in ('redis', 'rediss'):
        raise ImproperlyConfigured('REDIS_URL must use redis:// or rediss://.')
    if redis_url.hostname in ('redis', 'localhost', '127.0.0.1') and not redis_url.password:
        raise ImproperlyConfigured('Self-hosted production Redis must require a password.')

    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'TIMEOUT': 300,
        },
    }

    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [REDIS_URL],
            },
        },
    }
else:
    # Fallback for pre-deploy / migrations (Redis not yet available)
    import logging
    logging.getLogger('dineflow.settings').warning(
        'REDIS_URL not set — using in-memory cache and channel layer. '
        'This is acceptable during migrations but not for runtime.'
    )
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        },
    }
    # CHANNEL_LAYERS stays as InMemoryChannelLayer from base.py


# Railway handles SSL termination at the proxy layer and sends
# X-Forwarded-Proto headers. Internal health checks arrive over HTTP,
# so SECURE_SSL_REDIRECT would cause 301 loops for the health checker.
SECURE_SSL_REDIRECT = not config('RAILWAY_ENVIRONMENT', default='')
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=False, cast=bool)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = _csv_config('CSRF_TRUSTED_ORIGINS', required=False)
if config('RAILWAY_PUBLIC_DOMAIN', default=''):
    CSRF_TRUSTED_ORIGINS.append(f"https://{config('RAILWAY_PUBLIC_DOMAIN')}")
# Filter out non-https origins instead of crashing
_bad_origins = [o for o in CSRF_TRUSTED_ORIGINS if not o.startswith('https://')]
if _bad_origins:
    import logging
    logging.getLogger('dineflow.settings').warning(
        'Stripping non-https CSRF_TRUSTED_ORIGINS: %s', ', '.join(_bad_origins)
    )
    CSRF_TRUSTED_ORIGINS = [o for o in CSRF_TRUSTED_ORIGINS if o.startswith('https://')]

# ── Supabase S3 Storage ──────────────────────────────────────────────────────
# Railway ephemeral disk means media must be stored externally.
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default='')
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default='')
AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default='')
AWS_S3_ENDPOINT_URL = config('AWS_S3_ENDPOINT_URL', default='')
AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='')

if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_STORAGE_BUCKET_NAME and AWS_S3_ENDPOINT_URL:
    STORAGES['default'] = {
        'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
    }
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = 'public-read'
    AWS_S3_SIGNATURE_VERSION = 's3v4'
else:
    import logging
    logging.getLogger('dineflow.settings').warning(
        'AWS/Supabase S3 credentials are not fully configured. '
        'Media uploads will use local filesystem (ephemeral on Railway). '
        'Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME, '
        'and AWS_S3_ENDPOINT_URL for persistent media storage.'
    )

# ── Error notifications ──────────────────────────────────────────────────────
SERVER_EMAIL = config('SERVER_EMAIL', default='noreply@order-flow.app')
ADMINS = [
    (name.strip(), email.strip())
    for entry in config('ADMINS', default='').split(';')
    if ',' in entry
    for name, email in [entry.split(',', 1)]
]

# ── Production logging (structured JSON for log aggregation) ─────────────────
LOGGING['formatters']['json'] = {
    '()': 'django.utils.log.ServerFormatter',
    'format': '{asctime} {levelname} {name} {message}',
    'style': '{',
}
# Set all app loggers to use verbose format with timestamps
for logger_name in ('ordering', 'kitchen', 'core', 'owner'):
    if logger_name in LOGGING['loggers']:
        LOGGING['loggers'][logger_name]['level'] = 'INFO'

# Ensure django.request logs at WARNING in production for visibility
LOGGING['loggers']['django.request']['level'] = 'WARNING'

# ── Celery Configuration ─────────────────────────────────────────────────────
if REDIS_URL:
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE if 'TIME_ZONE' in locals() else 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Optimize for fairness in long-running tasks like payments
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000  # Prevent memory leaks over time
PAYMENT_JOBS_INLINE = not REDIS_URL  # Inline if no broker available


CELERY_BEAT_SCHEDULE = {
    'release-expired-reservations-every-5-minutes': {
        'task': 'ordering.payments.jobs.release_expired_reservations_task',
        'schedule': 300.0,
    },
    'expire-pending-payments-every-5-minutes': {
        'task': 'ordering.payments.jobs.expire_pending_payments_task',
        'schedule': 300.0,
    },
    'process-unprocessed-webhooks-every-minute': {
        'task': 'ordering.payments.jobs.process_unprocessed_webhooks_task',
        'schedule': 60.0,
    },
    'reconcile-recent-payments-every-15-minutes': {
        'task': 'ordering.payments.jobs.reconcile_recent_payments_task',
        'schedule': 900.0,
    },
    'sync-monthly-statements-hourly': {
        'task': 'ordering.payments.jobs.sync_monthly_statements_task',
        'schedule': 3600.0,
    },
}
