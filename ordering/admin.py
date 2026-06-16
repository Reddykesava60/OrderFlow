# ordering/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Order, OrderItem, OrderItemAddOn, StockReservation,
    RestaurantOrderCounter, PaymentTransaction, RestaurantBalance,
    Settlement, RestaurantLedger
)
from kitchen.models import PaymentEvent

# ── Inlines ───────────────────────────────────────────────────────────────────

class PaymentEventInline(admin.TabularInline):
    model = PaymentEvent
    extra = 0
    readonly_fields = [
        'created_at', 'event_type', 'event_status', 'amount_display', 
        'razorpay_payment_id', 'metadata_display'
    ]
    fields = readonly_fields
    can_delete = False
    ordering = ['created_at']

    @admin.display(description='Amount')
    def amount_display(self, obj):
        color = 'green' if obj.event_status == 'SUCCESS' else 'red' if obj.event_status == 'FAILED' else 'black'
        return format_html('<span style="color:{};font-weight:bold">{}</span>', color, f"₹{obj.amount:,.2f}")

    @admin.display(description='Metadata')
    def metadata_display(self, obj):
        import json
        return format_html('<pre style="white-space: pre-wrap; font-size: 10px;">{}</pre>', json.dumps(obj.metadata, indent=2))
    
    def has_add_permission(self, request, obj=None):
        return False


class OrderItemAddOnInline(admin.TabularInline):
    model = OrderItemAddOn
    extra = 0
    readonly_fields = ['addon', 'addon_name', 'unit_price', 'quantity']
    can_delete = False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = [
        'menu_item', 'menu_item_name', 'unit_price', 'parcel_surcharge',
        'quantity', 'dining_option', 'spice_level',
        'prep_started_at', 'completed_at', 'completed_by',
    ]
    can_delete = False
    show_change_link = True  # lets you click through to see add-ons


# ── Order Admin ───────────────────────────────────────────────────────────────

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_number', 'restaurant', 'customer_name',
        'status_badge', 'payment_method', 'total_display',
        'created_at', 'paid_at',
    ]
    list_filter = ['status', 'payment_method', 'restaurant']
    search_fields = ['customer_name', 'table_number', 'id']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    readonly_fields = [
        'id', 'order_number', 'restaurant', 'customer_name', 'table_number',
        'payment_method', 'total', 'consent_given',
        'razorpay_order_id', 'razorpay_payment_id',
        'created_at', 'paid_at', 'prep_started_at', 'completed_at',
    ]
    inlines = [OrderItemInline]

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {
            'UNPAID':       '#92400e',
            'PENDING':      '#065f46',
            'PREP_STARTED': '#9a3412',
            'COMPLETED':    '#065f46',
            'CANCELLED':    '#991b1b',
        }
        bg = {
            'UNPAID':       '#fef3c7',
            'PENDING':      '#d1fae5',
            'PREP_STARTED': '#ffedd5',
            'COMPLETED':    '#d1fae5',
            'CANCELLED':    '#fee2e2',
        }
        return format_html(
            '<span style="background:{};color:{};padding:3px 8px;border-radius:10px;font-size:11px;font-weight:700">{}</span>',
            bg.get(obj.status, '#f3f4f6'),
            colors.get(obj.status, '#374151'),
            obj.get_status_display(),
        )

    @admin.display(description='Total')
    def total_display(self, obj):
        return f"₹{obj.total:,.2f}"


# ── OrderItem Admin (for click-through from Order inline) ─────────────────────

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['order', 'menu_item_name', 'quantity', 'dining_option', 'spice_level', 'unit_price']
    list_filter = ['dining_option', 'order__restaurant']
    search_fields = ['menu_item_name', 'order__customer_name']
    readonly_fields = [
        'id', 'order', 'menu_item', 'menu_item_name',
        'unit_price', 'parcel_surcharge', 'quantity',
        'dining_option', 'spice_level',
        'prep_started_at', 'completed_at', 'completed_by',
    ]
    inlines = [OrderItemAddOnInline]


# ── StockReservation Admin ────────────────────────────────────────────────────

@admin.register(StockReservation)
class StockReservationAdmin(admin.ModelAdmin):
    list_display = ['order', 'menu_item', 'addon', 'quantity', 'is_confirmed', 'expires_at', 'reserved_at']
    list_filter = ['is_confirmed']
    readonly_fields = [f.name for f in StockReservation._meta.fields]
    ordering = ['-reserved_at']


# ── RestaurantOrderCounter Admin ──────────────────────────────────────────────

@admin.register(RestaurantOrderCounter)
class RestaurantOrderCounterAdmin(admin.ModelAdmin):
    list_display = ['restaurant', 'last_number', 'last_reset']
    readonly_fields = ['id', 'restaurant', 'last_number', 'last_reset']


# ── PaymentTransaction Admin ─────────────────────────────────────────────────

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id_short', 'restaurant', 'order', 'provider', 'state',
        'amount_display', 'gateway_account_source', 'created_at',
    ]
    list_filter = ['state', 'provider', 'gateway_account_source', 'restaurant']
    search_fields = ['id', 'provider_order_id', 'provider_payment_id', 'order__id']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    readonly_fields = [f.name for f in PaymentTransaction._meta.fields]
    inlines = [PaymentEventInline]

    @admin.display(description='ID')
    def id_short(self, obj):
        return str(obj.id)[:8]

    @admin.display(description='Amount')
    def amount_display(self, obj):
        return f"₹{obj.amount:,.2f}"


# ── RestaurantBalance Admin ──────────────────────────────────────────────────

