from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class PaymentCommand:
    order_id: str
    provider: str
    idempotency_key: str | None = None


@dataclass(frozen=True)
class PaymentResult:
    payment_id: str
    order_id: str
    state: str
    status_url: str
    retry_url: str


class PaymentApplicationService(Protocol):
    """Application-layer boundary for payment orchestration."""

    def create_payment(self, command: PaymentCommand) -> PaymentResult:
        ...


@dataclass(frozen=True)
class LedgerOrderCommand:
    customer_id: str
    order_id: str
    amount: Decimal
    description: str


@dataclass(frozen=True)
class LedgerPaymentCommand:
    customer_id: str
    amount: Decimal
    description: str


class LedgerApplicationService(Protocol):
    """Application-layer boundary for customer balance and ledger mutations."""

    def record_order_debt(self, command: LedgerOrderCommand) -> str:
        ...

    def record_customer_payment(self, command: LedgerPaymentCommand) -> str:
        ...
