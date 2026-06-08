# kitchen/services.py
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache

def trigger_kds_refresh(restaurant_id, order_id=None, action="refresh"):
    """
    Triggers a WebSocket message to all clients connected to the
    given restaurant's KDS group, instructing them to fetch the latest state.
    """
    # Invalidate cache for this restaurant — atomic version bump
    version_key = f"kds_version_{restaurant_id}"
    try:
        cache.incr(version_key)
    except ValueError:
        # Key doesn't exist or has expired — initialize it
        cache.set(version_key, 1, timeout=86400)

    channel_layer = get_channel_layer()
    group_name = f"kds_{restaurant_id}"
    
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            'type': 'kds.refresh',
            'order_id': str(order_id) if order_id else None,
            'action': action,
        }
    )


def broadcast_payment_update(restaurant_id, payment_id, state, order_id=None):
    channel_layer = get_channel_layer()
    group_name = f"kds_{restaurant_id}"
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            'type': 'payment.update',
            'payment_id': str(payment_id),
            'state': state,
            'order_id': str(order_id) if order_id else None,
        }
    )
