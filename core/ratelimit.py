import functools
import hashlib
import logging

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render

logger = logging.getLogger(__name__)


def client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def rate_limit(name, *, limit, window, key_func=None):
    """
    Cache-backed throttle for high-risk endpoints.

    Production must use the shared Redis cache configured in settings.prod.
    Development falls back to Django's local memory cache.
    """

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapped(*args, **kwargs):
            request = next(
                (arg for arg in args if hasattr(arg, "META") and hasattr(arg, "method")),
                None,
            )
            if request is None:
                return view_func(*args, **kwargs)
            raw_key = key_func(request, *args[2:], **kwargs) if key_func else client_ip(request)
            digest = hashlib.sha256(str(raw_key).encode("utf-8")).hexdigest()[:32]
            cache_key = f"rl:{name}:{digest}"

            try:
                if cache.add(cache_key, 1, timeout=window):
                    return view_func(*args, **kwargs)
                count = cache.incr(cache_key)
            except Exception:
                logger.exception("Rate limiter failed open for %s", name)
                return view_func(*args, **kwargs)

            if count > limit:
                logger.info("metric kds_rate_limit_hits 1 endpoint=%s ip=%s", name, client_ip(request))
                try:
                    cache.incr("kds_metrics_rate_limit_hits")
                except ValueError:
                    cache.set("kds_metrics_rate_limit_hits", 1, timeout=None)
                
                accepts = request.META.get('HTTP_ACCEPT', '')
                if 'text/html' in accepts:
                    response = render(request, '429.html', status=429)
                else:
                    response = JsonResponse(
                        {
                            "error": "RATE_LIMITED",
                            "message": "Too many requests. Please try again shortly.",
                        },
                        status=429,
                    )
                response["Retry-After"] = str(window)
                return response

            return view_func(*args, **kwargs)

        return wrapped

    return decorator
