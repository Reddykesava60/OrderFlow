"""
Centralized payment credential resolver.

Resolution order:
  1. TenantPaymentConfig (new multi-provider model, per-restaurant, if active)
  2. Platform-level credentials from environment variables

Every callsite that needs gateway credentials MUST go through this module.
"""
from django.conf import settings

from ordering.models import GatewayAccountSource, PaymentProvider, TenantPaymentConfig

from .contracts import PaymentConfigurationError, ResolvedPaymentConfig


# ── Helpers ──────────────────────────────────────────────────────────────────


def _tenant_config(restaurant, provider=None, *, require_webhook=False):
    """Attempt to resolve from the new TenantPaymentConfig model."""
    configs = TenantPaymentConfig.objects.filter(restaurant=restaurant, is_active=True)
    if provider:
        configs = configs.filter(provider=provider)

    config = configs.order_by("priority", "provider").first()
    if not config:
        return None

    webhook_secret = config.get_webhook_secret()
    if require_webhook and not webhook_secret:
        return None

    if not settings.DEBUG and not getattr(settings, "TESTING", False):
        if config.mode == 'test':
            raise PaymentConfigurationError("Test payment credentials are not allowed in production.")

    return ResolvedPaymentConfig(
        provider=config.provider,
        mode=config.mode,
        credentials=config.get_credentials(),
        webhook_secret=webhook_secret,
        tenant_config=config,
        is_legacy=False,
        account_source=GatewayAccountSource.RESTAURANT,
        account_identifier=f"{config.account_name or config.provider}:{config.mode}",
    )



def _platform_razorpay_config(restaurant=None, *, require_webhook=False):
    """
    Fallback: use platform-level Razorpay credentials from environment variables.
    All restaurants share this single gateway account.
    """
    key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
    key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
    webhook_secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")

    if not key_id or not key_secret:
        return None

    if require_webhook and not webhook_secret:
        return None

    if not settings.DEBUG and not getattr(settings, "TESTING", False):
        if key_id.startswith("rzp_test_"):
            raise PaymentConfigurationError("Test Razorpay credentials are not allowed in production.")

    merchant_name = restaurant.name if restaurant else getattr(settings, "APP_NAME", "DineFlow")

    return ResolvedPaymentConfig(
        provider=PaymentProvider.RAZORPAY,
        mode="test" if key_id.startswith("rzp_test_") else "live",
        credentials={
            "key_id": key_id,
            "key_secret": key_secret,
            "upi_vpa": "",
            "merchant_name": merchant_name,
        },
        webhook_secret=webhook_secret,
        is_legacy=True,
        account_source=GatewayAccountSource.PLATFORM,
        account_identifier=f"{key_id[:8]}..." if key_id else "platform",
    )


# ── Public API ───────────────────────────────────────────────────────────────


def resolve_payment_config(restaurant, provider=None, *, require_webhook=False):
    """
    Centralized credential resolution.

    Resolution order:
      1. TenantPaymentConfig (per-restaurant, multi-provider)
      2. Platform environment variables

    Returns ResolvedPaymentConfig with account_source metadata.
    Raises PaymentConfigurationError if no credentials can be resolved.
    """
    # 1. New multi-provider tenant config
    resolved = _tenant_config(restaurant, provider, require_webhook=require_webhook)
    if resolved:
        return resolved

    # 2. Platform-level Razorpay (default for all restaurants)
    if not provider or provider == PaymentProvider.RAZORPAY:
        resolved = _platform_razorpay_config(restaurant, require_webhook=require_webhook)
        if resolved:
            return resolved

    raise PaymentConfigurationError(
        "No active payment configuration found for this restaurant. "
        "Configure restaurant-specific credentials or set platform Razorpay environment variables."
    )


def resolve_payment_config_for_transaction(payment, *, require_webhook=False):
    """
    Resolve credentials for an existing PaymentTransaction.

    Uses tenant_config FK if available, otherwise falls through the
    standard resolution chain for the payment's restaurant.
    """
    if payment.tenant_config_id:
        config = payment.tenant_config
        return ResolvedPaymentConfig(
            provider=config.provider,
            mode=config.mode,
            credentials=config.get_credentials(),
            webhook_secret=config.get_webhook_secret(),
            tenant_config=config,
            is_legacy=False,
            account_source=GatewayAccountSource.RESTAURANT,
            account_identifier=f"{config.account_name or config.provider}:{config.mode}",
        )

    # No tenant_config FK — resolve via the standard chain.
    # This handles both legacy restaurant configs and platform fallback.
    return resolve_payment_config(
        payment.restaurant, payment.provider, require_webhook=require_webhook,
    )