@admin.register(RestaurantBalance)
class RestaurantBalanceAdmin(admin.ModelAdmin):
    list_display = [
        'restaurant', 'order_number', 'gross_display', 'commission_display',
        'net_display', 'settlement_status', 'gateway_account_source', 'created_at',
    ]
    list_filter = ['settlement_status', 'gateway_account_source', 'restaurant']
    search_fields = ['restaurant__name', 'order__id', 'settlement_reference']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    readonly_fields = [
        'id', 'restaurant', 'order', 'payment_transaction',
        'gross_amount', 'platform_commission', 'commission_rate_snapshot', 'net_amount',
        'gateway_account_source', 'created_at',
    ]

    @admin.display(description='Order')
    def order_number(self, obj):
        return obj.order.order_number if obj.order else '—'

    @admin.display(description='Gross')
    def gross_display(self, obj):
        return f"₹{obj.gross_amount:,.2f}"

    @admin.display(description='Commission')
    def commission_display(self, obj):
        return f"₹{obj.platform_commission:,.2f} ({obj.commission_rate_snapshot}%)"

    @admin.display(description='Net')
    def net_display(self, obj):
        return f"₹{obj.net_amount:,.2f}"


# ── RestaurantLedger Admin ───────────────────────────────────────────────────

@admin.register(RestaurantLedger)
class RestaurantLedgerAdmin(admin.ModelAdmin):
    list_display = [
        'restaurant', 'entry_type', 'amount_display', 'balance_display', 
        'reference', 'created_at'
    ]
    list_filter = ['entry_type', 'restaurant']
    search_fields = ['restaurant__name', 'reference', 'order__id', 'settlement__id']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    readonly_fields = [f.name for f in RestaurantLedger._meta.fields]

    @admin.display(description='Amount')
    def amount_display(self, obj):
        color = 'green' if obj.amount > 0 else 'red'
        formatted_amount = f"₹{obj.amount:,.2f}"
        return format_html('<span style="color:{};font-weight:bold">{}</span>', color, formatted_amount)

    @admin.display(description='Balance')
    def balance_display(self, obj):
        return f"₹{obj.balance_after:,.2f}"


# ── Settlement Admin ─────────────────────────────────────────────────────────

from django.utils import timezone

@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = [
        'id_short', 'restaurant', 'amount_display', 'status', 
        'reference_number', 'settled_at', 'created_at'
    ]
    list_filter = ['status', 'restaurant']
    search_fields = ['restaurant__name', 'reference_number', 'id']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    readonly_fields = ['id', 'created_at', 'settled_at', 'settled_by']

    @admin.display(description='ID')
    def id_short(self, obj):
        return str(obj.id)[:8]

    @admin.display(description='Amount')
    def amount_display(self, obj):
        return f"₹{obj.amount:,.2f}"

    def save_model(self, request, obj, form, change):
        # We handle settlement logging to ledger when status transitions to COMPLETED.
        # This is a basic implementation. Real-world apps might use a custom view or action.
        super().save_model(request, obj, form, change)
        
        if obj.status == Settlement.Status.COMPLETED and not RestaurantLedger.objects.filter(settlement=obj).exists():
            from ordering.ledger.services import RestaurantLedgerService
            obj.settled_by = request.user
            obj.settled_at = timezone.now()
            obj.save(update_fields=['settled_by', 'settled_at'])
            
            RestaurantLedgerService().record_settlement(
                settlement=obj,
                created_by=request.user
            )

# ── WebhookLog Admin ─────────────────────────────────────────────────────────

from ordering.models import WebhookLog

@admin.register(WebhookLog)
class WebhookLogAdmin(admin.ModelAdmin):
    change_list_template = "admin/ordering/webhooklog/change_list.html"
    list_display = [
        'id_short', 'provider', 'event_type', 'signature_valid', 
        'processed_at', 'status_badge', 'created_at'
    ]
    list_filter = ['signature_valid', 'provider', 'status']
    search_fields = ['id', 'provider_event_id']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    readonly_fields = [f.name for f in WebhookLog._meta.fields]

    @admin.display(description='Event Type')
    def event_type(self, obj):
        import json
        try:
            payload = json.loads(obj.raw_payload)
            return payload.get('event', 'unknown')
        except Exception:
            return 'parse_error'

    @admin.display(description='ID')
    def id_short(self, obj):
        return str(obj.id)[:8]

    @admin.display(description='Status')
    def status_badge(self, obj):
        if obj.status == WebhookLog.Status.DEAD_LETTERED:
            return format_html('<span style="color:white;background:red;padding:2px 6px;border-radius:4px;font-size:10px;">DEAD LETTERED</span><br><span style="font-size:10px;color:red;">Retries: {}</span>', obj.retry_count)
        elif obj.status == WebhookLog.Status.PROCESSED:
            return format_html('<span style="color:white;background:green;padding:2px 6px;border-radius:4px;font-size:10px;">PROCESSED</span>')
        elif obj.retry_count > 0:
            return format_html('<span style="color:white;background:orange;padding:2px 6px;border-radius:4px;font-size:10px;">RETRYING</span><br><span style="font-size:10px;color:orange;">Retries: {}</span>', obj.retry_count)
        return format_html('<span style="color:black;background:lightgray;padding:2px 6px;border-radius:4px;font-size:10px;">PENDING</span>')

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        # Compute unprocessed count for the dashboard metric
        unprocessed_count = WebhookLog.objects.filter(
            signature_valid=True,
            status=WebhookLog.Status.PENDING
        ).count()
        dead_lettered_count = WebhookLog.objects.filter(
            status=WebhookLog.Status.DEAD_LETTERED
        ).count()
        extra_context['unprocessed_count'] = unprocessed_count
        extra_context['dead_lettered_count'] = dead_lettered_count
        return super().changelist_view(request, extra_context=extra_context)
