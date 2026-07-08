# kitchen/consumers.py
import json
import time
from channels.generic.websocket import AsyncWebsocketConsumer

# Per-connection message throttle: max messages within a sliding window
WS_THROTTLE_MAX_MESSAGES = 30
WS_THROTTLE_WINDOW_SECONDS = 10


class KDSWebsocketConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        
        # Must be authenticated, active, and either STAFF or OWNER
        if not user.is_authenticated or not getattr(user, 'is_active', False):
            await self.close()
            return
        if user.role not in ['STAFF', 'OWNER']:
            await self.close()
            return
            
        if not user.restaurant_id:
            await self.close()
            return

        # Per-connection message timestamps for throttling
        self._message_timestamps = []

        # Join restaurant-specific KDS group
        self.restaurant_id = str(user.restaurant_id)
        self.group_name = f"kds_{self.restaurant_id}"
        self.user_group_name = f"user_{user.id}"
        
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )
        
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
        if hasattr(self, 'user_group_name'):
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )

    async def force_disconnect(self, event):
        """Handle broadcast instruction to forcefully disconnect this session."""
        await self.send(text_data=json.dumps({
            'action': 'force_disconnect',
            'message': 'Your session has been terminated by the server.'
        }))
        await self.close()

    def _is_throttled(self):
        """Simple sliding-window per-connection message throttle."""
        now = time.monotonic()
        cutoff = now - WS_THROTTLE_WINDOW_SECONDS
        self._message_timestamps = [
            ts for ts in self._message_timestamps if ts > cutoff
        ]
        if len(self._message_timestamps) >= WS_THROTTLE_MAX_MESSAGES:
            return True
        self._message_timestamps.append(now)
        return False

    async def receive(self, text_data):
        if self._is_throttled():
            await self.close(code=4029)
            return
        try:
            data = json.loads(text_data)
            if data.get("action") == "ping":
                await self.send(text_data=json.dumps({"action": "pong"}))
        except json.JSONDecodeError:
            pass

    async def kds_refresh(self, event):
        await self.send(text_data=json.dumps({
            'action': event.get('action', 'refresh'),
            'order_id': event.get('order_id'),
        }))

    async def payment_update(self, event):
        await self.send(text_data=json.dumps({
            'action': 'payment_update',
            'payment_id': event.get('payment_id'),
            'state': event.get('state'),
            'order_id': event.get('order_id'),
        }))
