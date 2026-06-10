import hashlib
import json
import logging
import uuid
from decimal import Decimal
from datetime import timezone as dt_timezone

from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import PlatformFeeRecord
from kitchen.models import PaymentEvent
from kitchen.services import broadcast_payment_update, trigger_kds_refresh
from ordering.models import (
    Order,
    PaymentAttempt,
    PaymentProvider,
    PaymentReconciliationLog,
    PaymentState,
    PaymentTransaction,
    StockReservation,
    WebhookLog,
)
from ordering.services import _create_fee_record

from .contracts import PaymentCreateRequest, PaymentGatewayError, ProviderWebhookEvent
from .providers import get_gateway
from .resolver import resolve_payment_config, resolve_payment_config_for_transaction
from .upi import build_app_intent_urls

logger = logging.getLogger(__name__)


ACTIVE_STATES = [PaymentState.PENDING, PaymentState.INITIATED, PaymentState.PROCESSING, PaymentState.PAID]
PAYMENT_ACCESS_TOKEN_SALT = "dineflow.payment-access"
PAYMENT_WEBHOOK_REPLAY_WINDOW_SECONDS = 300
SAFE_WEBHOOK_HEADER_NAMES = {
    "content-type",
    "user-agent",
    "x-idempotency-header",
    "x-razorpay-event-id",
    "x-razorpay-timestamp",
    "x-webhook-timestamp",
}


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return uuid.uuid4()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def get_payment_access_token(payment):
    return signing.dumps(
        {
            "payment_id": str(payment.id),
            "order_id": str(payment.order_id),
            "restaurant_id": str(payment.restaurant_id),
        },
        salt=PAYMENT_ACCESS_TOKEN_SALT,
    )


def verify_payment_access_token(payment, token, *, max_age=86400):
    if not token:
        return False
    try:
        data = signing.loads(token, salt=PAYMENT_ACCESS_TOKEN_SALT, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return False
    return (
        data.get("payment_id") == str(payment.id)
        and data.get("order_id") == str(payment.order_id)
        and data.get("restaurant_id") == str(payment.restaurant_id)
    )


def _parse_webhook_timestamp(headers):
    raw_timestamp = (
        headers.get("x-webhook-timestamp")
        or headers.get("X-Webhook-Timestamp")
        or headers.get("x-razorpay-timestamp")
        or headers.get("X-Razorpay-Timestamp")
    )
    if not raw_timestamp:
        return None

    parsed = None
    try:
        parsed = timezone.datetime.fromtimestamp(float(raw_timestamp), tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError):
        parsed = parse_datetime(raw_timestamp)

    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone=dt_timezone.utc)
    return parsed


def _is_webhook_timestamp_fresh(headers):
    parsed = _parse_webhook_timestamp(headers)
    if parsed is None:
        # Missing timestamp is suspicious but allowed for backward compatibility
        # with older Razorpay webhook configurations.
        logger.warning(
            "payment_webhook_missing_timestamp — allowing for backward compatibility"
        )
        return True
    age = abs((timezone.now() - parsed).total_seconds())
    if age > PAYMENT_WEBHOOK_REPLAY_WINDOW_SECONDS:
        logger.warning(
            "payment_webhook_stale_timestamp age_seconds=%.0f max_allowed=%d",
            age, PAYMENT_WEBHOOK_REPLAY_WINDOW_SECONDS,
        )
    return age <= PAYMENT_WEBHOOK_REPLAY_WINDOW_SECONDS


def _safe_webhook_headers(headers):
    return {
        key: value
        for key, value in dict(headers).items()
        if key.lower() in SAFE_WEBHOOK_HEADER_NAMES
    }


