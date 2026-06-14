import os
import django
import sys
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.prod')
django.setup()

from ordering.models import WebhookLog, PaymentTransaction, Order
from kitchen.models import PaymentEvent

def run():
    print("=== Auditing payment.failed webhooks ===")
    logs = WebhookLog.objects.filter(raw_payload__contains='"payment.failed"').order_by('-created_at')[:1]
    
    if not logs:
        print("No payment.failed webhook logs found.")
        return
        
    for log in logs:
        print(f"\nWebhookLog ID: {log.id}")
        print(f"Created At: {log.created_at}")
        print(f"Signature Valid: {log.signature_valid}")
        print(f"Processed At: {log.processed_at}")
        print(f"Failed Reason: {log.failed_reason}")
        print(f"Raw Payload: {log.raw_payload[:200]}...")
        
        payment = log.payment_transaction
        print(f"\nPaymentTransaction ID: {payment.id if payment else 'None'}")
        if payment:
            print(f"State: {payment.state}")
            print(f"Provider Payment ID: {payment.provider_payment_id}")
            
            order = payment.order
            print(f"\nOrder ID: {order.id if order else 'None'}")
            if order:
                print(f"Order Status: {order.status}")
                print(f"Order Paid At: {order.paid_at}")
                
            print("\nPaymentEvents for this Transaction:")
            events = PaymentEvent.objects.filter(transaction=payment).order_by('created_at')
            for event in events:
                print(f" - {event.created_at} | {event.event_type} | Status: {event.event_status} | Razorpay ID: {event.razorpay_payment_id}")
                
if __name__ == '__main__':
    run()
