import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory
from django.http import HttpResponse, JsonResponse
from django.core.cache import cache

from core.ratelimit import rate_limit

class RateLimitTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    @rate_limit("test_endpoint", limit=2, window=60)
    def dummy_view(self, request):
        return HttpResponse("OK")

    def test_rate_limit_triggers_correctly(self):
        # 1st request
        req1 = self.factory.get("/")
        req1.META["REMOTE_ADDR"] = "1.2.3.4"
        res1 = self.dummy_view(req1)
        self.assertEqual(res1.status_code, 200)

        # 2nd request
        req2 = self.factory.get("/")
        req2.META["REMOTE_ADDR"] = "1.2.3.4"
        res2 = self.dummy_view(req2)
        self.assertEqual(res2.status_code, 200)

        # 3rd request (exceeds limit=2)
        req3 = self.factory.get("/")
        req3.META["REMOTE_ADDR"] = "1.2.3.4"
        res3 = self.dummy_view(req3)
        self.assertEqual(res3.status_code, 429)
        data = json.loads(res3.content)
        self.assertEqual(data["error"], "RATE_LIMITED")

    def test_different_ips_not_limited(self):
        for i in range(5):
            req = self.factory.get("/")
            req.META["REMOTE_ADDR"] = f"10.0.0.{i}"
            res = self.dummy_view(req)
            self.assertEqual(res.status_code, 200)

    @patch("core.ratelimit.cache")
    def test_cache_failure_fails_open(self, mock_cache):
        # Simulate cache backend failure (e.g. Redis down)
        mock_cache.add.side_effect = Exception("Redis connection refused")
        
        req = self.factory.get("/")
        req.META["REMOTE_ADDR"] = "1.2.3.4"
        
        # Should not raise UnboundLocalError or Exception, but fail open
        res = self.dummy_view(req)
        self.assertEqual(res.status_code, 200)

    def test_no_unbound_local_error(self):
        req = self.factory.get("/")
        req.META["REMOTE_ADDR"] = "1.2.3.4"
        try:
            self.dummy_view(req)
        except UnboundLocalError:
            self.fail("UnboundLocalError occurred due to shadow import")