class PaymentOrchestratorService:
    def create_payment_for_order(self, order, *, provider=None, idempotency_key=None):
        with transaction.atomic():
            locked_order = Order.objects.select_for_update().select_related("restaurant").get(pk=order.pk)

            existing = (
                PaymentTransaction.objects
                .select_for_update()
                .select_related("order", "restaurant")
                .filter(order=locked_order, state__in=ACTIVE_STATES)
                .order_by("-created_at")
                .first()
            )
            if existing:
                return self.serialize(existing)

            resolved = resolve_payment_config(locked_order.restaurant, provider)
            gateway = get_gateway(resolved.provider)
            expires_at = timezone.now() + timezone.timedelta(minutes=15)
            payment_key = _uuid(idempotency_key)

            try:
                payment = PaymentTransaction.objects.create(
                    restaurant=locked_order.restaurant,
                    order=locked_order,
                    tenant_config=resolved.tenant_config,
                    provider=resolved.provider,
                    state=PaymentState.PENDING,
                    amount=locked_order.total,
                    currency="INR",
                    idempotency_key=payment_key,
                    expires_at=expires_at,
                    gateway_account_source=resolved.account_source,
                    gateway_account_identifier=resolved.account_identifier,
                )
            except IntegrityError:
                payment = PaymentTransaction.objects.select_related("order", "restaurant").get(idempotency_key=payment_key)
                return self.serialize(payment)

        request = PaymentCreateRequest(
            order_id=str(locked_order.id),
            order_number=locked_order.order_number,
            restaurant_name=locked_order.restaurant.name,
            restaurant_slug=locked_order.restaurant.slug,
            customer_name=locked_order.customer_name,
            amount=locked_order.total,
            currency="INR",
            expires_at=expires_at,
            metadata={"payment_transaction_id": str(payment.id)},
        )
        result = gateway.create_payment(request, resolved)

        with transaction.atomic():
            payment = PaymentTransaction.objects.select_for_update().get(pk=payment.pk)
            payment.provider_order_id = result.provider_order_id
            payment.provider_payment_id = result.provider_payment_id
            payment.provider_qr_id = result.provider_qr_id
            payment.intent_uri = result.intent_uri
            payment.qr_image_url = result.qr_image_url
            payment.qr_payload = result.qr_payload
            payment.expires_at = result.expires_at or expires_at
            payment.metadata = {"create_response": result.raw_response}
            payment.transition_to(PaymentState.INITIATED)
            payment.version += 1
            payment.save(update_fields=[
                "provider_order_id", "provider_payment_id", "provider_qr_id",
                "intent_uri", "qr_image_url", "qr_payload", "expires_at",
                "metadata", "state", "version", "updated_at",
            ])
            PaymentAttempt.objects.create(
                payment_transaction=payment,
                restaurant=payment.restaurant,
                attempt_no=payment.attempts.count() + 1,
                method=PaymentAttempt.Method.QR,
                provider_attempt_id=result.provider_qr_id or result.provider_order_id,
                request_payload_hash=_hash(request.__dict__),
                response_payload=result.raw_response,
                expires_at=payment.expires_at,
            )
            PaymentEvent.objects.create(
                order=payment.order,
                order_ref=payment.order.order_ref_snapshot,
                restaurant=payment.restaurant,
                event_type=PaymentEvent.EventType.RAZORPAY_INITIATED if payment.provider == PaymentProvider.RAZORPAY else PaymentEvent.EventType.DIGITAL_PAYMENT_INITIATED,
                amount=payment.amount,
                razorpay_payment_id=payment.provider_payment_id,
            )
            if payment.provider == PaymentProvider.RAZORPAY and payment.provider_order_id:
                Order.objects.filter(pk=order.pk).update(razorpay_order_id=payment.provider_order_id)

        trigger_kds_refresh(payment.restaurant_id)
        broadcast_payment_update(payment.restaurant_id, payment.id, payment.state, payment.order_id)
        return self.serialize(payment)

    def serialize(self, payment):
        payment = PaymentTransaction.objects.select_related("order", "restaurant").get(pk=payment.pk)
        seconds_left = max(0, int((payment.expires_at - timezone.now()).total_seconds())) if payment.expires_at else 0
        access_token = get_payment_access_token(payment)
        return {
            "status": "payment_pending" if payment.state != PaymentState.PAID else "paid",
            "payment_id": str(payment.id),
            "order_id": str(payment.order_id),
            "order_number": payment.order.order_number,
            "provider": payment.provider,
            "state": payment.state,
            "amount": str(payment.amount),
            "total_paise": int(payment.amount * Decimal("100")),
            "currency": payment.currency,
            "intent_uri": payment.intent_uri,
            "intent_urls": build_app_intent_urls(payment.intent_uri),
            "qr_image_url": payment.qr_image_url,
            "qr_payload": payment.qr_payload,
            "expires_at": payment.expires_at.isoformat() if payment.expires_at else None,
            "seconds_left": seconds_left,
            "access_token": access_token,
            "status_url": f"/payments/status/{payment.id}/?token={access_token}",
            "verify_url": f"/payments/verify/",
            "retry_url": f"/payments/retry/{payment.id}/?token={access_token}",
            "receipt_url": f"/r/{payment.order.restaurant.slug}/receipt/{payment.order.id}/",
        }


