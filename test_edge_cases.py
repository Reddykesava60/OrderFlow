import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.base')
django.setup()

from core.models import Restaurant, Customer, MenuItem, ItemType
from core.services import create_customer, update_customer_pin, verify_customer_pin, set_customer_status
from ordering.services import place_post_payment_order, record_customer_payment, CartError
from ordering.models import Order, LedgerEntry

def run_tests():
    restaurant = Restaurant.objects.first()
    print(f"Testing for restaurant: {restaurant.name}")
    
    # 1. Create a fresh customer
    customer = create_customer(
        restaurant=restaurant,
        name="Edge Case User",
        phone="1231231234",
        pin="1234",
        credit_limit=Decimal('100.00')
    )
    print(f"\n[Test 1] Created Customer ID {customer.serial_number} with limit 100.00")
    
    # 2. Test Invalid PIN (Unchanged PIN should fail if must_change_pin is False? No, create_customer sets must_change_pin=True)
    try:
        verify = verify_customer_pin(customer, "1234")
        print(f"[Test 2a] Verification of default PIN: {verify}")
    except Exception as e:
        print(f"[Test 2a] Error: {e}")
        
    update_customer_pin(customer, "4321")
    verify = verify_customer_pin(customer, "4321")
    print(f"[Test 2b] Verification of new PIN: {verify}")
    
    # Get a menu item
    menu_item = MenuItem.objects.filter(restaurant=restaurant).first()
    menu_item.stock = 10
    menu_item.base_price = Decimal('60.00')
    menu_item.save()
    
    cart_lines = [{
        'item_id': str(menu_item.id),
        'quantity': 1,
        'dining_option': 'DINE_IN',
        'spice_level': '',
        'addons': []
    }]
    
    # 3. Test Invalid PIN in checkout
    try:
        place_post_payment_order(restaurant, cart_lines, customer, "9999", "A1")
        print("[Test 3] FAILED: Order placed with wrong PIN!")
    except Exception as e:
        print(f"[Test 3] SUCCESS: Blocked order with wrong PIN. Error: {e}")
        
    # 4. Test Inactive Customer
    set_customer_status(customer, False)
    try:
        place_post_payment_order(restaurant, cart_lines, customer, "4321", "A1")
        print("[Test 4] FAILED: Order placed for inactive customer!")
    except Exception as e:
        print(f"[Test 4] SUCCESS: Blocked inactive customer. Error: {e}")
    set_customer_status(customer, True)
    
    # 5. Test Exceeding Credit Limit (Limit is 100, item is 60. Buying 2 = 120 > 100)
    cart_lines[0]['quantity'] = 2
    try:
        place_post_payment_order(restaurant, cart_lines, customer, "4321", "A1")
        print("[Test 5] FAILED: Order placed exceeding credit limit!")
    except Exception as e:
        print(f"[Test 5] SUCCESS: Blocked exceeding limit. Error: {e}")
        
    # 6. Place valid order
    cart_lines[0]['quantity'] = 1
    order = place_post_payment_order(restaurant, cart_lines, customer, "4321", "A1")
    print(f"[Test 6] SUCCESS: Order {order.order_number} placed. Balance: {customer.balance}")
    
    # 7. Record payment
    record_customer_payment(customer, Decimal('60.00'), 'UPI')
    customer.refresh_from_db()
    print(f"[Test 7] SUCCESS: Payment recorded. New Balance: {customer.balance}")

if __name__ == "__main__":
    run_tests()
