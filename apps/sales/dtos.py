from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID

@dataclass
class CartAddonDTO:
    addon_id: UUID
    quantity: int

@dataclass
class CartItemDTO:
    menu_item_id: UUID
    quantity: int
    dining_option: str # 'DINE_IN' or 'PARCEL'
    spice_level: str = ''
    addons: List[CartAddonDTO] = field(default_factory=list)

@dataclass
class PlaceOrderCommand:
    restaurant_id: UUID
    customer_name: str
    payment_method: str # 'CASH' or 'UPI'
    items: List[CartItemDTO]
    
    table_number: str = ''
    customer_id: Optional[UUID] = None
    idempotency_key: Optional[UUID] = None
