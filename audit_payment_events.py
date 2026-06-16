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

from kitchen.models import PaymentEvent

print("--- PaymentEvents for c56e72a7 ---")
events = PaymentEvent.objects.filter(transaction_id='c56e72a7-92f2-4412-ba4f-92d87e47b8d1').order_by('created_at')
for e in events:
    print(f"[{e.created_at}] {e.event_type} - {e.event_status}")

print("\n--- Any PaymentEvents indicating expiration ran? ---")
expiration_events = PaymentEvent.objects.filter(event_type__in=['PAYMENT_TIMEOUT', 'PAYMENT_FAILED']).order_by('-created_at')[:5]
for e in expiration_events:
    print(f"[{e.created_at}] Order: {e.order_id} - {e.event_type} - {e.event_status}")
