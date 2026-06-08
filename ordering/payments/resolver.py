"""
Centralized payment credential resolver.

Resolution order:
  1. TenantPaymentConfig (new multi-provider model, per-restaurant, if active)
  2. RestaurantPaymentConfig (legacy Razorpay-only model, if active & usable)
  3. Platform-level credentials from environment variables

Every callsite that needs gateway credentials MUST go through this module.
"""
from django.conf import settings

from core.models import RestaurantPaymentConfig
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


def _legacy_razorpay_config(restaurant, *, require_webhook=False):
    """Attempt to resolve from the legacy RestaurantPaymentConfig model (Razorpay-only)."""
    try:
        config = restaurant.payment_config
    except RestaurantPaymentConfig.DoesNotExist:
        config = None

    if config is None:
        config = RestaurantPaymentConfig.objects.filter(restaurant=restaurant).first()

    if not config or not config.is_active:
        return None

    # Respect config_status — MIGRATED_TO_PLATFORM means skip this config
    if hasattr(config, 'config_status') and config.config_status == RestaurantPaymentConfig.ConfigStatus.MIGRATED_TO_PLATFORM:
        return None

    if not settings.DEBUG and not getattr(settings, "TESTING", False):
        if (config.razorpay_key_id or "").startswith("rzp_test_"):
            return None  # Don't use test keys in production; fall through to platform

    missing = []
    if not config.razorpay_key_id:
        missing.append("razorpay_key_id")
    if not config.get_razorpay_key_secret():
        missing.append("razorpay_key_secret")
    if require_webhook and not config.get_razorpay_webhook_secret():
        missing.append("razorpay_webhook_secret")
    if missing:
        return None  # Incomplete config; fall through to platform

    return ResolvedPaymentConfig(
        provider=PaymentProvider.RAZORPAY,
        mode="test" if (config.razorpay_key_id or "").startswith("rzp_test_") else "live",
        credentials={
            "key_id": config.razorpay_key_id,
            "key_secret": config.get_razorpay_key_secret(),
            "upi_vpa": "",
            "merchant_name": config.account_name or restaurant.name,
        },
        webhook_secret=config.get_razorpay_webhook_secret(),
        is_legacy=True,
        account_source=GatewayAccountSource.RESTAURANT,
        account_identifier=f"{config.razorpay_key_id[:8]}..." if config.razorpay_key_id else "",
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
      2. RestaurantPaymentConfig (legacy per-restaurant Razorpay)
      3. Platform environment variables

    Returns ResolvedPaymentConfig with account_source metadata.
    Raises PaymentConfigurationError if no credentials can be resolved.
    """
    # 1. New multi-provider tenant config
    resolved = _tenant_config(restaurant, provider, require_webhook=require_webhook)
    if resolved:
        return resolved

    # 2. Legacy per-restaurant Razorpay config
    if not provider or provider == PaymentProvider.RAZORPAY:
        resolved = _legacy_razorpay_config(restaurant, require_webhook=require_webhook)
        if resolved:
            return resolved

    # 3. Platform-level Razorpay (default for all restaurants)
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
