# kitchen/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import PaymentEvent


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display  = ['created_at', 'restaurant', 'order_ref', 'event_type', 'event_status', 'amount_display', 'razorpay_payment_id']
    list_filter   = ['event_status', 'event_type', 'restaurant']
    search_fields = ['order_ref', 'razorpay_payment_id', 'transaction__id']
    date_hierarchy = 'created_at'
    ordering      = ['-created_at']

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields] + ['metadata_display']

    @admin.display(description='Metadata')
    def metadata_display(self, obj):
        import json
        return format_html('<pre>{}</pre>', json.dumps(obj.metadata, indent=2))

    @admin.display(description='Amount')
    def amount_display(self, obj):
        color = {
            'PAYMENT_FAILED':    '#b91c1c',
            'PAYMENT_TIMEOUT':   '#b91c1c',
            'REFUND_FAILED':     '#b45309',
            'REFUND_INITIATED':  '#b45309',
            'REFUND_PROCESSED':  '#b45309',
            'CASH_COLLECTED':    '#1f7a4d',
            'RAZORPAY_CONFIRMED':'#1f7a4d',
        }.get(obj.event_type, '#374151')
        return format_html('<span style="color:{}">{}</span>', color, f"₹{obj.amount:,.2f}")
