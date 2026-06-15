import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.base')
django.setup()

from ordering.models import WebhookLog
from kitchen.models import PaymentEvent

def run():
    print("--- SCENARIO 1: FAKE ORDER ID ---")
    payload1 = {
        "entity": "event",
        "account_id": "acc_123",
        "event": "payment.captured",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_fake123",
                    "entity": "payment",
                    "amount": 1000,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": "fake"
                }
            }
        },
        "created_at": 1600000000
    }
    raw_body1 = json.dumps(payload1).encode('utf-8')
    headers1 = {"HTTP_X_RAZORPAY_SIGNATURE": "invalid_signature_12345"}
    
    try:
        from ordering.payments.services import WebhookIngestionService
        WebhookIngestionService().receive('razorpay', raw_body1, headers1)
    except Exception as e:
        pass
        
    print("PaymentEvents created:")
    from django.utils import timezone
    from datetime import timedelta
    ev1 = PaymentEvent.objects.order_by('-created_at').first()
    print(f" - {ev1.event_type} (amount={ev1.amount})")
    
    print("\n--- SCENARIO 2: INVALID SIGNATURE ---")
    payload2 = {
        "entity": "event",
        "account_id": "acc_123",
        "event": "payment.captured",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_T1c3OFtGlRc55C",
                    "entity": "payment",
                    "amount": 1000,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": "order_T1c3Kd0QPV1i3I"
                }
            }
        },
        "created_at": 1600000001
    }
    raw_body2 = json.dumps(payload2).encode('utf-8')
    headers2 = {"HTTP_X_RAZORPAY_SIGNATURE": "invalid_signature_12345"}
    
    try:
        WebhookIngestionService().receive('razorpay', raw_body2, headers2)
    except Exception as e:
        print(f"Caught exception: {type(e).__name__}: {str(e)}")
        
    log = WebhookLog.objects.order_by('-created_at').first()
    print(f"WebhookLog ID: {log.id}")
    print(f"Signature Valid: {log.signature_valid}")
    print(f"Failed Reason: {log.failed_reason}")

if __name__ == '__main__':
    run()
