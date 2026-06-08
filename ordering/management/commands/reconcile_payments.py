from django.core.management.base import BaseCommand
from django.utils import timezone

from ordering.models import PaymentState, PaymentTransaction
from ordering.payments.services import PaymentReconciliationService


class Command(BaseCommand):
    help = "Reconcile pending/processing payment transactions with providers."

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=int, default=360)
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timezone.timedelta(minutes=options["minutes"])
        payments = (
            PaymentTransaction.objects
            .filter(
                state__in=[PaymentState.PENDING, PaymentState.INITIATED, PaymentState.PROCESSING],
                created_at__gte=cutoff,
            )
            .order_by("created_at")[:options["limit"]]
        )
        count = 0
        service = PaymentReconciliationService()
        for payment in payments:
            service.reconcile_payment(payment)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Reconciled {count} payment(s)."))
