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

from decimal import Decimal
from core.models import Restaurant, MerchantLedgerBalance, JournalEntry, JournalLine
from core.ledger import LedgerService, LedgerError
from ordering.models import Order
from django.utils import timezone

class TestLedger(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name="Ledger Test Rest")
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            total=Decimal('100.00'),
            status=Order.Status.PENDING,
            created_at=timezone.now()
        )

    def test_unbalanced_entry_raises_error(self):
        lines = [
            {'account_type': JournalLine.AccountType.ASSET_CASH_IN_TRANSIT, 'amount': Decimal('100.00')},
            {'account_type': JournalLine.AccountType.REVENUE_PLATFORM_FEE, 'amount': Decimal('-10.00')},
            # Missing -90.00 credit to balance
        ]
        with self.assertRaises(LedgerError):
            LedgerService._create_journal_entry(
                restaurant=self.restaurant,
                reference_id="TEST_1",
                entry_type=JournalEntry.EntryType.MANUAL_ADJUSTMENT,
                lines=lines
            )

    def test_payment_capture_creates_balanced_entry(self):
        LedgerService.record_payment_capture(
            order=self.order,
            gross_amount=Decimal('100.00'),
            fee_amount=Decimal('2.50'),
            reference_id=f"PAYMENT_{self.order.id}"
        )

        entry = JournalEntry.objects.get(reference_id=f"PAYMENT_{self.order.id}")
        lines = entry.lines.all()
        self.assertEqual(lines.count(), 3)
        total = sum(l.amount for l in lines)
        self.assertEqual(total, Decimal('0.00'))

        balance = MerchantLedgerBalance.objects.get(restaurant=self.restaurant)
        self.assertEqual(balance.available_balance, Decimal('97.50'))

    def test_refund_reverses_balance(self):
        # Initial capture
        LedgerService.record_payment_capture(
            order=self.order,
            gross_amount=Decimal('100.00'),
            fee_amount=Decimal('2.50'),
            reference_id=f"PAYMENT_{self.order.id}"
        )
        # Refund
        LedgerService.record_refund(
            order=self.order,
            amount=Decimal('100.00'),
            fee_refunded=Decimal('2.50')
        )

        balance = MerchantLedgerBalance.objects.get(restaurant=self.restaurant)
        self.assertEqual(balance.available_balance, Decimal('0.00'))


from core.templatetags.menu_extras import jsonify


class JsonifyFilterTests(TestCase):
    """Ensure the jsonify template filter escapes HTML-dangerous characters."""

    def test_script_tag_breakout_is_escaped(self):
        """A value containing </script> must not produce a literal closing tag."""
        malicious = '</script><script>alert(1)</script>'
        result = str(jsonify(malicious))
        self.assertNotIn('</script>', result)
        self.assertNotIn('<script>', result)
        # The output must still be valid JSON that decodes to the original value
        self.assertEqual(json.loads(result), malicious)

    def test_ampersand_is_escaped(self):
        result = str(jsonify('a&b'))
        self.assertNotIn('&', result)
        self.assertEqual(json.loads(result), 'a&b')

    def test_angle_brackets_are_escaped(self):
        result = str(jsonify('<b>bold</b>'))
        self.assertNotIn('<', result)
        self.assertNotIn('>', result)
        self.assertEqual(json.loads(result), '<b>bold</b>')

    def test_normal_string_round_trips(self):
        value = "Chicken Biryani (Large)"
        result = str(jsonify(value))
        self.assertEqual(json.loads(result), value)

    def test_dict_with_special_chars(self):
        value = {'name': 'Tom & Jerry <Special>', 'price': 100}
        result = str(jsonify(value))
        self.assertNotIn('&', result)
        self.assertNotIn('<', result)
        self.assertEqual(json.loads(result), value)
