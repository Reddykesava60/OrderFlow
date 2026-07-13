from decimal import Decimal
import hashlib
import hmac
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import MenuItem, PlatformSettings, Restaurant
from core.models import PlatformFeeRecord
from kitchen.models import PaymentEvent

from .models import Order, OrderItem, PaymentState, PaymentTransaction, StockReservation, WebhookLog
from .payments.contracts import ProviderWebhookEvent
from .payments.services import PaymentMutationService, WebhookIngestionService
from .payments.services import get_payment_access_token
from .checkout.services import CartError, PaymentConfigurationError, get_restaurant_payment_config, place_cash_order, place_upi_order
from .orders.services import confirm_cash_payment, expire_overdue_unpaid_cash_orders


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

    def test_hybrid_platform_fee_used_for_confirmed_cash_payment(self):
        settings_obj = PlatformSettings.get_solo()
        settings_obj.platform_fee_mode = PlatformSettings.FeeMode.HYBRID
        settings_obj.platform_fee_fixed_amount = Decimal('2.00')
        settings_obj.platform_fee_percent = Decimal('5.00')
        settings_obj.save(update_fields=['platform_fee_mode', 'platform_fee_fixed_amount', 'platform_fee_percent'])

        order = place_cash_order(
            self.restaurant,
            cart_lines=[
                {
                    'item_id': str(self.item.id),
                    'quantity': 2, # Total = 2 * 12.50 = 25.00
                    'dining_option': 'DINE_IN',
                    'addons': [],
                }
            ],
            customer_name='Ankit',
            table_number='T1',
        )

        confirm_cash_payment(order, self.user)
        fee_record = PlatformFeeRecord.objects.get(order=order)
        
        # 5% of 25.00 = 1.25. Fixed = 2.00. Total = 3.25.
        self.assertEqual(fee_record.fee_amount, Decimal('3.25'))

    def test_restaurant_custom_fee_override_used_instead_of_platform_settings(self):
        settings_obj = PlatformSettings.get_solo()
        settings_obj.platform_fee_mode = PlatformSettings.FeeMode.FIXED
        settings_obj.platform_fee_fixed_amount = Decimal('12.00')
        settings_obj.platform_fee_percent = Decimal('3.00')
        settings_obj.save(update_fields=['platform_fee_mode', 'platform_fee_fixed_amount', 'platform_fee_percent'])

        # Set custom fee override on restaurant to HYBRID, 4.00%, 1.00 fixed
        self.restaurant.custom_fee_mode = PlatformSettings.FeeMode.HYBRID
        self.restaurant.custom_fee_percent = Decimal('4.00')
        self.restaurant.custom_fee_fixed_amount = Decimal('1.00')
        self.restaurant.save(update_fields=['custom_fee_mode', 'custom_fee_percent', 'custom_fee_fixed_amount'])

        order = place_cash_order(
            self.restaurant,
            cart_lines=[
                {
                    'item_id': str(self.item.id),
                    'quantity': 1,  # 12.50
                    'dining_option': 'DINE_IN',
                    'addons': [],
                }
            ],
            customer_name='Ravi',
            table_number='C3',
        )

        confirm_cash_payment(order, self.user)
        fee_record = PlatformFeeRecord.objects.get(order=order)

        # 4% of 12.50 = 0.50. Fixed = 1.00. Total = 1.50
        self.assertEqual(fee_record.fee_amount, Decimal('1.50'))


class TestUpiWebhook(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='UPI Test', slug='upi-test')
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            name='Dosa',
            base_price=Decimal('90.00'),
            stock=10,
        )
        from ordering.models import TenantPaymentConfig, PaymentProvider
        payment_config = TenantPaymentConfig.objects.create(
            restaurant=self.restaurant,
            provider=PaymentProvider.RAZORPAY,
            is_active=True
        )
        payment_config.set_credentials({
            'key_id': 'test_key_example123456',
            'key_secret': 'test_secret_123'
        })
        payment_config.set_webhook_secret('whsec_test_123')
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
            b'whsec_test_123',
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
            b'whsec_test_123',
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
        from ordering.models import TenantPaymentConfig, PaymentProvider
        payment_config = TenantPaymentConfig.objects.create(
            restaurant=self.restaurant,
            provider=PaymentProvider.RAZORPAY,
            mode='test',
            is_active=True
        )
        payment_config.set_credentials({
            'key_id': 'rzp_test_example123456',
            'key_secret': 'test_secret_123'
        })
        payment_config.set_webhook_secret('whsec_test_123')
        payment_config.save()

    @override_settings(DEBUG=False, TESTING=False)
    def test_test_credentials_rejected_in_production_mode(self):
        with self.assertRaises(PaymentConfigurationError):
            get_restaurant_payment_config(self.restaurant)


