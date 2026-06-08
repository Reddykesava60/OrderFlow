from django.core.management.base import BaseCommand

from ordering.payments.jobs import expire_pending_payments_task


class Command(BaseCommand):
    help = "Expire stale pending payment transactions after provider reconciliation."

    def handle(self, *args, **options):
        expired = expire_pending_payments_task()
        self.stdout.write(self.style.SUCCESS(f"Expired {expired or 0} payment(s)."))
