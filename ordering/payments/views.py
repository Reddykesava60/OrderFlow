import logging
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.shortcuts import get_object_or_404

from ordering.models import PaymentTransaction
from .services import PaymentOrchestratorService, PaymentRetryService, WebhookIngestionService, verify_payment_access_token
from .jobs import ProcessPaymentWebhookJob

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class WebhookIngressView(View):
    """
    Unified webhook ingress for all payment providers.
    """
    def post(self, request, provider):
        try:
            webhook_log = WebhookIngestionService().receive(
                provider=provider,
                raw_body=request.body,
                headers=request.headers,
            )
            if webhook_log:
                try:
                    ProcessPaymentWebhookJob.dispatch(str(webhook_log.id))
                except Exception:
                    logger.exception(
                        "Webhook persisted but dispatch failed for %s/%s",
                        provider,
                        webhook_log.id,
                    )
            return HttpResponse("OK", status=200)
        except Exception as e:
            logger.exception(f"Webhook ingress error for {provider}")
            # We return 200 to prevent provider from spamming us if it's our code failure,
            # unless we want them to retry. For security/signature errors, we return 400.
            return HttpResponse(str(e), status=400)


class PaymentStatusView(View):
    """
    Frontend polls this to know if payment succeeded.
    """
    def get(self, request, payment_id):
        payment = get_object_or_404(PaymentTransaction, id=payment_id)

        token = (request.GET.get("token") or request.headers.get("X-Payment-Access-Token") or "").strip()
        user = getattr(request, "user", None)
        has_session_access = bool(user and user.is_authenticated and getattr(user, "restaurant_id", None) == payment.restaurant_id)
        if not has_session_access and not verify_payment_access_token(payment, token):
            return JsonResponse({"error": "FORBIDDEN"}, status=403)
            
        data = PaymentOrchestratorService().serialize(payment)
        return JsonResponse(data)


@method_decorator(csrf_exempt, name='dispatch')
class PaymentRetryView(View):
    def post(self, request, payment_id):
        payment = get_object_or_404(PaymentTransaction, id=payment_id)
        token = (request.GET.get("token") or request.headers.get("X-Payment-Access-Token") or "").strip()
        user = getattr(request, "user", None)
        has_session_access = bool(user and user.is_authenticated and getattr(user, "restaurant_id", None) == payment.restaurant_id)
        if not has_session_access and not verify_payment_access_token(payment, token):
            return JsonResponse({"error": "FORBIDDEN"}, status=403)

        new_data = PaymentRetryService().retry_payment(payment)
        return JsonResponse(new_data)
