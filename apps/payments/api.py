import json
from uuid import UUID
from ninja import Router, Schema
from django.http import HttpRequest
from pydantic import Field
from .dtos import InitializePaymentCommand, ProcessWebhookCommand
from .use_cases import PaymentUseCases

router = Router()

class InitializePaymentIn(Schema):
    order_id: UUID
    amount: str # decimal as string
    currency: str = 'INR'
    idempotency_key: UUID = None

class InitializePaymentOut(Schema):
    transaction_id: UUID
    provider_order_id: str
    amount: str
    state: str

@router.post("/{restaurant_id}/initialize/", response={200: InitializePaymentOut, 400: dict})
def initialize_payment(request, restaurant_id: UUID, payload: InitializePaymentIn):
    from decimal import Decimal
    try:
        cmd = InitializePaymentCommand(
            restaurant_id=restaurant_id,
            order_id=payload.order_id,
            amount=Decimal(payload.amount),
            currency=payload.currency,
            idempotency_key=payload.idempotency_key
        )
        tx = PaymentUseCases.initialize_payment(cmd)
        return 200, {
            "transaction_id": tx.id,
            "provider_order_id": tx.provider_order_id,
            "amount": str(tx.amount),
            "state": tx.state
        }
    except Exception as e:
        return 400, {"detail": str(e)}

@router.post("/{restaurant_id}/webhook/{provider}/")
def webhook_receiver(request: HttpRequest, restaurant_id: UUID, provider: str):
    # Depending on provider, signature comes from different headers
    signature = ""
    if provider == 'razorpay':
        signature = request.headers.get('x-razorpay-signature', '')

    cmd = ProcessWebhookCommand(
        restaurant_id=restaurant_id,
        provider=provider,
        payload_body=request.body.decode('utf-8'),
        signature=signature
    )
    
    success = PaymentUseCases.process_webhook(cmd)
    if success:
        return {"status": "ok"}
    else:
        # We always return 200 to the webhook provider even if validation fails
        # to prevent retries of bad payloads
        return {"status": "ignored"}
