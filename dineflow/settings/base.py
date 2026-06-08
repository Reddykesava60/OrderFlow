# dineflow/settings/base.py
import dj_database_url
from decouple import config
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config('SECRET_KEY')
PAYMENT_ENCRYPTION_KEY = config('PAYMENT_ENCRYPTION_KEY', default=SECRET_KEY)

APP_NAME = config('APP_NAME', default='Order-Flow')
APP_SHORT_NAME = config('APP_SHORT_NAME', default='OF')
APP_TAGLINE = config('APP_TAGLINE', default='Restaurant order operations')

# Test runner heuristic (keeps certain safety rails from breaking unit tests).
TESTING = 'test' in sys.argv

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # our apps
    'core',
    'ordering',
    'kitchen',
    'owner',
    'channels',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'core.middleware.SecurityHeadersMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # serves static in prod
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.MustChangePasswordMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'dineflow.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],   # global templates folder
    'APP_DIRS': True,                   # also loads app/templates/
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
            'core.context_processors.app_brand',
        ],
    },
}]

WSGI_APPLICATION = 'dineflow.wsgi.application'
ASGI_APPLICATION = 'dineflow.asgi.application'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

# Payment webhook jobs run through Celery in deployed environments. Tests run
# them inline so webhook behavior stays deterministic without a broker.
PAYMENT_JOBS_INLINE = True if TESTING else config('PAYMENT_JOBS_INLINE', default=False, cast=bool)

# ── Database ────────────────────────────────────────────────────────────────
default_db = dj_database_url.config(
    default=config('DATABASE_URL'),
    conn_max_age=600,
    conn_health_checks=True,
)
if 'postgresql' in default_db.get('ENGINE', '') and not TESTING:
    default_db.setdefault('OPTIONS', {})
    default_db['OPTIONS'].setdefault(
        'sslmode',
        config('DB_SSLMODE', default='require'),
    )

DATABASES = {
    'default': default_db,
}

# ── Auth ────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'core.User'  # our custom user — must be set before first migration

LOGIN_URL = '/owner/login/'
LOGIN_REDIRECT_URL = '/api/kds/'
LOGOUT_REDIRECT_URL = '/owner/login/'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.ScryptPasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
    'core.hashers.CustomerPINHasher',
]

# ── Internationalisation ────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'     # IST — important for daily order counter resets
USE_I18N = True
USE_TZ = True

# ── Static & media ──────────────────────────────────────────────────────────
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'   # collectstatic target
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# Reverse proxy support (Nginx sets X-Forwarded-Proto)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

MEDIA_URL  = config('MEDIA_URL', default='/media/')
MEDIA_ROOT = BASE_DIR / config('MEDIA_ROOT', default='media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Sessions ────────────────────────────────────────────────────────────────
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 28800           # 8 hours (SEC-13)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'

DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ── Security headers (SEC-11, SEC-12) ────────────────────────────────────────
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
PERMISSIONS_POLICY = config(
    'PERMISSIONS_POLICY',
    default='camera=(), microphone=(), geolocation=(), usb=()',
)
CONTENT_SECURITY_POLICY_REPORT_ONLY = config('CONTENT_SECURITY_POLICY_REPORT_ONLY', default=True, cast=bool)
CONTENT_SECURITY_POLICY = config(
    'CONTENT_SECURITY_POLICY',
    default=(
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://checkout.razorpay.com https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
        "connect-src 'self' https://api.razorpay.com wss:; "
        "frame-src https://api.razorpay.com https://checkout.razorpay.com"
    ),
)

# ── Razorpay ────────────────────────────────────────────────────────────────
# Platform-level Razorpay credentials (Single Platform Account).
# All restaurants use these by default unless they have their own config.
RAZORPAY_KEY_ID        = config('RAZORPAY_KEY_ID', default='')
RAZORPAY_KEY_SECRET    = config('RAZORPAY_KEY_SECRET', default='')
RAZORPAY_WEBHOOK_SECRET = config('RAZORPAY_WEBHOOK_SECRET', default='')
RAZORPAY_ENV           = config('RAZORPAY_ENV', default='sandbox')  # sandbox | production

# ── Supabase (Storage + optional future Auth/RLS) ─────────────────────────────
# Database connectivity uses DATABASE_URL above (Supabase pooler URL in prod).
SUPABASE_URL = config('SUPABASE_URL', default='')
SUPABASE_SERVICE_KEY = config('SUPABASE_SERVICE_KEY', default='')  # service_role (server-side only)

# ── Logging ─────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {name} {module}:{lineno} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'ordering': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'kitchen': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'core': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'owner': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