class PaymentVerificationService:
    def verify_payment(self, payment):
        resolved = resolve_payment_config_for_transaction(payment)
        status = get_gateway(payment.provider).get_payment_status(payment.provider_order_id, resolved)
        kind = "payment_paid" if status.state == PaymentState.PAID else "payment_failed" if status.state == PaymentState.FAILED else "ignored"
        event = ProviderWebhookEvent(
            kind=kind,
            provider_order_id=payment.provider_order_id,
            provider_payment_id=status.provider_payment_id,
            amount=status.amount,
            raw=status.raw_response,
        )
        if kind != "ignored":
            return PaymentMutationService().apply_provider_event(payment, event)
        if payment.state == PaymentState.INITIATED:
            with transaction.atomic():
                payment = PaymentTransaction.objects.select_for_update().get(pk=payment.pk)
                if payment.state == PaymentState.INITIATED:
                    payment.transition_to(PaymentState.PROCESSING)
                    payment.version += 1
                    payment.save(update_fields=["state", "version", "updated_at"])
        return payment


class PaymentRetryService:
    def retry_payment(self, payment):
        if payment.state == PaymentState.PAID:
            return PaymentOrchestratorService().serialize(payment)
        with transaction.atomic():
            payment = PaymentTransaction.objects.select_for_update().select_related("order").get(pk=payment.pk)
            if payment.state in (PaymentState.PAID, PaymentState.REFUNDED):
                return PaymentOrchestratorService().serialize(payment)
            payment.transition_to(PaymentState.EXPIRED)
            payment.version += 1
            payment.save(update_fields=["state", "version", "updated_at"])
        return PaymentOrchestratorService().create_payment_for_order(payment.order, provider=payment.provider)


