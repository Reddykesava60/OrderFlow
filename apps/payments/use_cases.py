import uuid
import json
import logging
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from .dtos import InitializePaymentCommand, ProcessWebhookCommand
from .models import PaymentTransaction, TenantPaymentConfig, PaymentState, GatewayAccountSource, WebhookLog
from shared.events import DomainEvent
from shared.event_bus import event_bus

logger = logging.getLogger(__name__)

class OrderPaidEvent(DomainEvent):
    def __init__(self, order_id: uuid.UUID):
        self.order_id = order_id

class GatewayService:
    """Interface to external payment gateways."""
    @staticmethod
    def create_razorpay_order(amount: float, receipt: str, config: TenantPaymentConfig) -> str:
        # Stub implementation. In reality, invokes razorpay SDK using config credentials.
        return f"order_{uuid.uuid4().hex[:14]}"
    
    @staticmethod
    def verify_webhook_signature(payload: str, signature: str, secret: str) -> bool:
        # Stub
        return True

class PaymentUseCases:
    @staticmethod
    def initialize_payment(cmd: InitializePaymentCommand) -> PaymentTransaction:
        if cmd.idempotency_key:
            existing = PaymentTransaction.objects.filter(idempotency_key=cmd.idempotency_key).first()
            if existing:
                return existing

        with transaction.atomic():
            # Determine routing: Restaurant's own credentials or Platform credentials
            config = TenantPaymentConfig.objects.filter(restaurant_id=cmd.restaurant_id, is_active=True).first()
            source = GatewayAccountSource.RESTAURANT if config else GatewayAccountSource.PLATFORM

            tx = PaymentTransaction.objects.create(
                restaurant_id=cmd.restaurant_id,
                order_id=cmd.order_id,
                tenant_config=config,
                provider='razorpay',
                state=PaymentState.INITIATED,
                amount=cmd.amount,
                currency=cmd.currency,
                idempotency_key=cmd.idempotency_key or uuid.uuid4(),
                gateway_account_source=source,
                expires_at=timezone.now() + timedelta(minutes=15)
            )

            # Call gateway
            amount_in_paise = int(cmd.amount * 100)
            provider_order_id = GatewayService.create_razorpay_order(
                amount=amount_in_paise,
                receipt=str(tx.id),
                config=config
            )
            
            tx.provider_order_id = provider_order_id
            tx.save()

            return tx

    @staticmethod
    def process_webhook(cmd: ProcessWebhookCommand) -> bool:
        """
        Handles incoming webhooks, validates signature, and transitions payment state.
        Emits OrderPaidEvent if successful.
        """
        try:
            payload = json.loads(cmd.payload_body)
            event_name = payload.get('event')
            provider_order_id = payload.get('payload', {}).get('payment', {}).get('entity', {}).get('order_id')
            
            if not provider_order_id:
                return False

            tx = PaymentTransaction.objects.select_for_update().filter(provider_order_id=provider_order_id).first()
            if not tx:
                return False

            # In a real impl, fetch the secret associated with tx.tenant_config
            secret = "stub_secret"
            is_valid = GatewayService.verify_webhook_signature(cmd.payload_body, cmd.signature, secret)

            WebhookLog.objects.create(
                restaurant_id=tx.restaurant_id,
                payment_transaction=tx,
                provider=cmd.provider,
                signature_valid=is_valid,
                payload_hash=cmd.signature, # simplified
                raw_payload=cmd.payload_body,
                processed_at=timezone.now()
            )

            if not is_valid:
                logger.warning(f"Invalid webhook signature for tx {tx.id}")
                return False

            if event_name == 'payment.captured' and tx.state != PaymentState.PAID:
                tx.state = PaymentState.PAID
                tx.paid_at = timezone.now()
                tx.save()

                # Publish event to decouple order state transition and ledger entries
                event_bus.publish(OrderPaidEvent(order_id=tx.order_id))

            return True

        except Exception as e:
            logger.exception("Error processing webhook")
            return False
