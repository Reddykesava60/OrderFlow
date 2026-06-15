from django.core.management.base import BaseCommand, CommandError
from ordering.models import WebhookLog
from ordering.payments.services import WebhookIngestionService

class Command(BaseCommand):
    help = 'Replays a webhook by ID'

    def add_arguments(self, parser):
        parser.add_argument('webhook_id', type=str, help='The UUID (or prefix) of the WebhookLog to replay')

    def handle(self, *args, **options):
        webhook_id = options['webhook_id']
        
        try:
            # allow short UUID prefix matching
            webhook_log = WebhookLog.objects.get(id__startswith=webhook_id)
        except WebhookLog.DoesNotExist:
            raise CommandError(f'WebhookLog "{webhook_id}" does not exist')
        except WebhookLog.MultipleObjectsReturned:
            raise CommandError(f'WebhookLog "{webhook_id}" matched multiple records. Use full UUID.')

        self.stdout.write(self.style.SUCCESS(f'Found webhook {webhook_log.id} ({webhook_log.provider_event_id})'))
        
        try:
            # We are replaying, so we should bypass the processed_at check inside the processor if we want to force it.
            # Wait, process_log checks if processed_at is set. No, process_log doesn't check it, the celery task checks it.
            # So calling process_log directly will just process it.
            service = WebhookIngestionService()
            service.process_log(webhook_log)
            
            # Fetch fresh
            webhook_log.refresh_from_db()
            if webhook_log.failed_reason:
                self.stdout.write(self.style.WARNING(f'Webhook processed with failure: {webhook_log.failed_reason}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Successfully processed webhook {webhook_log.id}'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error processing webhook: {str(e)}'))
