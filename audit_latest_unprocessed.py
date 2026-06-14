import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.prod')
django.setup()

from ordering.models import WebhookLog
from kitchen.models import PaymentEvent

def run():
    print("=== Latest Unprocessed Webhooks ===")
    logs = WebhookLog.objects.filter(processed_at__isnull=True).order_by('-created_at')[:3]
    
    for log in logs:
        print(f"\nWebhookLog ID: {log.id}")
        print(f"Created At: {log.created_at}")
        print(f"Provider: {log.provider}")
        print(f"Failed Reason: {log.failed_reason}")
        print(f"Raw: {log.raw_payload[:100]}...")
        
        payment = log.payment_transaction
        print(f"Transaction State: {payment.state if payment else 'None'}")
        
        print("Events:")
        events = PaymentEvent.objects.filter(transaction=payment).order_by('created_at')
        for e in events:
            print(f" - {e.created_at} | {e.event_type} | {e.event_status}")

if __name__ == '__main__':
    run()
