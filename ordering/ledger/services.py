from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from typing import Optional

from core.models import Customer, Restaurant, User
from ordering.models import LedgerEntry, Order, RestaurantLedger, Settlement, PaymentTransaction


@dataclass
class CustomerLedgerService:
    """Service boundary for atomic customer balance and ledger writes."""

    @transaction.atomic
    def add_order_debt(self, *, customer: Customer, order: Order, amount: Decimal, description: str) -> LedgerEntry:
        locked_customer = Customer.objects.select_for_update().get(pk=customer.pk)
        locked_customer.balance += amount
        locked_customer.save(update_fields=["balance"])

        return LedgerEntry.objects.create(
            restaurant=locked_customer.restaurant,
            customer=locked_customer,
            entry_type=LedgerEntry.EntryType.ORDER,
            amount=amount,
            balance_after=locked_customer.balance,
            order=order,
            description=description,
        )

    @transaction.atomic
    def add_customer_payment(self, *, customer: Customer, amount: Decimal, description: str) -> LedgerEntry:
        locked_customer = Customer.objects.select_for_update().get(pk=customer.pk)
        locked_customer.balance -= amount
        locked_customer.save(update_fields=["balance"])

        return LedgerEntry.objects.create(
            restaurant=locked_customer.restaurant,
            customer=locked_customer,
            entry_type=LedgerEntry.EntryType.PAYMENT,
            amount=-amount,
            balance_after=locked_customer.balance,
            description=description,
        )


