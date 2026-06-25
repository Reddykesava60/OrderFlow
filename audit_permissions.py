import os
import django
from collections import defaultdict
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.dev')
django.setup()

from core.models import OwnerAuditLog, User, Restaurant
from ordering.models import RestaurantLedger, Order
from kitchen.models import PaymentEvent

print("--- AUDITING PERMISSIONS ---")

# 1. Check OwnerAuditLog for non-owners
print("\n[OwnerAuditLog]")
owner_logs = OwnerAuditLog.objects.select_related('user').all()
for log in owner_logs:
    if log.user and not log.user.is_owner:
        # Check if the user's role was changed to STAFF at some point?
        # But if they were STAFF when they performed the action, it's a bug.
        print(f"WARNING: User {log.user.username} (Role: {log.user.role}) performed Owner action: {log.action} on {log.created_at}")

# 2. Check RestaurantLedger for unauthorized Cash Collection
print("\n[Cash Collections (RestaurantLedger)]")
cash_ledgers = RestaurantLedger.objects.filter(entry_type=RestaurantLedger.EntryType.DEBIT_CASH_COLLECTED).select_related('created_by')
for ledger in cash_ledgers:
    user = ledger.created_by
    if user:
        if not (user.is_owner or user.allow_cash_collection):
            print(f"WARNING: User {user.username} collected cash for Order {ledger.order_id} without permission! Amount: {ledger.amount} on {ledger.created_at}")

# 3. Check PaymentEvent for unauthorized cash collections
print("\n[Cash Collections (PaymentEvent)]")
payment_events = PaymentEvent.objects.filter(event_type=PaymentEvent.EventType.CASH_COLLECTED).select_related('user')
for event in payment_events:
    user = event.user
    if user:
        if not (user.is_owner or user.allow_cash_collection):
            print(f"WARNING: User {user.username} recorded PaymentEvent (Cash) without permission! Amount: {event.amount} on {event.created_at}")

# 4. Check Orders for Completion by unauthorized users
print("\n[Order Completions]")
# Order does not have created_by, but maybe PaymentEvent or something has it?
# Let's check PaymentEvent for order completion... Wait, PaymentEvent is just payments.
# Let's check if there is an order audit or KDS audit.
print("Checking if any other logs exist for order completions...")

