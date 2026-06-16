import django.dispatch

# Provides args: order, payment, fee_amount
order_paid = django.dispatch.Signal()

# Provides args: order, reason
order_cancelled = django.dispatch.Signal()

# Provides args: order
inventory_released = django.dispatch.Signal()