class PaymentMutationService:
    def apply_provider_event(self, payment, event):
        if event.kind == "payment_paid":
            return self.mark_paid(payment, event)
        if event.kind == "payment_failed":
            return self.mark_failed(payment, event)
        return payment

    def mark_paid(self, payment, event):
        with transaction.atomic():
            payment = PaymentTransaction.objects.select_for_update().select_related("order", "restaurant").get(pk=payment.pk)
            order = Order.objects.select_for_update().select_related("restaurant").get(pk=payment.order_id)
            if payment.state == PaymentState.PAID:
                return payment
            if event.amount is not None and event.amount != payment.amount:
                raise PaymentGatewayError(f"Payment amount mismatch for {payment.id}")
            if order.restaurant_id != payment.restaurant_id:
                raise PaymentGatewayError("Payment tenant mismatch.")

            StockReservation.objects.select_for_update().filter(order=order, is_confirmed=False).update(is_confirmed=True)
            now = timezone.now()
            payment.provider_payment_id = event.provider_payment_id or payment.provider_payment_id
            payment.paid_at = now
            payment.transition_to(PaymentState.PAID)
            payment.version += 1
            payment.save(update_fields=["provider_payment_id", "paid_at", "state", "version", "updated_at"])

            if order.status == Order.Status.UNPAID:
                order.status = Order.Status.PENDING
                order.paid_at = now
                update_fields = ["status", "paid_at"]
                if payment.provider == PaymentProvider.RAZORPAY:
                    order.razorpay_payment_id = payment.provider_payment_id
                    update_fields.append("razorpay_payment_id")
                order.save(update_fields=update_fields)

            event_type = PaymentEvent.EventType.RAZORPAY_CONFIRMED if payment.provider == PaymentProvider.RAZORPAY else PaymentEvent.EventType.DIGITAL_PAYMENT_CONFIRMED
            initiated_event_type = PaymentEvent.EventType.RAZORPAY_INITIATED if payment.provider == PaymentProvider.RAZORPAY else PaymentEvent.EventType.DIGITAL_PAYMENT_INITIATED
            if payment.provider_payment_id and not PaymentEvent.objects.filter(
                order=order,
                event_type=initiated_event_type,
                razorpay_payment_id=payment.provider_payment_id,
            ).exists():
                PaymentEvent.objects.create(
                    order=order,
                    order_ref=order.order_ref_snapshot,
                    restaurant=order.restaurant,
                    event_type=initiated_event_type,
                    amount=payment.amount,
                    razorpay_payment_id=payment.provider_payment_id,
                )
            if not PaymentEvent.objects.filter(order=order, event_type=event_type, razorpay_payment_id=payment.provider_payment_id).exists():
                PaymentEvent.objects.create(
                    order=order,
                    order_ref=order.order_ref_snapshot,
                    restaurant=order.restaurant,
                    event_type=event_type,
                    amount=payment.amount,
                    razorpay_payment_id=payment.provider_payment_id,
                )
            if not PlatformFeeRecord.objects.filter(order=order).exists():
                _create_fee_record(order, order.restaurant)

            # RestaurantLedger is the canonical restaurant balance source.
            if not order.ledger_records.filter(
                entry_type="CREDIT_ORDER",
                payment_transaction=payment,
            ).exists():
                gross = order.total
                fee_record = PlatformFeeRecord.objects.filter(order=order).first()
                commission = fee_record.fee_amount if fee_record else Decimal("0.00")
                from ordering.ledger.services import RestaurantLedgerService
                RestaurantLedgerService().record_payment(
                    restaurant=order.restaurant,
                    order=order,
                    payment_transaction=payment,
                    gross_amount=gross,
                    platform_fee=commission,
                )

        # Side effects AFTER transaction commits — prevents KDS showing paid state
        # that gets rolled back if a later step in the transaction fails.
        trigger_kds_refresh(order.restaurant_id)
        broadcast_payment_update(payment.restaurant_id, payment.id, payment.state, payment.order_id)
        return payment

    def mark_failed(self, payment, event):
        with transaction.atomic():
            payment = PaymentTransaction.objects.select_for_update().select_related("order", "order__restaurant").get(pk=payment.pk)
            if payment.state in (PaymentState.PAID, PaymentState.REFUNDED):
                return payment
            payment.provider_payment_id = event.provider_payment_id or payment.provider_payment_id
            if payment.can_transition_to(PaymentState.FAILED):
                payment.transition_to(PaymentState.FAILED)
            else:
                payment.state = PaymentState.FAILED
            payment.version += 1
            payment.save(update_fields=["provider_payment_id", "state", "version", "updated_at"])

            # Stock release INSIDE the same transaction to prevent permanent stock leak.
            # If this fails, the payment state change also rolls back — safe.
            order = payment.order
            if order.status == Order.Status.UNPAID:
                reservations = list(
                    StockReservation.objects.select_for_update().filter(
                        order=order, is_confirmed=False,
                    )
                )
                from ordering.services import _restore_item_availability_after_stock_return
                for res in reservations:
                    if res.menu_item_id and res.menu_item and res.menu_item.stock is not None:
                        from django.db import models as db_models
                        from core.models import MenuItem
                        MenuItem.objects.filter(pk=res.menu_item_id).update(
                            stock=db_models.F('stock') + res.quantity
                        )
                        _restore_item_availability_after_stock_return(res.menu_item_id)
                    if res.addon_id and res.addon and res.addon.stock is not None:
                        from core.models import AddOn
                        from django.db import models as db_models
                        AddOn.objects.filter(pk=res.addon_id).update(
                            stock=db_models.F('stock') + res.quantity
                        )
                    res.is_confirmed = True
                    res.save(update_fields=['is_confirmed'])

                order.status = Order.Status.CANCELLED
                order.save(update_fields=['status'])

                PaymentEvent.objects.create(
                    order=order,
                    order_ref=order.order_ref_snapshot,
                    restaurant=order.restaurant,
                    event_type=PaymentEvent.EventType.PAYMENT_FAILED,
                    amount=order.total,
                )

        # Side effects AFTER transaction commits
        trigger_kds_refresh(payment.restaurant_id)
        broadcast_payment_update(payment.restaurant_id, payment.id, payment.state, payment.order_id)
        return payment

