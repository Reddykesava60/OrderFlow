import uuid
from decimal import Decimal
from django.db import transaction
from .dtos import PlaceOrderCommand
from .models import Order, OrderItem, OrderItemAddOn, OrderCounter
from apps.catalog.services import CatalogService, ItemNotFoundError, InsufficientStockError

class PlaceOrderUseCase:
    @staticmethod
    def _generate_order_number(restaurant_id: uuid.UUID) -> int:
        counter, _ = OrderCounter.objects.select_for_update().get_or_create(restaurant_id=restaurant_id)
        counter.last_number += 1
        counter.save()
        return counter.last_number

    @staticmethod
    def execute(cmd: PlaceOrderCommand) -> Order:
        if len(cmd.items) == 0:
            raise ValueError("Cart cannot be empty")
        if len(cmd.items) > 30:
            raise ValueError("Cart cannot exceed 30 distinct items")

        # Basic idempotency check
        if cmd.idempotency_key:
            existing_order = Order.objects.filter(idempotency_key=cmd.idempotency_key).first()
            if existing_order:
                return existing_order

        idempotency_key = cmd.idempotency_key or uuid.uuid4()

        with transaction.atomic():
            order_number = PlaceOrderUseCase._generate_order_number(cmd.restaurant_id)
            
            # Temporary holder for the total
            total_amount = Decimal('0.0000')

            order = Order.objects.create(
                restaurant_id=cmd.restaurant_id,
                customer_name=cmd.customer_name,
                customer_id=cmd.customer_id,
                table_number=cmd.table_number,
                payment_method=cmd.payment_method,
                status=Order.Status.UNPAID,
                total_amount=Decimal('0.0000'), # Will update
                idempotency_key=idempotency_key,
                order_number=order_number
            )

            # Process Line Items
            for item_dto in cmd.items:
                if not (1 <= item_dto.quantity <= 99):
                    raise ValueError(f"Invalid quantity {item_dto.quantity} for item")

                catalog_item = CatalogService.get_menu_item(item_dto.menu_item_id, cmd.restaurant_id)
                
                # Surcharge handling
                surcharge = catalog_item.parcel_surcharge if item_dto.dining_option == 'PARCEL' else Decimal('0.0000')
                line_price = catalog_item.base_price + surcharge
                
                # Reserve stock
                if catalog_item.auto_hidden_due_to_stock:
                    CatalogService.reserve_stock(catalog_item.id, item_dto.quantity, reference_id=order.id)

                order_item = OrderItem.objects.create(
                    order=order,
                    menu_item_id=catalog_item.id,
                    menu_item_name=catalog_item.name,
                    unit_price=catalog_item.base_price,
                    parcel_surcharge=surcharge,
                    quantity=item_dto.quantity,
                    dining_option=item_dto.dining_option,
                    spice_level=item_dto.spice_level
                )
                
                item_total = line_price * item_dto.quantity

                # Process Addons
                for addon_dto in item_dto.addons:
                    catalog_addon = CatalogService.get_addon(addon_dto.addon_id, cmd.restaurant_id)
                    
                    if not (1 <= addon_dto.quantity <= catalog_addon.max_qty):
                        raise ValueError(f"Invalid quantity {addon_dto.quantity} for addon {catalog_addon.name}")

                    OrderItemAddOn.objects.create(
                        order_item=order_item,
                        addon_id=catalog_addon.id,
                        addon_name=catalog_addon.name,
                        unit_price=catalog_addon.price,
                        quantity=addon_dto.quantity
                    )
                    
                    item_total += catalog_addon.price * addon_dto.quantity * item_dto.quantity

                total_amount += item_total

            order.total_amount = total_amount
            order.save()

            # Dispatch delayed task to expire if unpaid
            from .tasks import expire_unpaid_order
            from apps.operations.models import PlatformSettings
            timeout_mins = PlatformSettings.get_solo().cash_payment_timeout_minutes
            expire_unpaid_order.apply_async((order.id,), countdown=timeout_mins * 60)

            # Wait to emit events or initialize payment intent
            return order
