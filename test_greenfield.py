import os
import django
import uuid
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.operations.models import Restaurant, RestaurantConfig, PlatformSettings
from apps.catalog.models import ItemType, MenuItem, AddOn, MenuItemAddOn, InventoryLedger
from apps.sales.dtos import PlaceOrderCommand, CartItemDTO, CartAddonDTO
from apps.sales.use_cases import PlaceOrderUseCase
from apps.sales.models import Order
from apps.payments.use_cases import PaymentUseCases
from apps.payments.dtos import ProcessWebhookCommand
from apps.finance.models import LedgerEntry
from shared.event_bus import event_bus

def run_simulation():
    # 1. Setup Tenant and Platform Settings
    settings = PlatformSettings.get_solo()
    settings.platform_fee_percent = Decimal('5.00')
    settings.save()

    restaurant, _ = Restaurant.objects.get_or_create(slug="greenfield", defaults={
        'name': "Greenfield Cafe", 
        'commission_rate': Decimal('3.00')
    })
    RestaurantConfig.objects.get_or_create(restaurant=restaurant)

    # 2. Setup Catalog & Inventory
    cat, _ = ItemType.objects.get_or_create(restaurant_id=restaurant.id, name="Mains")
    item, _ = MenuItem.objects.get_or_create(
        restaurant_id=restaurant.id, 
        name="Burger", 
        defaults={
            'item_type': cat,
            'base_price': Decimal('100.00'),
            'parcel_surcharge': Decimal('10.00'),
            'auto_hidden_due_to_stock': True
        }
    )
    addon, _ = AddOn.objects.get_or_create(restaurant_id=restaurant.id, name="Cheese", defaults={'price': Decimal('20.00')})
    MenuItemAddOn.objects.get_or_create(menu_item=item, addon=addon)

    InventoryLedger.objects.get_or_create(
        restaurant_id=restaurant.id,
        menu_item=item,
        transaction_type=InventoryLedger.TransactionType.INITIAL,
        defaults={'quantity_change': 50}
    )

    print("--- Environment Setup Complete ---")

    # 3. Simulate Checkout (Sales Domain)
    cmd = PlaceOrderCommand(
        restaurant_id=restaurant.id,
        customer_name="John Doe",
        payment_method="UPI",
        items=[
            CartItemDTO(
                menu_item_id=item.id,
                quantity=2,
                dining_option='PARCEL',
                addons=[CartAddonDTO(addon_id=addon.id, quantity=1)]
            )
        ]
    )

    order = PlaceOrderUseCase.execute(cmd)
    
    # 2 * (100 base + 10 parcel) = 220
    # 2 * (20 cheese * 1 qty) = 40
    # Total = 260
    print(f"Order created: {order.id} for {order.total_amount}")
    
    # 4. Simulate Payment Intent (Payments Domain)
    from apps.payments.dtos import InitializePaymentCommand
    pay_cmd = InitializePaymentCommand(
        restaurant_id=restaurant.id,
        order_id=order.id,
        amount=order.total_amount
    )
    tx = PaymentUseCases.initialize_payment(pay_cmd)
    print(f"Payment initiated: {tx.provider_order_id} (State: {tx.state})")

    # 5. Simulate Webhook (Payments -> EventBus -> Finance/Sales)
    import json
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "order_id": tx.provider_order_id
                }
            }
        }
    }
    
    webhook_cmd = ProcessWebhookCommand(
        restaurant_id=restaurant.id,
        provider='razorpay',
        payload_body=json.dumps(payload),
        signature='test_sig'
    )
    
    success = PaymentUseCases.process_webhook(webhook_cmd)
    print(f"Webhook processed: {success}")

    # 6. Verify System State
    order.refresh_from_db()
    print(f"Order Status: {order.status} (Expected: PENDING)")
    
    entries = LedgerEntry.objects.filter(restaurant_id=restaurant.id)
    print("\n--- Finance Ledger ---")
    for entry in entries:
        print(f"[{entry.entry_type}] Amount: {entry.amount} | Balance After: {entry.balance_after}")

if __name__ == "__main__":
    run_simulation()
