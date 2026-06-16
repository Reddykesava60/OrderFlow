from django.views.generic import TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Sum, Count, Q
from django.utils import timezone

from core.models import Restaurant, PlatformFeeRecord
from core.timeutils import local_day_bounds
from ordering.models import Order, WebhookLog

class PlatformOperationsDashboardView(UserPassesTestMixin, TemplateView):
    template_name = "core/ops_dashboard.html"

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_superuser

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        today_start, today_end = local_day_bounds(timezone.localdate())

        # Global Financials (Today)
        # TGV = Total Gross Volume from paid orders today
        tgv_agg = Order.objects.filter(
            status__in=[Order.Status.PENDING, Order.Status.PREP_STARTED, Order.Status.COMPLETED],
            created_at__gte=today_start,
            created_at__lt=today_end
        ).aggregate(total=Sum('total'))
        tgv = tgv_agg['total'] or 0

        # Platform Fees Accrued Today
        fees_agg = PlatformFeeRecord.objects.filter(
            created_at__gte=today_start,
            created_at__lt=today_end
        ).aggregate(total=Sum('fee_amount'))
        platform_fees = fees_agg['total'] or 0

        # System Reliability
        failed_webhooks = WebhookLog.objects.filter(status=WebhookLog.Status.FAILED).count()
        dlq_size = WebhookLog.objects.filter(status=WebhookLog.Status.DLQ).count()

        # Restaurant Activity
        active_restaurants = Restaurant.objects.filter(is_active=True).count()
        # "Online" means is_active=True AND config.is_open=True
        online_restaurants = Restaurant.objects.filter(is_active=True, config__is_open=True).count()
        offline_restaurants = active_restaurants - online_restaurants

        context.update({
            'tgv': tgv,
            'platform_fees': platform_fees,
            'failed_webhooks': failed_webhooks,
            'dlq_size': dlq_size,
            'active_restaurants': active_restaurants,
            'online_restaurants': online_restaurants,
            'offline_restaurants': offline_restaurants,
        })
        return context
