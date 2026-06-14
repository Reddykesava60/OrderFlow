import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.prod')
django.setup()

from ordering.models import WebhookLog
from ordering.payments.providers import RazorpayProvider

def run():
    log = WebhookLog.objects.filter(processed_at__isnull=True).order_by('-created_at').first()
    if not log:
        print("No log found")
        return
        
    payload = json.loads(log.raw_payload or "{}")
    event = RazorpayProvider().parse_webhook(payload, log.headers)
    print(f"Parsed Event Kind: {event.kind}")
    print(f"Provider Order ID: {event.provider_order_id}")
    print(f"Provider Payment ID: {event.provider_payment_id}")

if __name__ == '__main__':
    run()
