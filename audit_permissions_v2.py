import os
import django
from collections import defaultdict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.dev')
django.setup()

from core.models import OwnerAuditLog
from ordering.models import RestaurantLedger, Order, OrderItem
from kitchen.models import PaymentEvent
from django.conf import settings
import dj_database_url

print('--- AUDIT LOG START ---')

db_url = os.environ.get('DATABASE_URL', '')
is_prod = 'supabase' in db_url.lower() or 'production' in db_url.lower()
print(f"DATABASE CONNECTED: {db_url.split('@')[-1] if '@' in db_url else 'Unknown'}")
print(f"IS PRODUCTION: {is_prod}")
print("-" * 30)

print("\n[Cash Collections (RestaurantLedger joined with PaymentEvent)]")
cash_ledgers = RestaurantLedger.objects.filter(entry_type=RestaurantLedger.EntryType.DEBIT_CASH_COLLECTED).select_related('order')

checked_ledger_count = 0
unauth_ledger_count = 0

for ledger in cash_ledgers:
    if not ledger.order:
        continue
    event = PaymentEvent.objects.filter(order=ledger.order, event_type=PaymentEvent.EventType.CASH_COLLECTED).first()
    if event and event.staff_user:
        checked_ledger_count += 1
        user = event.staff_user
        if not (user.is_owner or user.allow_cash_collection):
            print(f"WARNING: User {user.username} collected cash for Order {ledger.order.order_number} without permission! Amount: {ledger.amount} on {ledger.created_at}")
            unauth_ledger_count += 1

print(f"Checked {checked_ledger_count} ledger entries with identifiable staff users. Found {unauth_ledger_count} unauthorized.")

print("\n[Historical Permission State Check]")
permission_changes = OwnerAuditLog.objects.filter(action=OwnerAuditLog.ActionType.TOGGLE_STAFF_PERMISSION)
print(f"Found {permission_changes.count()} permission change events in OwnerAuditLog.")
if permission_changes.exists():
    for pc in permission_changes:
        print(f" - {pc.created_at}: {pc.action} by {pc.user} details: {pc.details}")

print("\n[Order/Item Status Changes]")
order_fields = [f.name for f in Order._meta.get_fields()]
item_fields = [f.name for f in OrderItem._meta.get_fields()]

has_order_actor = any('user' in f or 'by' in f or 'staff' in f for f in order_fields)
has_item_actor = any('user' in f or 'by' in f or 'staff' in f for f in item_fields)

if not has_order_actor and not has_item_actor:
    print("CANNOT VERIFY FROM EXISTING DATA: Order and OrderItem models do not contain an actor/user field to track who changed the status.")
else:
    print(f"Order fields matching actor: {[f for f in order_fields if 'user' in f or 'by' in f or 'staff' in f]}")
    print(f"OrderItem fields matching actor: {[f for f in item_fields if 'user' in f or 'by' in f or 'staff' in f]}")

print("\n[OwnerRequiredMixin Coverage]")
print("OwnerAuditLog only tracks specific POST actions (config updates, staff management). It DOES NOT track GET requests to /owner/ views (e.g. just viewing the config or dashboard). Thus, unauthorized read-only access via the bug is NOT captured in any database log.")

print('--- AUDIT LOG END ---')
