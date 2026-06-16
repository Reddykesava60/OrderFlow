import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.base')
django.setup()

from core.models import Restaurant, Customer, MenuItem, ItemType
from core.services import create_customer, update_customer_pin, verify_customer_pin
from ordering.checkout.services import place_post_payment_order
from ordering.orders.services import record_customer_payment
from ordering.models import Order, LedgerEntry

def run_test():
    restaurant = Restaurant.objects.first()
    if not restaurant:
        restaurant = Restaurant.objects.create(name="Test Rest", slug="test-rest")
        
    print(f"Testing for restaurant: {restaurant.name}")
    
    # 1. Create a customer
    customer = create_customer(
        restaurant=restaurant,
        name="John Doe",
        phone="1234567890",
        pin="1234",
        credit_limit=Decimal('500.00')
    )
    print(f"Created customer: {customer.serial_number} - {customer.name}, limit: {customer.credit_limit}")
    
    # 2. Update PIN
    update_customer_pin(customer, "5678")
    is_valid = verify_customer_pin(customer, "5678")
    print(f"PIN update & verification successful: {is_valid}")
    
    # 3. Create a test menu item
    item_type, _ = ItemType.objects.get_or_create(restaurant=restaurant, name="Main")
    menu_item, _ = MenuItem.objects.get_or_create(
        restaurant=restaurant,
        name="Burger",
        defaults={
            'base_price': Decimal('150.00'),
            'item_type': item_type,
            'is_available': True,
            'stock': 10
        }
    )
    # Give it some stock if out
    if menu_item.stock == 0:
        menu_item.stock = 10
        menu_item.is_available = True
        menu_item.save()
        
    # 4. Try Post Payment Order
    cart_lines = [{
        'item_id': str(menu_item.id),
        'quantity': 2,
        'dining_option': 'DINE_IN',
        'spice_level': '',
        'addons': []
    }]
    
    print(f"Attempting post payment order. Cart: {cart_lines}")
    try:
        order = place_post_payment_order(
            restaurant=restaurant,
            cart_lines=cart_lines,
            customer=customer,
            plain_pin="5678",
            table_number="A1",
            idempotency_key=None
        )
        print(f"Order created successfully! Order #{order.order_number}, Status: {order.status}, Total: {order.total}")
        
        # Reload customer to check balance
        customer.refresh_from_db()
        print(f"Customer Balance after order: {customer.balance}")
        
    except Exception as e:
        print(f"Error placing order: {e}")
        return
        
    # 5. Record Payment
    print("Recording payment of 200.00")
    record_customer_payment(customer, Decimal('200.00'), 'Cash')
    
    customer.refresh_from_db()
    print(f"Customer Balance after payment: {customer.balance}")
    
    # 6. Check Ledger
    entries = LedgerEntry.objects.filter(customer=customer).order_by('created_at')
    print("Ledger Entries:")
    for e in entries:
        print(f"  - {e.entry_type}: {e.amount} | Balance After: {e.balance_after} | {e.description}")
        
if __name__ == "__main__":
    run_test()
