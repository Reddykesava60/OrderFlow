import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.prod')
django.setup()

from ordering.models import WebhookLog
from ordering.payments.services import WebhookIngestionService

def run():
    log = WebhookLog.objects.filter(processed_at__isnull=True).order_by('-created_at').first()
    if not log:
        print("No log found")
        return
        
    print(f"Processing webhook {log.id}...")
    try:
        WebhookIngestionService().process_log(log)
        print("Success!")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    run()