class TestUpiPaymentRecovery(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Recovery Test', slug='recovery-test')
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            name='Dosa',
            base_price=Decimal('90.00'),
            stock=10,
        )
        from ordering.models import TenantPaymentConfig, PaymentProvider
        payment_config = TenantPaymentConfig.objects.create(
            restaurant=self.restaurant,
            provider=PaymentProvider.RAZORPAY,
            is_active=True
        )
        payment_config.set_credentials({
            'key_id': 'test_key_example123456',
            'key_secret': 'test_secret_123'
        })
        payment_config.set_webhook_secret('whsec_test_123')
        payment_config.save()

    @patch('razorpay.Client')
    @patch('requests.get')
    def test_reconciliation_recovers_missing_webhook_and_frontend_verify(self, mock_get, mock_razorpay):
        # Setup razorpay create mock
        mock_client = mock_razorpay.return_value
        mock_client.order.create.return_value = {'id': 'order_test_recovery_123'}

        # 1 & 2 & 3: Place UPI order and create razorpay order (which now creates PaymentTransaction)
        from ordering.checkout.services import create_razorpay_order
        
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
        create_razorpay_order(order)
        order.refresh_from_db()

        self.assertEqual(order.status, Order.Status.UNPAID)
        self.assertEqual(order.razorpay_order_id, 'order_test_recovery_123')

        # Verify PaymentTransaction was eagerly created
        pt = PaymentTransaction.objects.get(order=order)
        self.assertEqual(pt.state, PaymentState.INITIATED)
        self.assertEqual(pt.provider_order_id, 'order_test_recovery_123')

        # 4 & 5 & 6: Simulate successful payment capture but skip verify/webhook
        # Setup mock for reconciliation polling
        class MockResponse:
            def raise_for_status(self): pass
            def json(self):
                return {
                    'items': [
                        {'status': 'captured', 'id': 'pay_recovery_123', 'amount': 9000}
                    ]
                }
        mock_get.return_value = MockResponse()

        # 7: Run reconciliation task
        from ordering.payments.jobs import reconcile_recent_payments_task
        reconciled_count = reconcile_recent_payments_task(minutes=360, limit=200)
        
        # the task returns the number of reconciled payments
        self.assertEqual(reconciled_count, 1)

        # 8: Verify order becomes paid/pending
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.razorpay_payment_id, 'pay_recovery_123')

        # Verify payment transaction state
        pt.refresh_from_db()
        self.assertEqual(pt.state, PaymentState.PAID)
        self.assertEqual(pt.provider_payment_id, 'pay_recovery_123')

        # Verify ledger entries
        from ordering.models import RestaurantLedger
        ledger_entry = RestaurantLedger.objects.filter(order=order, entry_type='CREDIT_ORDER').first()
        self.assertIsNotNone(ledger_entry)
        self.assertEqual(ledger_entry.amount, Decimal('90.00'))


class TestPaymentJobsSerialization(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Job Test', slug='job-test')
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            order_number=1,
            customer_name='Asha',
            payment_method=Order.PaymentMethod.UPI,
            status=Order.Status.UNPAID,
            total=Decimal('50.00'),
        )
        self.payment = PaymentTransaction.objects.create(
            restaurant=self.restaurant,
            order=self.order,
            provider='razorpay',
            state=PaymentState.PENDING,
            amount=Decimal('50.00'),
            currency='INR',
        )
        self.webhook_log = WebhookLog.objects.create(
            restaurant=self.restaurant,
            payment_transaction=self.payment,
            provider='razorpay',
            payload_hash='hash123',
            raw_payload='{}',
        )

    @patch('ordering.payments.jobs.WebhookIngestionService')
    def test_process_payment_webhook_task_serialization(self, mock_service):
        mock_service.return_value.process_log.return_value = self.webhook_log
        
        from ordering.payments.jobs import process_payment_webhook_task
        result = process_payment_webhook_task(self.webhook_log.id)
        # Verify JSON serializable
        try:
            json.dumps(result)
        except TypeError as e:
            self.fail(f"process_payment_webhook_task result is not JSON serializable: {e}")
        self.assertEqual(result.get('webhook_log_id'), str(self.webhook_log.id))

    @patch('ordering.payments.jobs.PaymentVerificationService')
    def test_verify_payment_task_serialization(self, mock_service):
        mock_service.return_value.verify_payment.return_value = self.payment
        
        from ordering.payments.jobs import verify_payment_task
        result = verify_payment_task(self.payment.id)
        # Verify JSON serializable
        try:
            json.dumps(result)
        except TypeError as e:
            self.fail(f"verify_payment_task result is not JSON serializable: {e}")
        self.assertEqual(result.get('payment_transaction_id'), str(self.payment.id))

    @patch('ordering.payments.jobs.PaymentReconciliationService')
    def test_reconcile_payment_task_serialization(self, mock_service):
        mock_service.return_value.reconcile_payment.return_value = self.payment
        
        from ordering.payments.jobs import reconcile_payment_task
        result = reconcile_payment_task(self.payment.id)
        # Verify JSON serializable
        try:
            json.dumps(result)
        except TypeError as e:
            self.fail(f"reconcile_payment_task result is not JSON serializable: {e}")
        self.assertEqual(result.get('payment_transaction_id'), str(self.payment.id))


