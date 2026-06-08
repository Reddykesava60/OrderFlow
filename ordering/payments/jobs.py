import logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from ordering.models import PaymentState, PaymentTransaction, WebhookLog

from .services import (
    PaymentReconciliationService,
    PaymentRetryService,
    PaymentVerificationService,
    WebhookIngestionService,
)

logger = logging.getLogger(__name__)

def _dispatch_or_run(task_func, *args, **kwargs):
    if getattr(settings, "PAYMENT_JOBS_INLINE", False):
        return task_func(*args, **kwargs)
    logger.info("payment_job_enqueued task=%s args=%s", task_func.__name__, args)
    return task_func.delay(*args, **kwargs)


@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def process_payment_webhook_task(self, webhook_log_id):
    try:
        log = WebhookLog.objects.get(pk=webhook_log_id)
        return WebhookIngestionService().process_log(log)
    except Exception as exc:
        logger.exception("Webhook processing failed, retrying...")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def verify_payment_task(self, payment_transaction_id):
    try:
        payment = PaymentTransaction.objects.get(pk=payment_transaction_id)
        return PaymentVerificationService().verify_payment(payment)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def reconcile_payment_task(self, payment_transaction_id):
    try:
        payment = PaymentTransaction.objects.get(pk=payment_transaction_id)
        return PaymentReconciliationService().reconcile_payment(payment)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def expire_pending_payments_task():
    expired = 0
    qs = PaymentTransaction.objects.filter(
        state__in=[PaymentState.PENDING, PaymentState.INITIATED, PaymentState.PROCESSING],
        expires_at__lt=timezone.now(),
    ).select_related("order")
    for payment in qs:
        try:
            # Inline execution for the cron task to avoid spawning too many async jobs
            PaymentReconciliationService().reconcile_payment(payment)
            payment.refresh_from_db()
            if payment.state in [PaymentState.PENDING, PaymentState.INITIATED, PaymentState.PROCESSING]:
                payment.transition_to(PaymentState.EXPIRED)
                payment.version += 1
                payment.save(update_fields=["state", "version", "updated_at"])
                expired += 1
        except Exception:
            logger.exception("expire_pending_payment_failed payment=%s", payment.id)
    return expired


@shared_task
def process_unprocessed_webhooks_task(limit=100):
    processed = 0
    qs = (
        WebhookLog.objects
        .filter(signature_valid=True, processed_at__isnull=True)
        .order_by("created_at")[:limit]
    )
    for webhook_log in qs:
        try:
            WebhookIngestionService().process_log(webhook_log)
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
