from django.utils import timezone
from apps.payments.use_cases import OrderPaidEvent
from .models import Order

def handle_order_paid(event: OrderPaidEvent):
    """
    Updates order status upon successful payment.
    """
    order = Order.objects.filter(id=event.order_id).first()
    if order and order.status == Order.Status.UNPAID:
        order.status = Order.Status.PENDING
        order.paid_at = timezone.now()
        order.save()