class WebhookIngestionService:
    def receive(self, provider, raw_body, headers):
        provider = str(provider).lower()
        payload = json.loads(raw_body.decode("utf-8") or "{}")
        gateway = get_gateway(provider)
        event = gateway.parse_webhook(payload, headers)

        logger.info(
            "payment_webhook_received provider=%s event_kind=%s "
            "event_id=%s provider_order_id=%s",
            provider, event.kind, event.provider_event_id,
            event.provider_order_id,
        )

        payment = self._resolve_payment(provider, event, payload)
        if not payment:
            logger.warning(
                "payment_webhook_unresolved provider=%s event_id=%s "
                "provider_order_id=%s provider_payment_id=%s",
                provider, event.provider_event_id,
                event.provider_order_id, event.provider_payment_id,
            )
            return None

        # Duplicate detection by provider event ID
        if event.provider_event_id:
            existing_event = WebhookLog.objects.filter(
                restaurant=payment.restaurant,
                provider=provider,
                provider_event_id=event.provider_event_id,
            ).first()
            if existing_event:
                logger.info(
                    "payment_webhook_duplicate provider=%s event_id=%s "
                    "payment_id=%s",
                    provider, event.provider_event_id, payment.id,
                )
                return existing_event

        # Replay protection
        if not _is_webhook_timestamp_fresh(headers):
            logger.warning(
                "payment_webhook_replay_rejected provider=%s event_id=%s "
                "payment_id=%s",
                provider, event.provider_event_id, payment.id,
            )
            raise PaymentGatewayError("Webhook timestamp is outside the allowed replay window.")

        # Signature verification
        resolved = resolve_payment_config_for_transaction(payment, require_webhook=True)
        signature_valid = gateway.verify_webhook(raw_body, headers, resolved)

        if signature_valid:
            logger.info(
                "payment_webhook_signature_valid provider=%s event_id=%s "
                "payment_id=%s",
                provider, event.provider_event_id, payment.id,
            )
        else:
            logger.warning(
                "payment_webhook_signature_invalid provider=%s event_id=%s "
                "payment_id=%s",
                provider, event.provider_event_id, payment.id,
            )

        # Persist the webhook log (dedup by payload hash)
        payload_hash = hashlib.sha256(raw_body).hexdigest()
        webhook_log, _ = WebhookLog.objects.get_or_create(
            restaurant=payment.restaurant,
            provider=provider,
            payload_hash=payload_hash,
            defaults={
                "payment_transaction": payment,
                "provider_event_id": event.provider_event_id,
                "idempotency_key": event.idempotency_key,
                "signature_valid": signature_valid,
                "raw_payload": raw_body.decode("utf-8", errors="replace"),
                "headers": _safe_webhook_headers(headers),
            },
        )
        if not signature_valid:
            webhook_log.failed_reason = "invalid_signature"
            webhook_log.save(update_fields=["failed_reason"])
            raise PaymentGatewayError("Invalid webhook signature.")
        return webhook_log

    def process_log(self, webhook_log):
        # Quick idempotency check without locking
        webhook_log = WebhookLog.objects.select_related("payment_transaction").get(pk=webhook_log.pk)
        if webhook_log.processed_at:
            logger.info(
                "payment_webhook_already_processed provider=%s event_id=%s "
                "webhook_log_id=%s",
                webhook_log.provider, webhook_log.provider_event_id,
                webhook_log.id,
            )
            return webhook_log
        if not webhook_log.signature_valid:
            raise PaymentGatewayError("Webhook signature was not verified.")

        payload = json.loads(webhook_log.raw_payload or "{}")
        event = get_gateway(webhook_log.provider).parse_webhook(payload, webhook_log.headers)

        try:
            # apply_provider_event manages its own transaction.atomic() internally.
            # We do NOT wrap this in another atomic block to avoid nested transaction
            # side-effect bugs (WS broadcasts firing inside a transaction that later rolls back).
            PaymentMutationService().apply_provider_event(webhook_log.payment_transaction, event)
            webhook_log.processed_at = timezone.now()
            webhook_log.failed_reason = ""
            webhook_log.save(update_fields=["processed_at", "failed_reason"])

            logger.info(
                "payment_webhook_processed provider=%s event_id=%s "
                "event_kind=%s payment_id=%s source=webhook",
                webhook_log.provider, webhook_log.provider_event_id,
                event.kind, webhook_log.payment_transaction_id,
            )
        except Exception as exc:
            webhook_log.failed_reason = str(exc)
            webhook_log.save(update_fields=["failed_reason"])
            logger.error(
                "payment_webhook_processing_failed provider=%s event_id=%s "
                "payment_id=%s error=%s",
                webhook_log.provider, webhook_log.provider_event_id,
                webhook_log.payment_transaction_id, exc,
            )
            raise
        return webhook_log

    def _resolve_payment(self, provider, event, payload):
        qs = PaymentTransaction.objects.select_related("restaurant", "order", "tenant_config")
        if event.provider_order_id:
            payment = qs.filter(provider=provider, provider_order_id=event.provider_order_id).first()
            if payment:
                return payment
        if event.provider_payment_id:
            payment = qs.filter(provider=provider, provider_payment_id=event.provider_payment_id).first()
            if payment:
                return payment
        notes = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("notes", {})
        if notes.get("payment_transaction_id"):
            payment = qs.filter(pk=notes["payment_transaction_id"]).first()
            if payment:
                return payment
        if provider == PaymentProvider.RAZORPAY and event.provider_order_id:
            order = Order.objects.filter(razorpay_order_id=event.provider_order_id).first()
            if order:
                payment, _ = PaymentTransaction.objects.get_or_create(
                    restaurant=order.restaurant,
                    order=order,
                    provider=PaymentProvider.RAZORPAY,
                    provider_order_id=event.provider_order_id,
                    defaults={"state": PaymentState.INITIATED, "amount": order.total, "currency": "INR", "expires_at": timezone.now() + timezone.timedelta(minutes=15)},
                )
                return payment
        return None


class PaymentReconciliationService:
    def reconcile_payment(self, payment):
        before = payment.state
        try:
            updated = PaymentVerificationService().verify_payment(payment)
            result = PaymentReconciliationLog.Result.UPDATED if updated.state != before else PaymentReconciliationLog.Result.MATCHED
            PaymentReconciliationLog.objects.create(
                restaurant=payment.restaurant,
                payment_transaction=payment,
                provider=payment.provider,
                result=result,
                local_state=before,
                provider_state=updated.state,
                details={},
            )
            return updated
        except Exception as exc:
            PaymentReconciliationLog.objects.create(
                restaurant=payment.restaurant,
                payment_transaction=payment,
                provider=payment.provider,
                result=PaymentReconciliationLog.Result.FAILED,
                local_state=before,
                details={"error": str(exc)},
            )
            raise
