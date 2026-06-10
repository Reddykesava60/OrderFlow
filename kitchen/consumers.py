# kitchen/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

class KDSWebsocketConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        
        # Must be authenticated and either STAFF or OWNER
        if not user.is_authenticated or user.role not in ['STAFF', 'OWNER']:
            await self.close()
            return
            
        if not user.restaurant_id:
            await self.close()
            return

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

    async def receive(self, text_data):
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
