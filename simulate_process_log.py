import os
import django
import json

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

from ordering.models import WebhookLog
from ordering.payments.services import WebhookIngestionService
from ordering.payments.providers import get_gateway

def simulate_for_log(log_id):
    print(f"\n======================")
    print(f"Simulating for WebhookLog ID: {log_id}")
    try:
        log = WebhookLog.objects.select_related("payment_transaction").get(pk=log_id)
    except WebhookLog.DoesNotExist:
        print("WebhookLog does not exist!")
        return

    print(f"Provider: {log.provider}")
    print(f"Payload Size: {len(log.raw_payload) if log.raw_payload else 0} bytes")
    
    try:
        payload = json.loads(log.raw_payload or "{}")
        print("json.loads() -> SUCCESS")
    except Exception as e:
        print(f"json.loads() -> FAILED: {e}")
        return

    try:
        event = get_gateway(log.provider).parse_webhook(payload, log.headers)
        print(f"parse_webhook() -> SUCCESS")
        print(f"  provider_order_id: {event.provider_order_id}")
        print(f"  provider_payment_id: {event.provider_payment_id}")
    except Exception as e:
        print(f"parse_webhook() -> FAILED: {e}")
        import traceback
        traceback.print_exc()
        return

    print(f"PaymentTransaction lookup result: {log.payment_transaction}")
    if log.payment_transaction:
        print(f"  Initial State: {log.payment_transaction.state}")

    print("\nExecuting actual process_log()...")
    service = WebhookIngestionService()
    try:
        result = service.process_log(log)
        print("process_log() completed without exceptions.")
    except Exception as e:
        print(f"process_log() RAISED EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        
    # Reload from DB
    log.refresh_from_db()
    print(f"Final processed_at: {log.processed_at}")
    print(f"Final failed_reason: {log.failed_reason}")
    if log.payment_transaction:
        log.payment_transaction.refresh_from_db()
        print(f"Final PaymentTransaction state: {log.payment_transaction.state}")

simulate_for_log("d36d4b65-6b08-4033-b48d-c4d86348987b")
simulate_for_log("599e572c-65ef-4782-95e0-c91c7542aa14")
