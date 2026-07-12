# dineflow/settings/dev.py
from .base import *

DEBUG = True
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

# Relaxed CSP in dev — Razorpay domains added in prod
SECURE_SSL_REDIRECT = False

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in config('CSRF_TRUSTED_ORIGINS', default='https://*.trycloudflare.com').split(',')
    if origin.strip()
]

# ── Dev/Prod Parity: Use Redis if available (e.g. via Docker Compose) ──
REDIS_URL = config('REDIS_URL', default='')
if REDIS_URL and 'railway.internal' not in REDIS_URL:
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