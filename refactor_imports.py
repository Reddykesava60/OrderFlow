import os
import re

checkout_funcs = {'CartError', 'PaymentConfigurationError', 'get_restaurant_payment_config', 'validate_and_price_cart', 'compute_order_total', 'place_cash_order', 'place_upi_order', 'place_post_payment_order', 'create_razorpay_order'}
order_funcs = {'expire_overdue_unpaid_cash_orders', 'sync_order_status', 'confirm_cash_payment', 'record_customer_payment', 'confirm_upi_payment', 'cancel_upi_payment', 'expire_unpaid_cash_order', 'get_cash_payment_timeout_minutes', '_create_fee_record'}
inventory_funcs = {'_restore_item_availability_after_stock_return', '_lock_and_decrement_stock', '_create_stock_reservations'}

def fix_imports(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    new_lines = []
    changed = False

    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r'^(from ordering\.services import |from \.services import )(.*)', line)
        if match:
            changed = True
            prefix = match.group(1)
            imports_str = match.group(2)
            
            while i + 1 < len(lines) and '(' in imports_str and ')' not in imports_str:
                i += 1
                imports_str += ' ' + lines[i].strip()
            
            imports_str = imports_str.replace('(', '').replace(')', '')
            funcs = [x.strip() for x in imports_str.split(',') if x.strip()]
            
            checkout_used = [f for f in funcs if f in checkout_funcs]
            orders_used = [f for f in funcs if f in order_funcs]
            inventory_used = [f for f in funcs if f in inventory_funcs]
            unknown_used = [f for f in funcs if f not in checkout_funcs and f not in order_funcs and f not in inventory_funcs]

            is_relative = prefix.startswith('from .')
            
            if checkout_used:
                mod = '.checkout.services' if is_relative else 'ordering.checkout.services'
                new_lines.append(f'from {mod} import {", ".join(checkout_used)}')
            if orders_used:
                mod = '.orders.services' if is_relative else 'ordering.orders.services'
                new_lines.append(f'from {mod} import {", ".join(orders_used)}')
            if inventory_used:
                mod = '.inventory.services' if is_relative else 'ordering.inventory.services'
                new_lines.append(f'from {mod} import {", ".join(inventory_used)}')
            if unknown_used:
                new_lines.append(f'{prefix}{", ".join(unknown_used)}')
        else:
            new_lines.append(line)
        i += 1
        
    if changed:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_lines))
        print(f'Fixed {file_path}')

for root, _, files in os.walk('.'):
    if '.venv' in root or '.git' in root:
        continue
    for f in files:
        if f.endswith('.py'):
            fix_imports(os.path.join(root, f))