@dataclass
class RestaurantLedgerService:
    """Service boundary for atomic platform-restaurant ledger writes."""

    @transaction.atomic
    def record_payment(
        self,
        *,
        restaurant: Restaurant,
        order: Order,
        payment_transaction: Optional[PaymentTransaction],
        gross_amount: Decimal,
        platform_fee: Decimal,
    ) -> tuple[RestaurantLedger, RestaurantLedger]:
        """
        Records the revenue from a payment and the deduction of the platform fee.
        """
        # Lock restaurant to serialize ledger writes
        locked_restaurant = Restaurant.objects.select_for_update().get(pk=restaurant.pk)
        
        last_entry = RestaurantLedger.objects.filter(restaurant=locked_restaurant).order_by('-created_at').first()
        current_balance = last_entry.balance_after if last_entry else Decimal('0.00')

        # 1. Credit the gross amount
        new_balance = current_balance + gross_amount
        credit_entry = RestaurantLedger.objects.create(
            restaurant=locked_restaurant,
            order=order,
            payment_transaction=payment_transaction,
            entry_type=RestaurantLedger.EntryType.CREDIT_ORDER,
            amount=gross_amount,
            balance_after=new_balance,
            reference=f"Payment for order {order.id}",
        )

        # 2. Debit the platform fee
        new_balance -= platform_fee
        fee_entry = RestaurantLedger.objects.create(
            restaurant=locked_restaurant,
            order=order,
            payment_transaction=payment_transaction,
            entry_type=RestaurantLedger.EntryType.DEBIT_PLATFORM_FEE,
            amount=-platform_fee,
            balance_after=new_balance,
            reference=f"Platform fee for order {order.id}",
        )

        return credit_entry, fee_entry

    @transaction.atomic
    def record_settlement(
        self,
        *,
        settlement: Settlement,
        created_by: Optional[User] = None,
    ) -> RestaurantLedger:
        locked_restaurant = Restaurant.objects.select_for_update().get(pk=settlement.restaurant.pk)
        last_entry = RestaurantLedger.objects.filter(restaurant=locked_restaurant).order_by('-created_at').first()
        current_balance = last_entry.balance_after if last_entry else Decimal('0.00')

        new_balance = current_balance - settlement.amount
        return RestaurantLedger.objects.create(
            restaurant=locked_restaurant,
            settlement=settlement,
            entry_type=RestaurantLedger.EntryType.SETTLEMENT_PAID,
            amount=-settlement.amount,
            balance_after=new_balance,
            reference=f"Settlement {settlement.id}",
            created_by=created_by,
        )

    @transaction.atomic
    def record_cash_payment(
        self,
        *,
        restaurant: Restaurant,
        order: Order,
        gross_amount: Decimal,
        platform_fee: Decimal,
    ) -> tuple[RestaurantLedger, RestaurantLedger, RestaurantLedger]:
        """
        Records a cash payment. Credits the gross revenue, debits the cash collected 
        by the restaurant (since the platform isn't holding it), and debits the platform fee.
        Net effect on platform balance: -platform_fee (restaurant owes platform).
        """
        locked_restaurant = Restaurant.objects.select_for_update().get(pk=restaurant.pk)
        last_entry = RestaurantLedger.objects.filter(restaurant=locked_restaurant).order_by('-created_at').first()
        current_balance = last_entry.balance_after if last_entry else Decimal('0.00')

        # 1. Credit the gross amount
        new_balance = current_balance + gross_amount
        credit_entry = RestaurantLedger.objects.create(
            restaurant=locked_restaurant,
            order=order,
            entry_type=RestaurantLedger.EntryType.CREDIT_ORDER,
            amount=gross_amount,
            balance_after=new_balance,
            reference=f"Cash Payment for order {order.id}",
        )

        # 2. Debit the cash collected (since restaurant keeps the cash)
        new_balance -= gross_amount
        cash_debit_entry = RestaurantLedger.objects.create(
            restaurant=locked_restaurant,
            order=order,
            entry_type=RestaurantLedger.EntryType.DEBIT_CASH_COLLECTED,
            amount=-gross_amount,
            balance_after=new_balance,
            reference=f"Cash Collected by Restaurant for order {order.id}",
        )

        # 3. Debit the platform fee
        new_balance -= platform_fee
        fee_entry = RestaurantLedger.objects.create(
            restaurant=locked_restaurant,
            order=order,
            entry_type=RestaurantLedger.EntryType.DEBIT_PLATFORM_FEE,
            amount=-platform_fee,
            balance_after=new_balance,
            reference=f"Platform fee for cash order {order.id}",
        )

        return credit_entry, cash_debit_entry, fee_entry

    @transaction.atomic
    def record_post_payment(
        self,
        *,
        restaurant: Restaurant,
        order: Order,
        gross_amount: Decimal,
        platform_fee: Decimal,
    ) -> tuple[RestaurantLedger, RestaurantLedger, RestaurantLedger]:
        """
        Records a post-payment order. Credits the gross revenue, debits the post payment collected 
        by the restaurant, and debits the platform fee.
        """
        locked_restaurant = Restaurant.objects.select_for_update().get(pk=restaurant.pk)
        last_entry = RestaurantLedger.objects.filter(restaurant=locked_restaurant).order_by('-created_at').first()
        current_balance = last_entry.balance_after if last_entry else Decimal('0.00')

        # 1. Credit the gross amount
        new_balance = current_balance + gross_amount
        credit_entry = RestaurantLedger.objects.create(
            restaurant=locked_restaurant,
            order=order,
            entry_type=RestaurantLedger.EntryType.CREDIT_ORDER,
            amount=gross_amount,
            balance_after=new_balance,
            reference=f"Post Payment for order {order.id}",
        )

        # 2. Debit the post payment collected
        new_balance -= gross_amount
        post_debit_entry = RestaurantLedger.objects.create(
            restaurant=locked_restaurant,
            order=order,
            entry_type=RestaurantLedger.EntryType.DEBIT_POST_PAYMENT,
            amount=-gross_amount,
            balance_after=new_balance,
            reference=f"Post Payment Collected for order {order.id}",
        )

        # 3. Debit the platform fee
        new_balance -= platform_fee
        fee_entry = RestaurantLedger.objects.create(
            restaurant=locked_restaurant,
            order=order,
            entry_type=RestaurantLedger.EntryType.DEBIT_PLATFORM_FEE,
            amount=-platform_fee,
            balance_after=new_balance,
            reference=f"Platform fee for post payment order {order.id}",
        )

        return credit_entry, post_debit_entry, fee_entry
