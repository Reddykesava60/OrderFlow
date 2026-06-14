import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.prod')
django.setup()

from ordering.models import WebhookLog, PaymentTransaction
from kitchen.models import PaymentEvent

def run():
    payment_id = '8856f297-42fa-45b0-9bf4-374dfa9525f0'
    print(f"=== Investigating Payment ID: {payment_id} ===\n")
    
    try:
        payment = PaymentTransaction.objects.get(id=payment_id)
        print(f"Current State: {payment.state}")
        print(f"Provider Order ID: {payment.provider_order_id}")
        print(f"Provider Payment ID: {payment.provider_payment_id}")
        print(f"Amount: {payment.amount}\n")
    except PaymentTransaction.DoesNotExist:
        print("Payment not found!")
        return

    print("=== PaymentEvents Timeline ===")
    events = PaymentEvent.objects.filter(transaction_id=payment_id).order_by('created_at')
    for e in events:
        print(f"[{e.created_at}] TYPE: {e.event_type} | STATUS: {e.event_status}")
        if e.metadata:
            print(f"    Metadata: {json.dumps(e.metadata)}")
            
    print("\n=== WebhookLogs Timeline ===")
    logs = WebhookLog.objects.filter(payment_transaction_id=payment_id).order_by('created_at')
    for log in logs:
        print(f"[{log.created_at}] LOG ID: {log.id}")
        print(f"    Provider Event ID: {log.provider_event_id}")
        print(f"    Processed At: {log.processed_at}")
        print(f"    Failed Reason: {log.failed_reason}")
        
        payload = json.loads(log.raw_payload or "{}")
        event_name = payload.get("event", "UNKNOWN")
        print(f"    Payload Event: {event_name}")
        
        # Extract amount from payload if present
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        if entity:
            print(f"    Payload Payment ID: {entity.get('id')} | Amount: {entity.get('amount')}")

if __name__ == '__main__':
    run()
