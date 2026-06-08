from decimal import Decimal
import hashlib
import hmac
import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import MenuItem, PlatformSettings, Restaurant
from core.models import PlatformFeeRecord
from kitchen.models import PaymentEvent

from .models import Order, PaymentState, PaymentTransaction, WebhookLog
from .payments.services import get_payment_access_token
from .services import (
    CartError,
    PaymentConfigurationError,
    confirm_cash_payment,
    expire_overdue_unpaid_cash_orders,
    get_restaurant_payment_config,
    place_cash_order,
    place_upi_order,
)


class CashTimeoutTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Timeout Test', slug='timeout-test')
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            name='Idli',
            base_price=Decimal('40.00'),
            stock=10,
        )
        self.user = get_user_model().objects.create_user(
            username='cashier',
            password='pass1234',
            role='STAFF',
            restaurant=self.restaurant,
            allow_cash_collection=True,
        )

        settings_obj = PlatformSettings.get_solo()
        settings_obj.cash_payment_timeout_minutes = 10
        settings_obj.save(update_fields=['cash_payment_timeout_minutes'])

    def _place_cash_order(self):
        return place_cash_order(
            self.restaurant,
            cart_lines=[
                {
                    'item_id': str(self.item.id),
                    'quantity': 1,
                    'dining_option': 'DINE_IN',
                    'addons': [],
                }
            ],
            customer_name='Alice',
            table_number='A1',
        )

    def test_expire_overdue_cash_order_changes_status_and_restores_stock(self):
        order = self._place_cash_order()
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 9)

        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timezone.timedelta(minutes=11)
        )

        expired_count = expire_overdue_unpaid_cash_orders(restaurant=self.restaurant)
        self.assertEqual(expired_count, 1)

        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.item.stock, 10)
        self.assertTrue(
            PaymentEvent.objects.filter(
                order=order,
                event_type=PaymentEvent.EventType.PAYMENT_TIMEOUT,
            ).exists()
        )

    def test_confirm_cash_payment_fails_after_timeout_and_marks_order_cancelled(self):
        order = self._place_cash_order()
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timezone.timedelta(minutes=11)
        )
        order.refresh_from_db()

        with self.assertRaises(CartError) as ctx:
            confirm_cash_payment(order, self.user)

        self.assertEqual(ctx.exception.code, 'PAYMENT_TIMEOUT')
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)


class PlatformFeePolicyTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Fee Test', slug='fee-test')
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            name='Pongal',
            base_price=Decimal('80.00'),
            stock=10,
        )
        self.user = get_user_model().objects.create_user(
            username='collector',
            password='pass1234',
            role='STAFF',
            restaurant=self.restaurant,
            allow_cash_collection=True,
        )

    def test_fixed_platform_fee_used_for_confirmed_cash_payment(self):
        settings_obj = PlatformSettings.get_solo()
        settings_obj.platform_fee_mode = PlatformSettings.FeeMode.FIXED
        settings_obj.platform_fee_fixed_amount = Decimal('12.00')
        settings_obj.platform_fee_percent = Decimal('3.00')
        settings_obj.save(update_fields=['platform_fee_mode', 'platform_fee_fixed_amount', 'platform_fee_percent'])

        order = place_cash_order(
            self.restaurant,
            cart_lines=[
                {
                    'item_id': str(self.item.id),
                    'quantity': 1,
                    'dining_option': 'DINE_IN',
                    'addons': [],
                }
            ],
            customer_name='Ravi',
            table_number='C3',
        )

        confirm_cash_payment(order, self.user)
        fee_record = PlatformFeeRecord.objects.get(order=order)

        self.assertEqual(fee_record.fee_amount, Decimal('12.00'))


