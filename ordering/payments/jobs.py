import logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from ordering.models import PaymentState, PaymentTransaction, WebhookLog

from .services import PaymentReconciliationService, PaymentRetryService, PaymentVerificationService, WebhookIngestionService

logger = logging.getLogger(__name__)

def _dispatch_or_run(task_func, *args, **kwargs):
    if getattr(settings, "PAYMENT_JOBS_INLINE", False):
        return task_func(*args, **kwargs)
    logger.info("payment_job_enqueued task=%s args=%s", task_func.__name__, args)
    return task_func.delay(*args, **kwargs)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_payment_webhook_task(self, webhook_log_id):
    try:
        log = WebhookLog.objects.get(pk=webhook_log_id)
        if log.status == WebhookLog.Status.DEAD_LETTERED:
            return {"webhook_log_id": str(webhook_log_id), "status": "dead_lettered_skipped"}
        result = WebhookIngestionService().process_log(log)
        return {
            "webhook_log_id": str(result.id),
            "status": "processed",
        }
    except Exception as exc:
        logger.exception("Webhook processing failed.")
        try:
            log = WebhookLog.objects.get(pk=webhook_log_id)
            log.retry_count += 1
            import traceback
            log.failed_reason = traceback.format_exc()
            if self.request.retries >= self.max_retries:
                log.status = WebhookLog.Status.DEAD_LETTERED
            log.save(update_fields=['retry_count', 'failed_reason', 'status'])
        except WebhookLog.DoesNotExist:
            pass
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def verify_payment_task(self, payment_transaction_id):
    try:
        payment = PaymentTransaction.objects.get(pk=payment_transaction_id)
        result = PaymentVerificationService().verify_payment(payment)
        return {
            "payment_transaction_id": str(result.id),
            "state": result.state,
        }
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def reconcile_payment_task(self, payment_transaction_id):
    try:
        payment = PaymentTransaction.objects.get(pk=payment_transaction_id)
        result = PaymentReconciliationService().reconcile_payment(payment)
        return {
            "payment_transaction_id": str(result.id),
            "state": result.state,
        }
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def expire_single_payment_task(self, payment_transaction_id):
    try:
        payment = PaymentTransaction.objects.get(pk=payment_transaction_id)
        # Attempt to reconcile first in case the webhook was delayed
        PaymentReconciliationService().reconcile_payment(payment)
        payment.refresh_from_db()
        if payment.state in [PaymentState.PENDING, PaymentState.INITIATED, PaymentState.PROCESSING]:
            if payment.expires_at and payment.expires_at < timezone.now():
                from ordering.payments.state_machine import PaymentStateMachine
                PaymentStateMachine().transition_locked(payment, PaymentState.EXPIRED)
                payment.save(update_fields=["state", "version", "updated_at"])
                
                order = payment.order
                if order and order.status == order.Status.UNPAID:
                    from ordering.orders.services import cancel_upi_payment
                    from kitchen.models import PaymentEvent
                    cancel_upi_payment(order, PaymentEvent.EventType.PAYMENT_TIMEOUT)
                
                return True
        return False
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def expire_pending_payments_task():
    qs = PaymentTransaction.objects.filter(
        state__in=[PaymentState.PENDING, PaymentState.INITIATED, PaymentState.PROCESSING],
        expires_at__lt=timezone.now(),
    ).values_list('id', flat=True)
    
    dispatched = 0
    for payment_id in qs:
        if settings.PAYMENT_JOBS_INLINE:
            expire_single_payment_task(payment_id)
        else:
            expire_single_payment_task.delay(payment_id)
        dispatched += 1
        
    return dispatched


@shared_task
def process_unprocessed_webhooks_task(limit=100):
    processed = 0
    qs = (
        WebhookLog.objects
        .filter(signature_valid=True, status=WebhookLog.Status.PENDING, retry_count__lt=3)
        .order_by("created_at")[:limit]
    )
    for webhook_log in qs:
        try:
            if getattr(settings, "PAYMENT_JOBS_INLINE", False):
                process_payment_webhook_task(webhook_log.id)
            else:
                process_payment_webhook_task.delay(webhook_log.id)
            processed += 1
        except Exception:
            logger.exception("process_unprocessed_webhook_failed webhook_log=%s", webhook_log.id)
    return processed


@shared_task
def reconcile_recent_payments_task(minutes=360, limit=200):
    cutoff = timezone.now() - timezone.timedelta(minutes=minutes)
    reconciled = 0
    payments = (
        PaymentTransaction.objects
        .filter(
            state__in=[PaymentState.PENDING, PaymentState.INITIATED, PaymentState.PROCESSING],
            created_at__gte=cutoff,
        )
        .order_by("created_at")[:limit]
    )
    for payment in payments:
        try:
            PaymentReconciliationService().reconcile_payment(payment)
            reconciled += 1
        except Exception:
            logger.exception("reconcile_recent_payment_failed payment=%s", payment.id)
    return reconciled


@shared_task
def release_expired_reservations_task():
    from django.core.management import call_command

    call_command("release_expired_reservations")
    return "ok"


@shared_task
def sync_monthly_statements_task():
    from django.core.management import call_command

    call_command("sync_monthly_statements")
    return "ok"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def retry_failed_payment_task(self, payment_transaction_id):
    try:
        payment = PaymentTransaction.objects.get(pk=payment_transaction_id)
        return PaymentRetryService().retry_payment(payment)
    except Exception as exc:
        raise self.retry(exc=exc)


from datetime import timedelta
import json

@shared_task
def stuck_webhook_detector_task():
    cutoff = timezone.now() - timedelta(minutes=5)
    stuck_webhooks = WebhookLog.objects.filter(
        signature_valid=True,
        processed_at__isnull=True,
        created_at__lt=cutoff
    )
    
    if stuck_webhooks.exists():
        webhook_ids = []
        provider_order_ids = []
        for w in stuck_webhooks:
            webhook_ids.append(str(w.id))
            try:
                payload = json.loads(w.raw_payload or "{}")
                # Handle Razorpay nested structure
                if w.provider == 'razorpay':
                    order_id = payload.get('payload', {}).get('order', {}).get('entity', {}).get('id')
                    if not order_id: # Also check payment payload
                        order_id = payload.get('payload', {}).get('payment', {}).get('entity', {}).get('order_id', 'unknown')
                    provider_order_ids.append(order_id)
                else:
                    provider_order_ids.append(w.provider_event_id)
            except Exception:
                provider_order_ids.append('parse_error')
        
        logger.error(
            "stuck_webhooks_detected count=%s ids=%s provider_order_ids=%s",
            stuck_webhooks.count(),
            webhook_ids,
            provider_order_ids
        )
    return stuck_webhooks.count()

# Maintain old API compatibility for services importing jobs.py
class ProcessPaymentWebhookJob:
    @classmethod
    def dispatch(cls, webhook_log_id):
        return _dispatch_or_run(process_payment_webhook_task, webhook_log_id)

class VerifyPaymentJob:
    @classmethod
    def dispatch(cls, payment_transaction_id):
        return _dispatch_or_run(verify_payment_task, payment_transaction_id)

class ReconcilePaymentJob:
    @classmethod
    def dispatch(cls, payment_transaction_id):
        return _dispatch_or_run(reconcile_payment_task, payment_transaction_id)

class ExpirePendingPaymentsJob:
    @classmethod
    def dispatch(cls):
        return _dispatch_or_run(expire_pending_payments_task)

class RetryFailedPaymentJob:
    @classmethod
    def dispatch(cls, payment_transaction_id):
        return _dispatch_or_run(retry_failed_payment_task, payment_transaction_id)
