# dineflow/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core.views_admin import KDSMetricsDashboardView
from core.views_ops import PlatformOperationsDashboardView
from ordering.views import RazorpayWebhookView
from . import views
import core.views_admin_mfa

admin.site.site_header = f'{settings.APP_NAME} Platform'
admin.site.site_title  = f'{settings.APP_NAME} Admin'
admin.site.index_title = 'Platform management'

handler404 = 'dineflow.views.custom_404'

urlpatterns = [
    path('', views.landing, name='landing'),
    path('healthz/live/', views.health_live, name='health_live'),
    path('healthz/ready/', views.health_ready, name='health_ready'),

    path('platform-admin/kds-metrics/', KDSMetricsDashboardView.as_view(), name='kds_metrics_dashboard'),
    path('platform-admin/ops/', PlatformOperationsDashboardView.as_view(), name='ops_dashboard'),
    
    path('platform-admin/mfa/setup/', core.views_admin_mfa.AdminMfaSetupView.as_view(), name='admin_mfa_setup'),
    path('platform-admin/mfa/verify/', core.views_admin_mfa.AdminMfaVerifyView.as_view(), name='admin_mfa_verify'),
    
    path('platform-admin/', admin.site.urls),

    # Customer-facing — public, no auth
    path('r/', include('ordering.urls')),

    # Razorpay webhook — public endpoint, HMAC-secured
    path('payments/', include('ordering.urls_payments')),
    
    # Fallback alias for old Razorpay webhook URL to prevent lost webhooks
    path('order/razorpay/webhook/', RazorpayWebhookView.as_view()),

    # KDS + staff API — session auth
    path('api/', include('kitchen.urls', namespace='kitchen')),

    # Owner panel — session auth, owner role required
    path('owner/', include('owner.urls', namespace='owner')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
