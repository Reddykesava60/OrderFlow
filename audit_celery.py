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

from django.conf import settings

print("CELERY_TASK_DEFAULT_QUEUE:", getattr(settings, 'CELERY_TASK_DEFAULT_QUEUE', 'Not Set'))
print("CELERY_TASK_ROUTES:", getattr(settings, 'CELERY_TASK_ROUTES', 'Not Set'))
print("CELERY_TASK_QUEUES:", getattr(settings, 'CELERY_TASK_QUEUES', 'Not Set'))
print("CELERY_TASK_ACKS_LATE:", getattr(settings, 'CELERY_TASK_ACKS_LATE', 'Not Set'))

# Print specific task queue bindings by inspecting Celery app directly if possible
from dineflow.celery import app

print("\n--- Worker Queues ---")
process_payment_webhook_task_route = app.conf.task_routes.get('ordering.payments.jobs.process_payment_webhook_task', 'default')
print(f"process_payment_webhook_task route: {process_payment_webhook_task_route}")

process_unprocessed_route = app.conf.task_routes.get('ordering.payments.jobs.process_unprocessed_webhooks_task', 'default')
print(f"process_unprocessed_webhooks_task route: {process_unprocessed_route}")
