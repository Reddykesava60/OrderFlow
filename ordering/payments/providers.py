import base64
import hashlib
import hmac
import logging
from decimal import Decimal

import requests
import razorpay
from django.conf import settings
from django.utils import timezone

from ordering.models import PaymentProvider, PaymentState

from .contracts import (
    PaymentCreateRequest,
    PaymentCreateResult,
    PaymentGatewayError,
    ProviderPaymentStatus,
    ProviderWebhookEvent,
    ResolvedPaymentConfig,
)
from .upi import build_upi_uri, qr_data_uri, signed_metadata

logger = logging.getLogger(__name__)


def _paise(amount):
    return int((Decimal(amount) * Decimal("100")).quantize(Decimal("1")))


def _rupees(value):
    if value in (None, ""):
        return None
    return (Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"))


class BaseProvider:
    provider = ""
    timeout_seconds = 8

    def generate_intent(self, request: PaymentCreateRequest, config: ResolvedPaymentConfig):
        signature = signed_metadata(
            request.order_id,
            request.metadata.get("payment_transaction_id", request.order_id),
            request.amount,
            config.credentials.get("intent_signing_secret") or getattr(settings, "SECRET_KEY", "order-flow"),
        )
        return build_upi_uri(
            vpa=config.credentials.get("upi_vpa", ""),
            merchant_name=config.credentials.get("merchant_name") or request.restaurant_name,
            amount=request.amount,
            transaction_ref=request.order_id,
            note=f"{settings.APP_NAME} order {request.order_number}",
            metadata_signature=signature,
        )

    def _fallback_qr(self, request, config, raw=None):
        intent_uri = self.generate_intent(request, config)
        return PaymentCreateResult(
            provider_order_id=request.order_id,
            intent_uri=intent_uri,
            qr_payload=intent_uri,
            qr_image_url=qr_data_uri(intent_uri),
            expires_at=request.expires_at,
            raw_response=raw or {},
        )

    def generate_qr(self, request, config):
        return self._fallback_qr(request, config)

    def _hmac_hex(self, raw_body, secret):
        return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


class RazorpayProvider(BaseProvider):
    provider = PaymentProvider.RAZORPAY

    def _auth(self, config):
        key_id = config.credentials.get("key_id")
        key_secret = config.credentials.get("key_secret")
        if not key_id or not key_secret:
            raise PaymentGatewayError("Razorpay key_id/key_secret are required.")
        return key_id, key_secret

    def create_payment(self, request, config):
        key_id, key_secret = self._auth(config)
        client = razorpay.Client(auth=(key_id, key_secret))
        rz_order = client.order.create({
            "amount": _paise(request.amount),
            "currency": request.currency,
            "payment_capture": 1,
            "receipt": request.order_id,
            "notes": {
                "dineflow_order_id": request.order_id,
                "restaurant": request.restaurant_slug,
                **request.metadata,
            },
        })

        fallback = self._fallback_qr(request, config, raw={"order": rz_order})
        qr_id = ""
        qr_image = fallback.qr_image_url
        qr_payload = fallback.qr_payload

        if not getattr(settings, "TESTING", False):
            try:
                response = requests.post(
                    "https://api.razorpay.com/v1/payments/qr_codes",
                    auth=(key_id, key_secret),
                    json={
                        "type": "upi_qr",
                        "name": f"{settings.APP_NAME} order {request.order_number}",
                        "usage": "single_use",
                        "fixed_amount": True,
                        "payment_amount": _paise(request.amount),
                        "description": f"{request.restaurant_name} order {request.order_number}",
                        "close_by": int(request.expires_at.timestamp()) if request.expires_at else None,
                        "notes": {
                            "dineflow_order_id": request.order_id,
                            "dineflow_provider_order_id": rz_order["id"],
                            **request.metadata,
                        },
                    },
                    timeout=self.timeout_seconds,
                )
                if response.ok:
                    qr_json = response.json()
                    qr_id = qr_json.get("id", "")
                    qr_image = qr_json.get("image_url") or qr_image
                    qr_payload = qr_json.get("image_url") or qr_payload
                else:
                    logger.warning("Razorpay QR create failed: %s", response.text[:500])
            except Exception:
                logger.exception("Razorpay QR create failed")

        return PaymentCreateResult(
            provider_order_id=rz_order["id"],
            provider_qr_id=qr_id,
            intent_uri=fallback.intent_uri,
            qr_image_url=qr_image,
            qr_payload=qr_payload,
            expires_at=request.expires_at,
            raw_response={"order": rz_order},
        )

    def verify_payment(self, provider_payment_id, config):
        key_id, key_secret = self._auth(config)
        payment = razorpay.Client(auth=(key_id, key_secret)).payment.fetch(provider_payment_id)
        state = {
            "captured": PaymentState.PAID,
            "authorized": PaymentState.PROCESSING,
            "failed": PaymentState.FAILED,
            "refunded": PaymentState.REFUNDED,
        }.get(payment.get("status"), PaymentState.PROCESSING)
        return ProviderPaymentStatus(state=state, provider_payment_id=payment.get("id", ""), amount=_rupees(payment.get("amount")), raw_response=payment)

    def get_payment_status(self, provider_order_id, config):
        key_id, key_secret = self._auth(config)
        response = requests.get(
            f"https://api.razorpay.com/v1/orders/{provider_order_id}/payments",
            auth=(key_id, key_secret),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        payments = payload.get("items") or []
        paid = next((p for p in payments if p.get("status") == "captured"), None)
        if paid:
            return ProviderPaymentStatus(PaymentState.PAID, paid.get("id", ""), _rupees(paid.get("amount")), payload)
        failed = next((p for p in payments if p.get("status") == "failed"), None)
        if failed:
            return ProviderPaymentStatus(PaymentState.FAILED, failed.get("id", ""), _rupees(failed.get("amount")), payload)
        return ProviderPaymentStatus(PaymentState.PROCESSING, raw_response=payload)

    def verify_webhook(self, raw_body, headers, config):
        signature = headers.get("X-Razorpay-Signature") or headers.get("x-razorpay-signature")
        if not config.webhook_secret:
            logger.warning(
                "razorpay_webhook_secret_empty — signature verification impossible"
            )
            return False
        if not signature:
            logger.warning("razorpay_webhook_signature_header_missing")
            return False
        return hmac.compare_digest(self._hmac_hex(raw_body, config.webhook_secret), signature)

    def parse_webhook(self, payload, headers):
        event_type = payload.get("event", "")
        entity = payload.get("payload", {})
        payment = entity.get("payment", {}).get("entity", {})
        order = entity.get("order", {}).get("entity", {})
        if event_type in ("payment.captured", "order.paid"):
            return ProviderWebhookEvent("payment_paid", payment.get("order_id") or order.get("id", ""), payment.get("id", ""), provider_event_id=payload.get("id", ""), idempotency_key=payload.get("id", "") or payment.get("id", ""), amount=_rupees(payment.get("amount")), raw=payload)
        if event_type == "payment.failed":
            return ProviderWebhookEvent("payment_failed", payment.get("order_id", ""), payment.get("id", ""), provider_event_id=payload.get("id", ""), idempotency_key=payload.get("id", "") or payment.get("id", ""), amount=_rupees(payment.get("amount")), raw=payload)
        return ProviderWebhookEvent("ignored", provider_event_id=payload.get("id", ""), raw=payload)


class CashfreeProvider(BaseProvider):
    provider = PaymentProvider.CASHFREE

    def create_payment(self, request, config):
        client_id = config.credentials.get("client_id")
        client_secret = config.credentials.get("client_secret")
        if not client_id or not client_secret:
            return self._fallback_qr(request, config)
        base_url = config.credentials.get("base_url", "https://sandbox.cashfree.com/pg").rstrip("/")
        response = requests.post(
            f"{base_url}/orders",
            headers={
                "x-client-id": client_id,
                "x-client-secret": client_secret,
                "x-api-version": config.credentials.get("api_version", "2025-01-01"),
                "Content-Type": "application/json",
            },
            json={
                "order_id": request.order_id,
                "order_amount": float(request.amount),
                "order_currency": request.currency,
                "customer_details": {"customer_id": request.order_id, "customer_name": request.customer_name},
                "order_tags": {"restaurant": request.restaurant_slug},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json()
        fallback = self._fallback_qr(request, config, raw=raw)
        return PaymentCreateResult(raw.get("order_id", request.order_id), intent_uri=fallback.intent_uri, qr_image_url=fallback.qr_image_url, qr_payload=fallback.qr_payload, expires_at=request.expires_at, raw_response=raw)

    def verify_payment(self, provider_payment_id, config):
        return ProviderPaymentStatus(PaymentState.PROCESSING, provider_payment_id)

    def get_payment_status(self, provider_order_id, config):
        client_id = config.credentials.get("client_id")
        client_secret = config.credentials.get("client_secret")
        if not client_id or not client_secret:
            raise PaymentGatewayError("Cashfree credentials are required for status polling.")
        base_url = config.credentials.get("base_url", "https://sandbox.cashfree.com/pg").rstrip("/")
        response = requests.get(
            f"{base_url}/orders/{provider_order_id}/payments",
            headers={"x-client-id": client_id, "x-client-secret": client_secret, "x-api-version": config.credentials.get("api_version", "2025-01-01")},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json()
        payments = raw if isinstance(raw, list) else raw.get("payments", [])
        paid = next((p for p in payments if p.get("payment_status") == "SUCCESS"), None)
        if paid:
            return ProviderPaymentStatus(PaymentState.PAID, str(paid.get("cf_payment_id", "")), Decimal(str(paid.get("payment_amount"))), {"payments": payments})
        failed = next((p for p in payments if p.get("payment_status") in ("FAILED", "USER_DROPPED")), None)
        return ProviderPaymentStatus(PaymentState.FAILED if failed else PaymentState.PROCESSING, raw_response={"payments": payments})

    def verify_webhook(self, raw_body, headers, config):
        timestamp = headers.get("x-webhook-timestamp") or headers.get("X-Webhook-Timestamp")
        signature = headers.get("x-webhook-signature") or headers.get("X-Webhook-Signature")
        if not timestamp or not signature or not config.webhook_secret:
            return False
        digest = hmac.new(config.webhook_secret.encode("utf-8"), timestamp.encode("utf-8") + raw_body, hashlib.sha256).digest()
        return hmac.compare_digest(base64.b64encode(digest).decode("utf-8"), signature)

    def parse_webhook(self, payload, headers):
        data = payload.get("data", {})
        payment = data.get("payment", {})
        order = data.get("order", {})
        status = payment.get("payment_status")
        kind = "payment_paid" if status == "SUCCESS" else "payment_failed" if status in ("FAILED", "USER_DROPPED") else "ignored"
        return ProviderWebhookEvent(kind, order.get("order_id", ""), str(payment.get("cf_payment_id", "")), provider_event_id=headers.get("x-idempotency-header", ""), idempotency_key=headers.get("x-idempotency-header", ""), amount=Decimal(str(payment["payment_amount"])) if payment.get("payment_amount") is not None else None, raw=payload)


class PhonePeProvider(BaseProvider):
    provider = PaymentProvider.PHONEPE

    def create_payment(self, request, config):
        base_url = config.credentials.get("base_url")
        token = config.credentials.get("auth_token")
        if not base_url or not token:
            return self._fallback_qr(request, config)
        response = requests.post(
            f"{base_url.rstrip('/')}/checkout/v2/pay",
            headers={"Content-Type": "application/json", "Authorization": f"O-Bearer {token}"},
            json={
                "merchantOrderId": request.order_id,
                "amount": _paise(request.amount),
                "expireAfter": max(60, int((request.expires_at - timezone.now()).total_seconds())),
                "paymentFlow": {"type": "PG_CHECKOUT", "message": f"{settings.APP_NAME} order {request.order_number}", "merchantUrls": config.credentials.get("merchant_urls", {})},
                "metaInfo": {"udf1": request.restaurant_slug, "udf2": request.order_id},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json()
        fallback = self._fallback_qr(request, config, raw=raw)
        return PaymentCreateResult(raw.get("orderId", request.order_id), intent_uri=fallback.intent_uri, qr_image_url=fallback.qr_image_url, qr_payload=fallback.qr_payload, expires_at=request.expires_at, raw_response=raw)

    def verify_payment(self, provider_payment_id, config):
        return ProviderPaymentStatus(PaymentState.PROCESSING, provider_payment_id)

    def get_payment_status(self, provider_order_id, config):
        base_url = config.credentials.get("base_url")
        token = config.credentials.get("auth_token")
        if not base_url or not token:
            raise PaymentGatewayError("PhonePe credentials are required for status polling.")
        response = requests.get(f"{base_url.rstrip('/')}/checkout/v2/order/{provider_order_id}/status", headers={"Authorization": f"O-Bearer {token}"}, timeout=self.timeout_seconds)
        response.raise_for_status()
        raw = response.json()
        details = raw.get("paymentDetails") or [{}]
        state = PaymentState.PAID if raw.get("state") in ("COMPLETED", "SUCCESS") else PaymentState.FAILED if raw.get("state") == "FAILED" else PaymentState.PROCESSING
        return ProviderPaymentStatus(state, details[0].get("transactionId", ""), _rupees(raw.get("amount")), raw)

    def verify_webhook(self, raw_body, headers, config):
        signature = headers.get("X-Webhook-Signature") or headers.get("x-webhook-signature")
        return bool(signature and config.webhook_secret and hmac.compare_digest(self._hmac_hex(raw_body, config.webhook_secret), signature))

    def parse_webhook(self, payload, headers):
        body = payload.get("payload", payload)
        state = body.get("state")
        kind = "payment_paid" if state in ("COMPLETED", "SUCCESS") else "payment_failed" if state == "FAILED" else "ignored"
        return ProviderWebhookEvent(kind, body.get("merchantOrderId", ""), body.get("transactionId", ""), provider_event_id=body.get("event", ""), idempotency_key=headers.get("x-idempotency-header", "") or body.get("transactionId", ""), amount=_rupees(body.get("amount")), raw=payload)


class PaytmProvider(BaseProvider):
    provider = PaymentProvider.PAYTM

    def create_payment(self, request, config):
        return self._fallback_qr(request, config)

    def verify_payment(self, provider_payment_id, config):
        return ProviderPaymentStatus(PaymentState.PROCESSING, provider_payment_id)

    def get_payment_status(self, provider_order_id, config):
        raise PaymentGatewayError("Paytm status polling requires Paytm checksum SDK configuration.")

    def verify_webhook(self, raw_body, headers, config):
        signature = headers.get("X-Webhook-Signature") or headers.get("x-webhook-signature")
        return bool(signature and config.webhook_secret and hmac.compare_digest(self._hmac_hex(raw_body, config.webhook_secret), signature))

    def parse_webhook(self, payload, headers):
        status = payload.get("STATUS")
        kind = "payment_paid" if status == "TXN_SUCCESS" else "payment_failed" if status == "TXN_FAILURE" else "ignored"
        return ProviderWebhookEvent(kind, payload.get("ORDERID", ""), payload.get("TXNID", ""), provider_event_id=payload.get("TXNID", ""), idempotency_key=payload.get("CHECKSUMHASH", "") or payload.get("TXNID", ""), amount=Decimal(str(payload["TXNAMOUNT"])) if payload.get("TXNAMOUNT") else None, raw=payload)


GATEWAYS = {
    PaymentProvider.RAZORPAY: RazorpayProvider(),
    PaymentProvider.PHONEPE: PhonePeProvider(),
    PaymentProvider.CASHFREE: CashfreeProvider(),
    PaymentProvider.PAYTM: PaytmProvider(),
}


def get_gateway(provider):
    try:
        return GATEWAYS[str(provider)]
    except KeyError as exc:
        raise PaymentGatewayError(f"Unsupported payment provider: {provider}") from exc
