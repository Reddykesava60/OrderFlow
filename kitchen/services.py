import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache

logger = logging.getLogger(__name__)

def trigger_kds_refresh(restaurant_id, order_id=None, action="refresh"):
    """
    Triggers a WebSocket message to all clients connected to the
    given restaurant's KDS group, instructing them to fetch the latest state.
    
    Wrapped in broad exception handling: A Redis failure here must NOT 
    crash the core payment confirmation / order pipeline.
    """
    try:
        # Invalidate cache for this restaurant — atomic version bump
        version_key = f"kds_version_{restaurant_id}"
        try:
            cache.incr(version_key)
        except ValueError:
            # Key doesn't exist or has expired — initialize it
            cache.set(version_key, 1, timeout=86400)
    except Exception as e:
        logger.warning(
            "kds_cache_invalidation_failed restaurant_id=%s error=%s - "
            "degrading to eventual consistency",
            restaurant_id, e
        )

    try:
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
    except Exception as e:
        logger.warning(
            "kds_websocket_broadcast_failed restaurant_id=%s action=%s error=%s",
            restaurant_id, action, e
        )


def broadcast_payment_update(restaurant_id, payment_id, state, order_id=None):
    """
    Broadcasts a payment status change to the KDS group.
    Fails gracefully if the realtime infrastructure (Redis) is down.
    """
    try:
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
    except Exception as e:
        logger.warning(
            "kds_payment_broadcast_failed restaurant_id=%s payment_id=%s error=%s",
            restaurant_id, payment_id, e
        )

def broadcast_user_disconnect(user_id):
    """
    Forces a WebSocket disconnect for all active sessions of a specific user.
    Called when a user's role is revoked, auth is invalidated, or account is disabled.
    """
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            {'type': 'force.disconnect'}
        )
    except Exception as e:
        logger.warning(
            "broadcast_user_disconnect_failed user_id=%s error=%s",
            user_id, e
        )
