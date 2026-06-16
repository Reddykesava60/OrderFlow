import os
import django

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

from ordering.models import Order, PaymentTransaction

order = Order.objects.filter(order_number=8).first()
if order:
    print(f"Order #8: {order.id}, Status: {order.status}")
    for pt in PaymentTransaction.objects.filter(order=order):
        print(f"Payment {pt.id} State: {pt.state} Expires At: {pt.expires_at}")
else:
    print("Order #8 not found locally, checking by payment prefix c56e72a7")

payment = PaymentTransaction.objects.filter(id__startswith='c56e72a7').first()
if payment:
    print(f"Found Payment: {payment.id} State: {payment.state}")
    print(f"Order: {payment.order_id} Status: {payment.order.status if payment.order else 'N/A'}")
