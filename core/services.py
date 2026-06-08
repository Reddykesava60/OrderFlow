import logging
from django.db import transaction
from django.contrib.auth.hashers import make_password, check_password
from core.models import Customer, RestaurantCustomerCounter, OwnerAuditLog

logger = logging.getLogger(__name__)


def validate_customer_pin_value(pin):
    pin = str(pin or '').strip()
    if not pin.isdigit() or not (4 <= len(pin) <= 6):
        raise ValueError("PIN must be 4 to 6 digits.")
    return pin


def _next_customer_serial(restaurant):
    """
    Assign sequential customer serial number per restaurant.
    Uses SELECT FOR UPDATE — must be called inside transaction.atomic().
    """
    counter, _ = RestaurantCustomerCounter.objects.select_for_update().get_or_create(
        restaurant=restaurant,
        defaults={'last_number': 0},
    )
    counter.last_number += 1
    counter.save(update_fields=['last_number'])
    return counter.last_number


def create_customer(restaurant, name, phone, pin, credit_limit=None, owner_user=None):
    """
    Atomic customer creation with sequential serial number.
    """
    pin = validate_customer_pin_value(pin)
    with transaction.atomic():
        serial = _next_customer_serial(restaurant)
        hashed_pin = make_password(pin, hasher='customer_pin')
        customer = Customer.objects.create(
            restaurant=restaurant,
            serial_number=serial,
            name=name,
            phone=phone,
            pin=hashed_pin,
            must_change_pin=True,
            credit_limit=credit_limit,
            balance=0.00
        )
        if owner_user:
            OwnerAuditLog.objects.create(
                restaurant=restaurant,
                user=owner_user,
                customer=customer,
                action=OwnerAuditLog.ActionType.CREATE_CUSTOMER,
                details={'name': name, 'phone': phone, 'credit_limit': str(credit_limit) if credit_limit else None}
            )
    return customer


def update_customer_pin(customer, new_pin, owner_user=None):
    """
    Update a customer's PIN and unset the must_change_pin flag.
    """
    new_pin = validate_customer_pin_value(new_pin)
    customer.pin = make_password(new_pin, hasher='customer_pin')
    customer.must_change_pin = False
    customer.save(update_fields=['pin', 'must_change_pin'])
    if owner_user:
        OwnerAuditLog.objects.create(
            restaurant=customer.restaurant,
            user=owner_user,
            customer=customer,
            action=OwnerAuditLog.ActionType.RESET_PIN,
            details={}
        )
    return customer


def verify_customer_pin(customer, plain_pin):
    """
    Verify customer's PIN safely.
    """
    if not customer.pin:
        return False
    return check_password(plain_pin, customer.pin)


def set_customer_status(customer, is_post_payment_enabled=None, is_blocked=None, credit_limit=False, owner_user=None):
    """
    Helper to update customer status flags.
    Use credit_limit=False to ignore it, None to set unlimited, or a Decimal for a limit.
    """
    update_fields = []
    if is_post_payment_enabled is not None:
        customer.is_post_payment_enabled = is_post_payment_enabled
        update_fields.append('is_post_payment_enabled')
    if is_blocked is not None:
        customer.is_blocked = is_blocked
        update_fields.append('is_blocked')
    if credit_limit is not False:
        customer.credit_limit = credit_limit
        update_fields.append('credit_limit')
        
    if update_fields:
        customer.save(update_fields=update_fields)
        if owner_user:
            details = {}
            if is_post_payment_enabled is not None: details['is_post_payment_enabled'] = is_post_payment_enabled
            if is_blocked is not None: details['is_blocked'] = is_blocked
            if credit_limit is not False: details['credit_limit'] = str(credit_limit) if credit_limit else None
            OwnerAuditLog.objects.create(
                restaurant=customer.restaurant,
                user=owner_user,
                customer=customer,
                action=OwnerAuditLog.ActionType.EDIT_CUSTOMER,
                details=details
            )
    return customer
