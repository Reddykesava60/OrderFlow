from django.core.management.base import BaseCommand

from ordering.models import WebhookLog
from ordering.payments.services import WebhookIngestionService


class Command(BaseCommand):
    help = "Process verified, unprocessed payment webhooks."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        count = 0
        qs = WebhookLog.objects.filter(signature_valid=True, processed_at__isnull=True).order_by("created_at")[:options["limit"]]
        for webhook_log in qs:
            WebhookIngestionService().process_log(webhook_log)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Processed {count} payment webhook(s)."))
