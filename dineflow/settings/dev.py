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