import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.prod')
django.setup()

from ordering.payments.providers import RazorpayProvider

def run():
    raw_payload_str = '{"account_id":"acc_SVVB8dLD33sdXX","contains":["payment"],"created_at":1781358895,"entity":"event","event":"payment.failed","payload":{"payment":{"entity":{"id":"pay_xyz","order_id":"order_xyz","amount":100}}}}'
    payload = json.loads(raw_payload_str)
    
    event = RazorpayProvider().parse_webhook(payload, {})
    print(f"Parsed Event Kind: {event.kind}")
    print(f"Provider Order ID: {event.provider_order_id}")
    print(f"Provider Payment ID: {event.provider_payment_id}")
    print(f"Provider Event ID: {event.provider_event_id}")

if __name__ == '__main__':
    run()
