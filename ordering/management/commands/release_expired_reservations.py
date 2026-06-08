# ordering/management/commands/release_expired_reservations.py
"""
Run every 30 minutes via cron:
  */30 * * * * /path/to/.venv/bin/python manage.py release_expired_reservations
"""
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from ordering.models import Order, StockReservation
from ordering.services import cancel_upi_payment, expire_overdue_unpaid_cash_orders, get_cash_payment_timeout_minutes
from kitchen.models import PaymentEvent

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Release expired UPI reservations and expire timed-out unpaid cash orders'

    def handle(self, *args, **options):
        now     = timezone.now()
        expired = StockReservation.objects.filter(
            expires_at__lt=now,
            is_confirmed=False,
        ).select_related('order', 'menu_item', 'addon')

        # Group by order
        order_map = {}
        for res in expired:
            order_map.setdefault(res.order_id, {'order': res.order, 'reservations': []})
            order_map[res.order_id]['reservations'].append(res)

        released = 0
        for group in order_map.values():
            order = group['order']
            try:
                with transaction.atomic():
                    order = Order.objects.select_for_update().get(pk=order.pk)

                    if order.status != Order.Status.UNPAID:
                        # Already handled by webhook — just mark reservations done
                        StockReservation.objects.filter(
                            order=order, is_confirmed=False
                        ).update(is_confirmed=True)
                        continue

                    cancel_upi_payment(order, PaymentEvent.EventType.PAYMENT_TIMEOUT)
                    released += 1

            except Exception:
                logger.exception("Error releasing reservations for order %s", order.pk)

        cash_timeout_minutes = get_cash_payment_timeout_minutes()
        expired_cash = expire_overdue_unpaid_cash_orders()

        self.stdout.write(
            f"Released {released} expired UPI order(s). "
            f"Expired {expired_cash} unpaid cash order(s) after {cash_timeout_minutes} minute(s)."
        )
