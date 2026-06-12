import os
import sys
import uuid
import json
import traceback

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from ordering.models import PaymentTransaction, WebhookLog, Order, Restaurant
from ordering.payments.views import WebhookIngressView
from ordering.payments.jobs import process_payment_webhook_task
from django.test import RequestFactory

def run():
    print("Creating test data...")
    restaurant = Restaurant.objects.first()
    if not restaurant:
        restaurant = Restaurant.objects.create(name="Test Rest", slug="test-rest")
    
    order = Order.objects.create(
        restaurant=restaurant,
        order_number=9999,
        customer_name="Test Customer",
        payment_method=Order.PaymentMethod.UPI,
        status=Order.Status.UNPAID,
        total=1.00
    )
    
    payment = PaymentTransaction.objects.create(
        restaurant=restaurant,
        order=order,
        provider="razorpay",
        state="initiated",
        amount=1.00,
        provider_order_id="order_TEST123"
    )
    
    # Simulate UUID serialization error
    print("Testing dispatch UUID error...")
    factory = RequestFactory()
    
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_TEST123",
                    "order_id": "order_TEST123",
                    "amount": 100
                }
            }
        }
    }
    
    # Normally we need a valid signature. We'll bypass signature for the test by mocking gateway
    from ordering.payments.providers import RazorpayProvider
    original_verify = RazorpayProvider.verify_webhook
    RazorpayProvider.verify_webhook = lambda self, a, b, c: True
    
    request = factory.post(
        '/webhook/razorpay/', 
        data=json.dumps(payload),
        content_type='application/json'
    )
    
    # Audit print
    provider = RazorpayProvider()
    event = provider.parse_webhook(payload, {})
    print(f"AUDIT VALUES:")
    print(f"payment.amount = {payment.amount} ({type(payment.amount)})")
    print(f"event.amount = {event.amount} ({type(event.amount)})")
    print(f"payload amount = {payload['payload']['payment']['entity']['amount']}")
    print(f"provider_order_id = {event.provider_order_id}")
    print(f"provider_payment_id = {event.provider_payment_id}")

    request.headers = {'x-razorpay-signature': 'dummy'}
    
    view = WebhookIngressView()
    response = view.post(request, 'razorpay')
    
    print(f"Response status: {response.status_code}")
    
    # Check if webhook log was processed
    log = WebhookLog.objects.filter(provider_event_id=payload.get('id')).last()
    if log:
        print(f"Webhook Log saved. Processed at: {log.processed_at}")
        if not log.processed_at:
            print("FAILED: Webhook was saved but NOT processed! This confirms the UUID dispatch bug.")
    else:
        print("Webhook log not found.")

    RazorpayProvider.verify_webhook = original_verify

if __name__ == '__main__':
    run()
