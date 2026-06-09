from uuid import UUID
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class InitializePaymentCommand:
    restaurant_id: UUID
    order_id: UUID
    amount: Decimal
    currency: str = 'INR'
    idempotency_key: UUID = None

@dataclass
class ProcessWebhookCommand:
    restaurant_id: UUID
    provider: str
    payload_body: str
    signature: str
