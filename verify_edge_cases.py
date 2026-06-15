import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.prod')
django.setup()

from decimal import Decimal
from django.utils import timezone
from ordering.models import Order, PaymentTransaction, StockReservation, PaymentState, WebhookLog
from core.models import Restaurant, Customer, MenuItem
from ordering.payments.jobs import expire_single_payment_task, release_expired_reservations_task, process_unprocessed_webhooks_task
from kitchen.models import PaymentEvent
from ordering.payments.services import WebhookIngestionService

print("Running edge cases verification...")

# Pick a restaurant
restaurant = Restaurant.objects.first()

print("\nA. Duplicate expiration path")
order1 = Order.objects.create(restaurant=restaurant, order_number=101, total=Decimal('100.00'), status=Order.Status.UNPAID)
menu_item1 = MenuItem.objects.create(restaurant=restaurant, name="Test Item A", base_price=Decimal('100.00'), stock=10)
res1 = StockReservation.objects.create(order=order1, menu_item=menu_item1, quantity=1, is_confirmed=False, expires_at=timezone.now() + timezone.timedelta(minutes=15))

payment1 = PaymentTransaction.objects.create(
    restaurant=restaurant, order=order1, amount=Decimal('100.00'),
    state=PaymentState.INITIATED, provider='razorpay',
    expires_at=timezone.now() - timezone.timedelta(minutes=1)
)

expire_single_payment_task(payment1.id)
menu_item1.refresh_from_db()
print(f"Stock after expire_single_payment_task: {menu_item1.stock} (expected 11)")

release_expired_reservations_task()
menu_item1.refresh_from_db()
print(f"Stock after release_expired_reservations_task: {menu_item1.stock} (expected 11, NO DOUBLE INCREMENT)")

print("\nB. payment.failed after expiration")
order2 = Order.objects.create(restaurant=restaurant, order_number=102, total=Decimal('100.00'), status=Order.Status.UNPAID)
menu_item2 = MenuItem.objects.create(restaurant=restaurant, name="Test Item B", base_price=Decimal('100.00'), stock=10)
res2 = StockReservation.objects.create(order=order2, menu_item=menu_item2, quantity=1, is_confirmed=False, expires_at=timezone.now() + timezone.timedelta(minutes=15))

payment2 = PaymentTransaction.objects.create(
    restaurant=restaurant, order=order2, amount=Decimal('100.00'),
    state=PaymentState.INITIATED, provider='razorpay',
    expires_at=timezone.now() - timezone.timedelta(minutes=1)
)

expire_single_payment_task(payment2.id)
menu_item2.refresh_from_db()
print(f"Stock after expire_single_payment_task: {menu_item2.stock} (expected 11)")

# Create mock webhook event
class MockEvent:
    provider_payment_id = "pay_mock123"
    amount = Decimal('100.00')

# It should not fail or duplicate
from ordering.payments.services import PaymentMutationService
PaymentMutationService().mark_failed(payment2, MockEvent())
menu_item2.refresh_from_db()
print(f"Stock after mark_failed: {menu_item2.stock} (expected 11)")

print("\nC. payment.captured after expiration")
order3 = Order.objects.create(restaurant=restaurant, order_number=103, total=Decimal('100.00'), status=Order.Status.UNPAID)
menu_item3 = MenuItem.objects.create(restaurant=restaurant, name="Test Item C", base_price=Decimal('100.00'), stock=10)
res3 = StockReservation.objects.create(order=order3, menu_item=menu_item3, quantity=1, is_confirmed=False, expires_at=timezone.now() + timezone.timedelta(minutes=15))

from ordering.models import OrderItem
OrderItem.objects.create(order=order3, menu_item=menu_item3, quantity=1, unit_price=Decimal('100.00'), dining_option='DINE_IN', menu_item_name='Test Item C')

payment3 = PaymentTransaction.objects.create(
    restaurant=restaurant, order=order3, amount=Decimal('100.00'),
    state=PaymentState.INITIATED, provider='razorpay',
    expires_at=timezone.now() - timezone.timedelta(minutes=1)
)

expire_single_payment_task(payment3.id)
menu_item3.refresh_from_db()
print(f"Stock after expire_single_payment_task: {menu_item3.stock} (expected 11)")

try:
    PaymentMutationService().mark_paid(payment3, MockEvent())
    menu_item3.refresh_from_db()
    print(f"Stock after mark_paid: {menu_item3.stock} (expected 10)")
    payment3.refresh_from_db()
    print(f"Payment state: {payment3.state} (expected paid)")
except Exception as e:
    print(f"Exception during mark_paid: {e}")

print("\nD. Queue starvation test")

WebhookLog.objects.all().delete()

# Create 5 broken webhooks
for i in range(5):
    WebhookLog.objects.create(
        restaurant=restaurant, provider='razorpay', payload_hash=f'broken_{i}',
        signature_valid=True, raw_payload='{"error": "mock"}'
    )

# Create 5 valid webhooks
for i in range(5):
    WebhookLog.objects.create(
        restaurant=restaurant, provider='razorpay', payload_hash=f'valid_{i}',
        signature_valid=True, raw_payload='{"event": "payment.failed"}'
    )

import json
from unittest.mock import patch

# Mock WebhookIngestionService.process_log to simulate failure on broken webhooks
original_process_log = WebhookIngestionService.process_log

def mock_process_log(self, webhook_log):
    if "broken" in webhook_log.payload_hash:
        raise Exception("Mock intermittent failure")
    return original_process_log(self, webhook_log)

with patch.object(WebhookIngestionService, 'process_log', new=mock_process_log):
    print("Run 1")
    process_unprocessed_webhooks_task(limit=5)
    print("Run 2")
    process_unprocessed_webhooks_task(limit=5)
    print("Run 3")
    process_unprocessed_webhooks_task(limit=5)
    print("Run 4")
    process_unprocessed_webhooks_task(limit=5)
    print("Run 5")
    process_unprocessed_webhooks_task(limit=5)

for w in WebhookLog.objects.order_by('payload_hash'):
    print(f"Webhook {w.payload_hash}: processed_at={bool(w.processed_at)}, retry_count={w.retry_count}")

