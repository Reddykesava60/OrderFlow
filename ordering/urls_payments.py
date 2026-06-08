from django.urls import path
from ordering.payments.views import WebhookIngressView, PaymentStatusView, PaymentRetryView
from ordering.views import RazorpayVerifyView, RazorpayWebhookView

urlpatterns = [
    # New Provider-Agnostic Routes
    path('webhook/<str:provider>/', WebhookIngressView.as_view(), name='payment_webhook_ingress'),
    path('status/<uuid:payment_id>/', PaymentStatusView.as_view(), name='payment_status'),
    path('retry/<uuid:payment_id>/', PaymentRetryView.as_view(), name='payment_retry'),
    
    # Legacy Razorpay endpoints required by menu.html
    path('razorpay/verify/', RazorpayVerifyView.as_view(), name='razorpay_verify'),
    path('razorpay/webhook/', RazorpayWebhookView.as_view(), name='razorpay_webhook'),
]