class TestUpiWebhook(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='UPI Test', slug='upi-test')
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            name='Dosa',
            base_price=Decimal('90.00'),
            stock=10,
        )
        payment_config = self.restaurant.payment_config
        payment_config.razorpay_key_id = 'rzp_test_example123456'
        payment_config.razorpay_key_secret = 'test_secret_123'
        payment_config.razorpay_webhook_secret = 'whsec_test_123'
        payment_config.is_active = True
        payment_config.save()

    def _place_upi_order(self):
        order = place_upi_order(
            self.restaurant,
            cart_lines=[
                {
                    'item_id': str(self.item.id),
                    'quantity': 1,
                    'dining_option': 'DINE_IN',
                    'addons': [],
                }
            ],
            customer_name='Meena',
            table_number='B2',
        )
        Order.objects.filter(pk=order.pk).update(razorpay_order_id='order_test_123')
        order.refresh_from_db()
        return order

    def _signature_header(self, body):
        signature = hmac.new(
            self.restaurant.payment_config.razorpay_webhook_secret.encode('utf-8'),
            body,
            hashlib.sha256,
        ).hexdigest()
        return {'HTTP_X_RAZORPAY_SIGNATURE': signature}

    def test_payment_captured_webhook_confirms_order(self):
        order = self._place_upi_order()

        payload = {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_test_123',
                        'order_id': order.razorpay_order_id,
                        'amount': 9000,
                    }
                }
            },
        }
        body = json.dumps(payload).encode('utf-8')

        response = self.client.post(
            '/payments/razorpay/webhook/',
            data=body,
            content_type='application/json',
            **self._signature_header(body),
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.razorpay_payment_id, 'pay_test_123')
        self.assertTrue(
            PaymentEvent.objects.filter(
                order=order,
                event_type=PaymentEvent.EventType.RAZORPAY_CONFIRMED,
                razorpay_payment_id='pay_test_123',
            ).exists()
        )

    def test_invalid_webhook_signature_is_rejected(self):
        order = self._place_upi_order()

        payload = {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_bad_sig',
                        'order_id': order.razorpay_order_id,
                        'amount': 9000,
                    }
                }
            },
        }
        body = json.dumps(payload).encode('utf-8')

        response = self.client.post(
            '/payments/razorpay/webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='bad_signature',
        )

        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.UNPAID)

    def test_duplicate_webhook_event_is_processed_once(self):
        order = self._place_upi_order()

        payload = {
            'id': 'evt_test_123',
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_test_123',
                        'order_id': order.razorpay_order_id,
                        'amount': 9000,
                    }
                },
                'order': {
                    'entity': {
                        'id': order.razorpay_order_id,
                    }
                },
            },
        }
        body = json.dumps(payload).encode('utf-8')
        signature = hmac.new(
            self.restaurant.payment_config.razorpay_webhook_secret.encode('utf-8'),
            body,
            hashlib.sha256,
        ).hexdigest()

        for _ in range(2):
            response = self.client.post(
                '/payments/razorpay/webhook/',
                data=body,
                content_type='application/json',
                HTTP_X_RAZORPAY_SIGNATURE=signature,
            )
            self.assertEqual(response.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(
            PaymentEvent.objects.filter(
                order=order,
                event_type=PaymentEvent.EventType.RAZORPAY_CONFIRMED,
                razorpay_payment_id='pay_test_123',
            ).count(),
            1,
        )
        self.assertEqual(
            PaymentEvent.objects.filter(
                order=order,
                event_type=PaymentEvent.EventType.RAZORPAY_INITIATED,
                razorpay_payment_id='pay_test_123',
            ).count(),
            1,
        )
        self.assertEqual(
            WebhookLog.objects.filter(
                restaurant=self.restaurant,
                provider='razorpay',
            ).count(),
            1,
        )


class TestPaymentAccessToken(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Token Test', slug='token-test')
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            name='Pongal',
            base_price=Decimal('50.00'),
            stock=10,
        )

    def test_payment_status_requires_signed_token(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            order_number=1,
            customer_name='Asha',
            table_number='T1',
            payment_method=Order.PaymentMethod.UPI,
            status=Order.Status.UNPAID,
            total=Decimal('50.00'),
        )
        payment = PaymentTransaction.objects.create(
            restaurant=self.restaurant,
            order=order,
            provider='razorpay',
            state=PaymentState.PENDING,
            amount=Decimal('50.00'),
            currency='INR',
            provider_order_id='order_token_123',
        )

        response = self.client.get(f'/payments/status/{payment.id}/')
        self.assertEqual(response.status_code, 403)

        token = get_payment_access_token(payment)
        response = self.client.get(f'/payments/status/{payment.id}/?token={token}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['payment_id'], str(payment.id))


class TestRazorpayCredentialMode(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Mode Test', slug='mode-test')
        payment_config = self.restaurant.payment_config
        payment_config.razorpay_key_id = 'rzp_test_example123456'
        payment_config.razorpay_key_secret = 'test_secret_123'
        payment_config.razorpay_webhook_secret = 'whsec_test_123'
        payment_config.is_active = True
        payment_config.save()

    @override_settings(DEBUG=False)
    def test_test_credentials_rejected_in_production_mode(self):
        with self.assertRaises(PaymentConfigurationError):
            get_restaurant_payment_config(self.restaurant)
