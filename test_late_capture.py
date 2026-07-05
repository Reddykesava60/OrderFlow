import os
import django
import json
import hmac
import hashlib
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.dev')
django.setup()

from django.test import Client
from core.models import Restaurant, Customer
from ordering.models import Order, PaymentTransaction, PaymentState
from ordering.payments.services import WebhookLog

def run():
    restaurant = Restaurant.objects.first()
    if not restaurant:
        restaurant = Restaurant.objects.create(name="UAT Test Restaurant")
        
    customer = Customer.objects.first()
    if not customer:
        customer = Customer.objects.create(phone="9999999999", name="UAT User")
    
    import random
    
    # 1. Create the Order but mark it as CANCELLED (simulating checkout timeout)
    order = Order.objects.create(
        restaurant=restaurant,
        customer=customer,
        order_number=random.randint(1000, 9999),
        customer_name="UAT User",
        payment_method=Order.PaymentMethod.UPI,
        total=Decimal("100.00"),
        status=Order.Status.CANCELLED
    )

    # 2. Setup the PaymentTransaction pointing to this order and mark it FAILED
    provider_order_id = f"rzp_order_late_{order.id}"
    payment = PaymentTransaction.objects.create(
        order=order,
        restaurant=restaurant,
        provider="razorpay",
        amount=Decimal("100.00"),
        provider_order_id=provider_order_id,
        state=PaymentState.FAILED
    )
    
    print(f"\n--- LATE CAPTURE SETUP ---")
    print(f"Created Order: {order.id}")
    print(f"Initial Order Status: {order.status}")
    print(f"Initial Payment State: {payment.state}")

    # 3. Create the Razorpay webhook payload for late capture
    payload = {
        "entity": "event",
        "account_id": "acc_12345",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_late_999",
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
    
    # 4. Sign it using the global webhook secret
    from django.conf import settings
    signature = hmac.new(
        key=settings.RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    headers = {
        "HTTP_X_RAZORPAY_SIGNATURE": signature,
        "HTTP_X_RAZORPAY_EVENT_ID": f"ev_late_{order.id}",
        "CONTENT_TYPE": "application/json"
    }

    client = Client(SERVER_NAME="localhost")
    
    # 5. Send the delayed webhook!
    print("\n--- FIRING LATE WEBHOOK ---")
    settings.PAYMENT_JOBS_INLINE = True
    response = client.post(
        "/payments/webhook/razorpay/",
        data=raw_body,
        content_type="application/json",
        **headers
    )
    print(f"Response Status: {response.status_code}")
    
    # 6. Check if the payment and order recovered
    payment.refresh_from_db()
    order.refresh_from_db()
    
    print(f"\n--- RECOVERY RESULTS ---")
    print(f"Final Payment State: {payment.state}")
    print(f"Final Order Status: {order.status}")
    print(f"Recovered Correctly? {'YES' if order.status == Order.Status.PENDING else 'NO'}")

if __name__ == "__main__":
    run()
