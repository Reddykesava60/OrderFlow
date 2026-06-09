from uuid import UUID
from typing import List, Optional
from ninja import Router, Schema
from django.shortcuts import get_object_or_404
from .models import Order
from .dtos import PlaceOrderCommand, CartItemDTO, CartAddonDTO
from .use_cases import PlaceOrderUseCase

router = Router()

class CartAddonIn(Schema):
    addon_id: UUID
    quantity: int

class CartItemIn(Schema):
    menu_item_id: UUID
    quantity: int
    dining_option: str
    spice_level: str = ''
    addons: List[CartAddonIn] = []

class PlaceOrderIn(Schema):
    customer_name: str
    payment_method: str
    items: List[CartItemIn]
    table_number: str = ''
    idempotency_key: Optional[UUID] = None

class OrderOut(Schema):
    id: UUID
    order_number: int
    status: str
    total_amount: str
    idempotency_key: UUID

@router.post("/{restaurant_id}/orders/", response={201: OrderOut, 400: dict})
def place_order(request, restaurant_id: UUID, payload: PlaceOrderIn):
    cmd_items = []
    for item in payload.items:
        addons = [CartAddonDTO(**addon.dict()) for addon in item.addons]
        cmd_items.append(CartItemDTO(
            menu_item_id=item.menu_item_id,
            quantity=item.quantity,
            dining_option=item.dining_option,
            spice_level=item.spice_level,
            addons=addons
        ))

    cmd = PlaceOrderCommand(
        restaurant_id=restaurant_id,
        customer_name=payload.customer_name,
        payment_method=payload.payment_method,
        items=cmd_items,
        table_number=payload.table_number,
        idempotency_key=payload.idempotency_key,
        customer_id=request.user.id if request.user.is_authenticated else None
    )

    try:
        order = PlaceOrderUseCase.execute(cmd)
        return 201, {
            "id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "total_amount": str(order.total_amount),
            "idempotency_key": order.idempotency_key
        }
    except ValueError as e:
        return 400, {"detail": str(e)}
    except Exception as e: # Catch InsufficientStockError and ItemNotFoundError from CatalogService
        return 400, {"detail": str(e)}
