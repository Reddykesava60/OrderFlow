# dineflow/settings/test.py
import os

os.environ.setdefault('SECRET_KEY', 'test-only-secret-key-not-for-production-1234567890')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from .base import *

DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
    'core.hashers.CustomerPINHasher',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    },
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'dineflow-tests',
    },
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

PAYMENT_JOBS_INLINE = True
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'

STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
STORAGES = {
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

# Razorpay — placeholder values for the test suite.
# These are never sent to Razorpay; they prevent credential-guard
# exceptions when payment service classes are instantiated in tests.
RAZORPAY_KEY_ID     = 'test-key-id-not-real'
RAZORPAY_KEY_SECRET = 'test-key-secret-not-real'
RAZORPAY_WEBHOOK_SECRET = 'test-webhook-secret-not-real'
