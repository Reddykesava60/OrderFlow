from django.core.management.base import BaseCommand
from ordering.models import WebhookLog

class Command(BaseCommand):
    help = 'Repairs WebhookLogs that were processed before the Status Enum was introduced'

    def handle(self, *args, **kwargs):
        # 1. Any webhook with processed_at AND no failed_reason was successfully processed
        successful = WebhookLog.objects.filter(
            status=WebhookLog.Status.PENDING,
            processed_at__isnull=False,
            failed_reason=''
        )
        successful_count = successful.update(status=WebhookLog.Status.PROCESSED)

        # 2. Any webhook with processed_at AND a failed_reason means it permanently failed (terminal exception)
        dead_lettered = WebhookLog.objects.filter(
            status=WebhookLog.Status.PENDING,
            processed_at__isnull=False
        ).exclude(failed_reason='')
        dead_lettered_count = dead_lettered.update(status=WebhookLog.Status.DEAD_LETTERED)

        # 3. Any webhook with retry_count >= 3 that isn't processed should be dead-lettered
        max_retries = WebhookLog.objects.filter(
            status=WebhookLog.Status.PENDING,
            retry_count__gte=3
        )
        max_retries_count = max_retries.update(status=WebhookLog.Status.DEAD_LETTERED)

        self.stdout.write(self.style.SUCCESS(
            f'Successfully repaired webhooks:\n'
            f'- Marked {successful_count} as PROCESSED\n'
            f'- Marked {dead_lettered_count} as DEAD_LETTERED (from old errors)\n'
            f'- Marked {max_retries_count} as DEAD_LETTERED (from max retries)'
        ))
