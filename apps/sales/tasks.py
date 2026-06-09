import logging
from uuid import UUID
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from .models import Order
from apps.catalog.services import CatalogService
from apps.operations.models import PlatformSettings

logger = logging.getLogger(__name__)

@shared_task
def expire_unpaid_order(order_id: UUID):
    """
    Called periodically or as a delayed task to cancel orders that remain UNPAID
    past the configured timeout, releasing their reserved stock.
    """
    try:
        order = Order.objects.get(id=order_id)
        if order.status != Order.Status.UNPAID:
            return # Order was paid or already handled

        settings = PlatformSettings.get_solo()
        timeout = timedelta(minutes=settings.cash_payment_timeout_minutes)
        
        # If enough time has passed
        if timezone.now() - order.created_at >= timeout:
            order.status = Order.Status.CANCELLED
            order.save()
            
            # Release stock
            for item in order.items.all():
                CatalogService.release_stock(item.menu_item_id, item.quantity, reference_id=order.id)
            
            logger.info(f"Order {order.id} expired and cancelled.")
    except Order.DoesNotExist:
        pass
