from django.views.generic import TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.cache import cache
from django.conf import settings
import time

class KDSMetricsDashboardView(UserPassesTestMixin, TemplateView):
    template_name = "core/kds_metrics.html"
    
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_superuser

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Read scalar metrics
        total_requests = cache.get("kds_metrics_requests_total", 0)
        cache_hits = cache.get("kds_metrics_cache_hits", 0)
        cache_misses = cache.get("kds_metrics_cache_misses", 0)
        stale_served = cache.get("kds_metrics_stale_served", 0)
        rate_limit_hits = cache.get("kds_metrics_rate_limit_hits", 0)
        rebuild_ms = cache.get("kds_metrics_payload_rebuild_ms", 0)
        
        # Calculate ratios
        total_cache_ops = cache_hits + cache_misses
        hit_ratio = round((cache_hits / total_cache_ops * 100), 2) if total_cache_ops > 0 else 0
        miss_ratio = round((cache_misses / total_cache_ops * 100), 2) if total_cache_ops > 0 else 0
        
        # Get active screens and restaurants using native Redis client if available
        active_restaurants = 0
        active_screens = 0
        
        redis_url = getattr(settings, "REDIS_URL", None)
        if redis_url:
            import redis
            try:
                client = redis.from_url(redis_url)
                now = int(time.time())
                cutoff = now - 60  # Consider active if seen in last 60 seconds
                
                # Count active restaurants
                active_restaurants = client.zcount("kds_active_restaurants", cutoff, "+inf")
                
                # Count active screens across all restaurants (scan keys starting with kds_screens_)
                # Note: Scanning is acceptable here since this is a low-traffic admin dashboard
                for key in client.scan_iter("kds_screens_*"):
                    active_screens += client.zcount(key, cutoff, "+inf")
            except Exception as e:
                # Fallback on error (e.g. redis not running locally)
                pass

        context.update({
            "total_requests": total_requests,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "stale_served": stale_served,
            "rate_limit_hits": rate_limit_hits,
            "rebuild_ms": rebuild_ms,
            "hit_ratio": hit_ratio,
            "miss_ratio": miss_ratio,
            "active_restaurants": active_restaurants,
            "active_screens": active_screens,
        })
        return context
