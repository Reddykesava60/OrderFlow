from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


class PaymentGatewayError(Exception):
    pass


class PaymentConfigurationError(Exception):
    pass


class PaymentSecurityError(Exception):
    pass


@dataclass(frozen=True)
class ResolvedPaymentConfig:
    provider: str
    mode: str
    credentials: dict[str, Any]
    webhook_secret: str = ""
    tenant_config: Any = None
    is_legacy: bool = False
    account_source: str = "PLATFORM"   # GatewayAccountSource value
    account_identifier: str = ""       # e.g. masked key_id or account name


@dataclass(frozen=True)
class PaymentCreateRequest:
    order_id: str
    order_number: int
    restaurant_name: str
    restaurant_slug: str
    customer_name: str
    amount: Decimal
    currency: str
    expires_at: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentCreateResult:
    provider_order_id: str = ""
    provider_payment_id: str = ""
    provider_qr_id: str = ""
    intent_uri: str = ""
    qr_image_url: str = ""
    qr_payload: str = ""
    expires_at: Any = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderPaymentStatus:
    state: str
    provider_payment_id: str = ""
    amount: Decimal | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderWebhookEvent:
    kind: str
    provider_order_id: str = ""
    provider_payment_id: str = ""
    provider_refund_id: str = ""
    provider_event_id: str = ""
    idempotency_key: str = ""
    amount: Decimal | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentGatewayInterface(Protocol):
    provider: str

    def create_payment(self, request: PaymentCreateRequest, config: ResolvedPaymentConfig) -> PaymentCreateResult:
        ...

    def verify_payment(self, provider_payment_id: str, config: ResolvedPaymentConfig) -> ProviderPaymentStatus:
        ...

    def get_payment_status(self, provider_order_id: str, config: ResolvedPaymentConfig) -> ProviderPaymentStatus:
        ...


class IntentPaymentInterface(Protocol):
    def generate_intent(self, request: PaymentCreateRequest, config: ResolvedPaymentConfig) -> str:
        ...


class QRPaymentInterface(Protocol):
    def generate_qr(self, request: PaymentCreateRequest, config: ResolvedPaymentConfig) -> PaymentCreateResult:
        ...


class WebhookVerificationInterface(Protocol):
    def verify_webhook(self, raw_body: bytes, headers: dict[str, str], config: ResolvedPaymentConfig) -> bool:
        ...

    def parse_webhook(self, payload: dict[str, Any], headers: dict[str, str]) -> ProviderWebhookEvent:
        ...
