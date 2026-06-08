import logging

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.http import JsonResponse
from django.shortcuts import render

logger = logging.getLogger('order_flow.health')


def landing(request):
    return render(request, 'landing.html')


def custom_404(request, exception):
    return render(request, '404.html', status=404)


def health_live(request):
    return JsonResponse({'status': 'ok'})


def health_ready(request):
    checks = {}
    status = 200

    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        checks['database'] = 'ok'
    except Exception as e:
        checks['database'] = 'error'
        if settings.DEBUG:
            checks['database_detail'] = str(e)
        logger.error('Health check: database failed: %s', e)
        status = 503

    try:
        cache.set('health:ready', 'ok', timeout=5)
        checks['cache'] = 'ok' if cache.get('health:ready') == 'ok' else 'error'
        if checks['cache'] != 'ok':
            status = 503
    except Exception as e:
        checks['cache'] = 'error'
        if settings.DEBUG:
            checks['cache_detail'] = str(e)
        logger.error('Health check: cache/redis failed: %s', e)
        status = 503

    return JsonResponse(
        {'status': 'ok' if status == 200 else 'error', 'checks': checks},
        status=status,
    )

