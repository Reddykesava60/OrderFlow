import os
import django
import json
import hmac
import hashlib
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings')
django.setup()

from django.test import Client
from core.models import Restaurant, Customer
from ordering.models import Order, PaymentTransaction, PaymentState
from ordering.payments.services import WebhookLog

def run():
    # 1. Setup using existing dev database objects
    restaurant = Restaurant.objects.first()
    if not restaurant:
        restaurant = Restaurant.objects.create(name="UAT Test Restaurant")
        
    # Give the restaurant a fake webhook secret for Razorpay
    restaurant.config.razorpay_webhook_secret = "test_secret_123"
    restaurant.config.razorpay_key_id = "rzp_test_123"
    restaurant.config.save()

    customer = Customer.objects.first()
    if not customer:
        customer = Customer.objects.create(phone="9999999999", name="UAT User")
    
    import random
    order = Order.objects.create(
        restaurant=restaurant,
        customer=customer,
        order_number=random.randint(1000, 9999),
        customer_name="UAT User",
        payment_method=Order.PaymentMethod.UPI,
        total=Decimal("100.00"),
        status=Order.Status.PENDING
    )

    # 2. Setup the PaymentTransaction pointing to this order
    provider_order_id = f"rzp_order_{order.id}"
    payment = PaymentTransaction.objects.create(
        order=order,
        restaurant=restaurant,
        provider="razorpay",
        amount=Decimal("100.00"),
        provider_order_id=provider_order_id,
        state=PaymentState.PENDING
    )
    print(f"\n--- SETUP COMPLETE ---")
    print(f"Created Payment: {payment.id}")
    print(f"Provider Order ID: {provider_order_id}")

    # 3. Create the Razorpay webhook payload
    payload = {
        "entity": "event",
        "account_id": "acc_12345",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_999",
                    "entity": "payment",
                    "amount": 10000,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": provider_order_id
                }
            }
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")
    
    # 4. Sign it using the webhook secret
    signature = hmac.new(
        key=b"your_webhook_secret_here",
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    headers = {
        "HTTP_X_RAZORPAY_SIGNATURE": signature,
        "HTTP_X_RAZORPAY_EVENT_ID": "ev_test_idempotent_001",
        "CONTENT_TYPE": "application/json"
    }

    client = Client(SERVER_NAME="localhost")
    
    # 5. Send it 3 times!
    print("\n--- FIRING WEBHOOKS ---")
    for i in range(1, 4):
        print(f"\nDelivery Attempt #{i}:")
        response = client.post(
            "/payments/webhook/razorpay/",
            data=raw_body,
            content_type="application/json",
            **headers
        )
        print(f"  Response Status: {response.status_code}")
        
        # Check if the payment was updated
        payment.refresh_from_db()
        print(f"  Payment State: {payment.state}")
        
        # Check logs
        logs_count = WebhookLog.objects.filter(provider_event_id="ev_test_idempotent_001").count()
        print(f"  Total distinct WebhookLog entries for this event: {logs_count}")

if __name__ == "__main__":
    run()
