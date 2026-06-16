import os
import django

# Load env vars
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.prod')
django.setup()

from django.utils import timezone
from ordering.models import Order, PaymentTransaction, PaymentState

# 1. Look for Order #8
order = Order.objects.filter(order_number=8).first()
if order:
    print(f"--- ORDER #8 ---")
    print(f"ID: {order.id}")
    print(f"Status: {order.status}")
    print(f"Total: {order.total}")
    
    # 2. Look for its payment
    payments = PaymentTransaction.objects.filter(order=order)
    for p in payments:
        print(f"\n--- PAYMENT FOR ORDER #8 ---")
        print(f"ID: {p.id}")
        print(f"State: {p.state}")
        print(f"Expires At: {p.expires_at}")
        print(f"Now: {timezone.now()}")
        if p.expires_at:
            print(f"Is expired? {p.expires_at < timezone.now()}")
else:
    print("Order #8 not found locally.")

# 3. Look for the payment prefix provided by user
print("\n--- SEARCHING BY PAYMENT PREFIX c56e72a7 ---")
payment = PaymentTransaction.objects.filter(id__startswith='c56e72a7').first()
if payment:
    print(f"Found Payment: {payment.id}")
    print(f"State: {payment.state}")
    print(f"Expires At: {payment.expires_at}")
    print(f"Is expired? {(payment.expires_at < timezone.now()) if payment.expires_at else 'No expiry'}")
    
    order = payment.order
    print(f"Order: {order.id if order else 'None'}")
    print(f"Order Number: {order.order_number if order else 'None'}")
else:
    print("Payment c56e72a7 not found locally.")

# 4. Show the exact queryset used by expire_pending_payments_task
print("\n--- QUERYSET CHECK ---")
qs = PaymentTransaction.objects.filter(
    state__in=[PaymentState.PENDING, PaymentState.INITIATED, PaymentState.PROCESSING],
    expires_at__lt=timezone.now(),
)
print("Payments matching expiration query:")
for p in qs:
    print(f"- Payment {p.id} (Order #{p.order.order_number if p.order else 'N/A'}, State: {p.state}, Expires: {p.expires_at})")