class TestUpiPaymentStateIntegrity(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Integrity Test', slug='integrity-test')
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            name='Dosa',
            base_price=Decimal('90.00'),
            stock=10,
        )
        from ordering.models import TenantPaymentConfig, PaymentProvider
        payment_config = TenantPaymentConfig.objects.create(
            restaurant=self.restaurant,
            provider=PaymentProvider.RAZORPAY,
            is_active=True
        )
        payment_config.set_credentials({
            'key_id': 'test_key_integrity123',
            'key_secret': 'test_secret_123'
        })
        payment_config.set_webhook_secret('whsec_test_123')
        payment_config.save()

    def _place_reserved_upi_order(self, *, provider_order_id='order_integrity_123'):
        order = place_upi_order(
            self.restaurant,
            cart_lines=[{
                'item_id': str(self.item.id),
                'quantity': 1,
                'dining_option': 'DINE_IN',
                'addons': [],
            }],
            customer_name='Meena',
            table_number='B2',
        )
        Order.objects.filter(pk=order.pk).update(razorpay_order_id=provider_order_id)
        order.refresh_from_db()
        payment = PaymentTransaction.objects.create(
            restaurant=self.restaurant,
            order=order,
            provider='razorpay',
            provider_order_id=provider_order_id,
            state=PaymentState.INITIATED,
            amount=order.total,
            currency='INR',
            expires_at=timezone.now() + timezone.timedelta(minutes=15),
        )
        self.item.refresh_from_db()
        return order, payment

    def _event(self, kind, provider_payment_id='pay_integrity_123'):
        return ProviderWebhookEvent(
            kind=kind,
            provider_order_id='order_integrity_123',
            provider_payment_id=provider_payment_id,
            amount=Decimal('90.00'),
            raw={'source': 'test'},
        )

    def _signed_headers(self, body, event_id=None):
        signature = hmac.new(
            b'whsec_test_123',
            body,
            hashlib.sha256,
        ).hexdigest()
        headers = {'X-Razorpay-Signature': signature}
        if event_id:
            headers['X-Razorpay-Event-Id'] = event_id
        return headers

    def _webhook_payload(self, event_name, provider_order_id='order_integrity_123', provider_payment_id='pay_integrity_123', event_id='evt_integrity_123'):
        return {
            'id': event_id,
            'event': event_name,
            'payload': {
                'payment': {
                    'entity': {
                        'id': provider_payment_id,
                        'order_id': provider_order_id,
                        'amount': 9000,
                    }
                },
                'order': {
                    'entity': {
                        'id': provider_order_id,
                    }
                },
            },
        }

    @patch('ordering.payments.jobs.PaymentReconciliationService')
    def test_payment_timeout_abandoned_upi_flow_restores_stock_once(self, mock_reconciliation):
        # Initial state: UPI order holds one stock unit with an initiated payment.
        order, payment = self._place_reserved_upi_order()
        mock_reconciliation.return_value.reconcile_payment.return_value = payment
        PaymentTransaction.objects.filter(pk=payment.pk).update(
            expires_at=timezone.now() - timezone.timedelta(minutes=1)
        )
        payment.refresh_from_db()

        # Action: scheduled payment expiration runs after the user abandons UPI.
        from ordering.payments.jobs import expire_single_payment_task
        expired = expire_single_payment_task(payment.id)

        # Expected/actual: payment expired, order cancelled, stock restored once.
        self.assertTrue(expired)
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.state, PaymentState.EXPIRED)
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.item.stock, 10)
        self.assertFalse(StockReservation.objects.filter(order=order, is_confirmed=False).exists())

    def test_payment_failed_webhook_cancels_order_and_restores_stock_once(self):
        # Initial state: UPI order stock is held.
        order, payment = self._place_reserved_upi_order()

        # Action: provider reports payment.failed.
        PaymentMutationService().mark_failed(payment, self._event('payment_failed', 'pay_failed_123'))

        # Expected/actual: failure is terminal for the order and inventory is restored.
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.state, PaymentState.FAILED)
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.item.stock, 10)

    def test_payment_captured_webhook_confirms_order_and_keeps_stock_deducted(self):
        # Initial state: UPI order stock is held.
        order, payment = self._place_reserved_upi_order()

        # Action: provider reports payment.captured.
        PaymentMutationService().mark_paid(payment, self._event('payment_paid', 'pay_captured_123'))

        # Expected/actual: payment and order are active, stock remains deducted.
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.state, PaymentState.PAID)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(self.item.stock, 9)

    def test_duplicate_payment_failed_is_idempotent(self):
        # Initial state: UPI order stock is held.
        order, payment = self._place_reserved_upi_order()
        event = self._event('payment_failed', 'pay_failed_dupe')

        # Action: duplicate payment.failed mutations arrive.
        PaymentMutationService().mark_failed(payment, event)
        PaymentMutationService().mark_failed(payment, event)

        # Expected/actual: stock is restored once, order remains cancelled.
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.state, PaymentState.FAILED)
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.item.stock, 10)

    def test_duplicate_payment_captured_is_idempotent(self):
        # Initial state: UPI order stock is held.
        order, payment = self._place_reserved_upi_order()
        event = self._event('payment_paid', 'pay_captured_dupe')

        # Action: duplicate payment.captured mutations arrive.
        PaymentMutationService().mark_paid(payment, event)
        PaymentMutationService().mark_paid(payment, event)

        # Expected/actual: payment/order are active and stock is not deducted twice.
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.state, PaymentState.PAID)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(self.item.stock, 9)
        self.assertEqual(
            PaymentEvent.objects.filter(
                order=order,
                event_type=PaymentEvent.EventType.RAZORPAY_CONFIRMED,
                razorpay_payment_id='pay_captured_dupe',
            ).count(),
            1,
        )

    @patch('ordering.payments.jobs.PaymentReconciliationService')
    def test_expired_to_paid_late_capture_recovers_order_and_inventory(self, mock_reconciliation):
        # Initial state: abandoned UPI order has expired and stock has been restored.
        order, payment = self._place_reserved_upi_order()
        mock_reconciliation.return_value.reconcile_payment.return_value = payment
        PaymentTransaction.objects.filter(pk=payment.pk).update(
            expires_at=timezone.now() - timezone.timedelta(minutes=1)
        )
        from ordering.payments.jobs import expire_single_payment_task
        expire_single_payment_task(payment.id)
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.state, PaymentState.EXPIRED)
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.item.stock, 10)

        # Action: delayed payment.captured arrives after expiration.
        PaymentMutationService().mark_paid(payment, self._event('payment_paid', 'pay_late_capture'))

        # Expected/actual: order is recovered, payment is paid, inventory is re-deducted.
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.state, PaymentState.PAID)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(self.item.stock, 9)
        self.assertTrue(
            StockReservation.objects.filter(order=order, is_confirmed=True).count() >= 2
        )

    @patch('ordering.payments.jobs.PaymentReconciliationService')
    def test_late_capture_with_insufficient_inventory_requires_manual_recovery(self, mock_reconciliation):
        # Initial state: abandoned UPI order expired, then stock is consumed elsewhere.
        order, payment = self._place_reserved_upi_order()
        mock_reconciliation.return_value.reconcile_payment.return_value = payment
        PaymentTransaction.objects.filter(pk=payment.pk).update(
            expires_at=timezone.now() - timezone.timedelta(minutes=1)
        )
        from ordering.payments.jobs import expire_single_payment_task
        expire_single_payment_task(payment.id)
        MenuItem.objects.filter(pk=self.item.pk).update(stock=0)
        payment.refresh_from_db()

        # Action: delayed payment.captured arrives but inventory cannot be reserved.
        PaymentMutationService().mark_paid(payment, self._event('payment_paid', 'pay_late_manual'))

        # Expected/actual: no paid/cancelled inconsistency is created; manual alert exists.
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.state, PaymentState.EXPIRED)
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.item.stock, 0)
        self.assertTrue(payment.metadata.get('manual_recovery_required'))
        self.assertTrue(
            PaymentEvent.objects.filter(
                order=order,
                event_type=PaymentEvent.EventType.PAYMENT_RECOVERY_REQUIRED,
                razorpay_payment_id='pay_late_manual',
            ).exists()
        )

    def test_duplicate_captured_webhook_log_is_idempotent(self):
        # Initial state: valid unpaid UPI payment.
        order, payment = self._place_reserved_upi_order()
        payload = self._webhook_payload('payment.captured', event_id='evt_capture_dupe')
        body = json.dumps(payload).encode('utf-8')
        headers = self._signed_headers(body, event_id='evt_capture_dupe')

        # Action: duplicate webhook deliveries are received and processed.
        log1 = WebhookIngestionService().receive('razorpay', body, headers)
        log2 = WebhookIngestionService().receive('razorpay', body, headers)
        WebhookIngestionService().process_log(log1)
        WebhookIngestionService().process_log(log2)

        # Expected/actual: one WebhookLog, one confirmation, stock deducted once.
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(log1.id, log2.id)
        self.assertEqual(WebhookLog.objects.filter(provider_event_id='evt_capture_dupe').count(), 1)
        self.assertEqual(payment.state, PaymentState.PAID)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(self.item.stock, 9)

    def test_duplicate_failed_webhook_log_is_idempotent(self):
        # Initial state: valid unpaid UPI payment.
        order, payment = self._place_reserved_upi_order()
        payload = self._webhook_payload('payment.failed', provider_payment_id='pay_failed_webhook', event_id='evt_failed_dupe')
        body = json.dumps(payload).encode('utf-8')
        headers = self._signed_headers(body, event_id='evt_failed_dupe')

        # Action: duplicate failed webhook deliveries are received and processed.
        log1 = WebhookIngestionService().receive('razorpay', body, headers)
        log2 = WebhookIngestionService().receive('razorpay', body, headers)
        WebhookIngestionService().process_log(log1)
        WebhookIngestionService().process_log(log2)

        # Expected/actual: one WebhookLog, stock restored once, order cancelled.
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(log1.id, log2.id)
        self.assertEqual(WebhookLog.objects.filter(provider_event_id='evt_failed_dupe').count(), 1)
        self.assertEqual(payment.state, PaymentState.FAILED)
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.item.stock, 10)

    def test_concurrent_style_duplicate_webhook_delivery_same_event_is_safe(self):
        # Initial state: two queued tasks receive the same provider event.
        order, payment = self._place_reserved_upi_order()
        payload = self._webhook_payload('payment.captured', event_id='evt_same_event_race')
        body = json.dumps(payload).encode('utf-8')
        headers = self._signed_headers(body, event_id='evt_same_event_race')
        log = WebhookIngestionService().receive('razorpay', body, headers)

        # Action: the same log is processed twice, as can happen after retries/restarts.
        from ordering.payments.jobs import process_payment_webhook_task
        first = process_payment_webhook_task(log.id)
        second = process_payment_webhook_task(log.id)

        # Expected/actual: both task calls complete without duplicate side effects.
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(first['status'], 'processed')
        self.assertEqual(second['status'], 'processed')
        self.assertEqual(payment.state, PaymentState.PAID)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(self.item.stock, 9)
        self.assertEqual(
            PaymentEvent.objects.filter(
                order=order,
                event_type=PaymentEvent.EventType.RAZORPAY_CONFIRMED,
                razorpay_payment_id='pay_integrity_123',
            ).count(),
            1,
        )

    @patch('ordering.views.razorpay.Client')
    def test_frontend_verify_does_not_mark_paid_when_provider_fetch_fails(self, mock_razorpay_client):
        # Initial state: checkout signature is valid but provider status is unavailable.
        order, payment = self._place_reserved_upi_order()
        mock_client = mock_razorpay_client.return_value
        mock_client.utility.verify_payment_signature.return_value = None
        mock_client.payment.fetch.side_effect = Exception('provider unavailable')

        # Action: frontend verify endpoint is called.
        response = self.client.post(
            '/payments/razorpay/verify/',
            data=json.dumps({
                'razorpay_order_id': order.razorpay_order_id,
                'razorpay_payment_id': 'pay_fetch_down',
                'razorpay_signature': 'valid_signature',
            }).encode('utf-8'),
            content_type='application/json',
        )

        # Expected/actual: provider truth is unavailable, so no state advances.
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['error'], 'PAYMENT_VERIFICATION_UNAVAILABLE')
        payment.refresh_from_db()
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.state, PaymentState.INITIATED)
        self.assertEqual(order.status, Order.Status.UNPAID)
        self.assertEqual(self.item.stock, 9)
