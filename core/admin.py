# core/admin.py
from decimal import Decimal
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Sum, Q, Subquery, OuterRef
from django.utils import timezone
from django.utils.html import format_html
from django.http import HttpResponse
import csv

from .models import (
    AddOn, ItemType, MenuItem, MenuItemAddOn,
    JournalEntry, JournalLine, MonthlyPlatformFeeStatement,
    PlatformFeeRecord, Restaurant,
    MerchantLedgerBalance, RestaurantConfig,
    SettlementBatch, SettlementRecord, StaffFilter, User,
)
from .timeutils import local_day_bounds


# ── Inlines ──────────────────────────────────────────────────────────────────

class RestaurantConfigInline(admin.StackedInline):
    model = RestaurantConfig
    can_delete = False
    verbose_name_plural = 'Restaurant config'
    fields = ('is_open', 'reopen_message', 'admin_cash_enabled', 'cash_enabled', 'admin_upi_enabled', 'upi_enabled', 'kds_prep_enabled', 'admin_post_payment_enabled', 'post_payment_enabled', 'cash_payment_timeout_minutes')



# ── Restaurant Admin ──────────────────────────────────────────────────────────

@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display   = [
        'name',
        'slug',
        'is_active',
        'owner_count',
        'current_balance',
        'today_revenue',
        'commission_rate_display',
        'cash_timeout_display',
        'today_platform_fee',
        'month_platform_fee',
        'created_at',
    ]
    list_filter    = ['is_active']
    search_fields  = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['created_at', 'id', 'menu_qr_code_url']
    inlines        = [RestaurantConfigInline]
    actions        = ['deactivate_restaurants', 'activate_restaurants']

    fieldsets = (
        (None, {
            'fields': ('id', 'name', 'slug', 'logo', 'menu_qr_code_url', 'is_active', 'created_at')
        }),
        ('Platform Fee Overrides', {
            'fields': ('custom_fee_mode', 'custom_fee_percent', 'custom_fee_fixed_amount'),
            'description': 'Leave mode blank to use the global Platform Settings default.',
        }),
    )

    def get_queryset(self, request):
        from ordering.models import RestaurantLedger
        qs = super().get_queryset(request)
        latest_ledger = RestaurantLedger.objects.filter(
            restaurant=OuterRef('pk')
        ).order_by('-created_at').values('balance_after')[:1]
        
        return qs.annotate(
            annotated_balance=Subquery(latest_ledger)
        )

    @admin.display(description='Current Balance', ordering='annotated_balance')
    def current_balance(self, obj):
        bal = getattr(obj, 'annotated_balance', None)
        if bal is None:
            bal = Decimal('0.00')
        color = 'green' if bal > 0 else 'red'
        formatted_bal = f"₹{bal:,.2f}"
        return format_html('<span style="color:{};font-weight:bold">{}</span>', color, formatted_bal)

    @admin.display(description='Owners')
    def owner_count(self, obj):
        return obj.users.filter(role=User.Role.OWNER, is_active=True).count()

    @admin.display(description="Today's revenue")
    def today_revenue(self, obj):
        from kitchen.models import PaymentEvent
        today = timezone.localdate()
        today_start, today_end = local_day_bounds(today)
        total = PaymentEvent.objects.filter(
            restaurant=obj,
            event_type__in=['CASH_COLLECTED', 'RAZORPAY_CONFIRMED'],
            created_at__gte=today_start,
            created_at__lt=today_end,
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        return f"₹{total:,.2f}"

    @admin.display(description="Today's platform fee")
    def today_platform_fee(self, obj):
        today = timezone.localdate()
        today_start, today_end = local_day_bounds(today)
        total = PlatformFeeRecord.objects.filter(
            restaurant=obj,
            is_refunded=False,
            created_at__gte=today_start,
            created_at__lt=today_end,
        ).aggregate(t=Sum('fee_amount'))['t'] or Decimal('0.00')
        return f"₹{total:,.2f}"

    @admin.display(description='Monthly platform fee')
    def month_platform_fee(self, obj):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        statement = MonthlyPlatformFeeStatement.objects.filter(
            restaurant=obj,
            month_date=month_start
        ).first()
        total = statement.total_fee_amount if statement else Decimal('0.00')
        return f"₹{total:,.2f}"

    @admin.display(description='Platform Fee Setting')
    def commission_rate_display(self, obj):
        if obj.fee_mode == Restaurant.FeeMode.PERCENTAGE:
            return f"{obj.fee_percent}%"
        elif obj.fee_mode == Restaurant.FeeMode.FIXED:
            return f"₹{obj.fee_fixed_amount}"
        elif obj.fee_mode == Restaurant.FeeMode.HYBRID:
            return f"{obj.fee_percent}% + ₹{obj.fee_fixed_amount}"
        return "Unknown"

    @admin.display(description='Cash Timeout')
    def cash_timeout_display(self, obj):
        try:
            config = obj.config
            return f"{config.cash_payment_timeout_minutes}m"
        except Exception:
            return "10m"

    @admin.action(description='Deactivate selected restaurants')
    def deactivate_restaurants(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} restaurant(s) deactivated.")

    @admin.action(description='Activate selected restaurants')
    def activate_restaurants(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} restaurant(s) activated.")


# ── User / Owner Admin ────────────────────────────────────────────────────────

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display   = [
        'username',
        'restaurant',
        'role',
        'is_active',
        'must_change_password',
        'mfa_enabled',
        'last_login',
    ]
    list_filter    = ['role', 'restaurant', 'is_active', 'must_change_password', 'mfa_enabled']
    search_fields  = ['username', 'first_name', 'last_name']
    readonly_fields = ['last_login', 'date_joined', 'id']
    actions        = ['force_password_reset', 'deactivate_users', 'activate_users', 'enable_mfa_for_users', 'disable_mfa_for_users']

    fieldsets = BaseUserAdmin.fieldsets + (
        (settings.APP_NAME, {
            'fields': (
                'role',
                'restaurant',
                'allow_cash_collection',
                'allow_order_completion',
                'must_change_password',
                'mfa_enabled',
                'photo',
            )
        }),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (settings.APP_NAME, {
            'fields': (
                'role',
                'restaurant',
                'allow_cash_collection',
                'allow_order_completion',
                'must_change_password',
                'mfa_enabled',
            )
        }),
    )

    @admin.action(description='Force password reset on next login')
    def force_password_reset(self, request, queryset):
        updated = queryset.update(must_change_password=True)
        self.message_user(request, f"{updated} user(s) flagged for password reset.")

    @admin.action(description='Deactivate selected users')
    def deactivate_users(self, request, queryset):
        updated = queryset.exclude(role=User.Role.OWNER).update(is_active=False)
        self.message_user(request, f"{updated} staff user(s) deactivated. Owners are protected.")

    @admin.action(description='Activate selected users')
    def activate_users(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} user(s) activated.")

    @admin.action(description='Require 2FA for selected users')
    def enable_mfa_for_users(self, request, queryset):
        updated = queryset.update(mfa_enabled=True)
        self.message_user(request, f"{updated} user(s) flagged to require 2FA.")

    @admin.action(description='Disable 2FA for selected users')
    def disable_mfa_for_users(self, request, queryset):
        updated = queryset.update(mfa_enabled=False)
        self.message_user(request, f"{updated} user(s) had 2FA requirement disabled.")


# ── PlatformFeeRecord Admin ───────────────────────────────────────────────────

@admin.register(PlatformFeeRecord)
class PlatformFeeRecordAdmin(admin.ModelAdmin):
    list_display   = [
        'created_at', 'restaurant', 'order_ref',
        'order_total_display', 'fee_amount_display',
        'fee_rate_snapshot', 'is_refunded'
    ]
    list_filter    = ['restaurant', 'is_refunded']
    search_fields  = ['order_ref']
    date_hierarchy = 'created_at'
    ordering       = ['-created_at']
    actions        = ['export_fee_report_csv']

    def get_readonly_fields(self, request, obj=None):
        all_fields = [f.name for f in self.model._meta.fields]
        return all_fields

    @admin.display(description='Order total')
    def order_total_display(self, obj):
        return f"₹{obj.order_total:,.2f}"

    @admin.display(description='Platform fee')
    def fee_amount_display(self, obj):
        color = '#b91c1c' if obj.is_refunded else '#1f7a4d'
        label = f"₹{obj.fee_amount:,.2f}"
        if obj.is_refunded:
            label += ' (refunded)'
        return format_html('<span style="color:{}">{}</span>', color, label)

    @admin.action(description='Export fee report as CSV')
    def export_fee_report_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="order_flow_fees.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Date', 'Restaurant', 'Order ref',
            'Order total', 'Fee amount', 'Fee rate %',
            'Refunded', 'Created at'
        ])
        for rec in queryset.select_related('restaurant').order_by('-created_at'):
            writer.writerow([
                rec.created_at.date(),
                rec.restaurant.name if rec.restaurant else '—',
                rec.order_ref,
                rec.order_total,
                rec.fee_amount,
                rec.fee_rate_snapshot,
                'Yes' if rec.is_refunded else 'No',
                rec.created_at.strftime('%Y-%m-%d %H:%M'),
            ])
        return response


# ── MonthlyPlatformFeeStatement Admin ─────────────────────────────────────────

@admin.register(MonthlyPlatformFeeStatement)
class MonthlyPlatformFeeStatementAdmin(admin.ModelAdmin):
    list_display = [
        'month_date_display', 'restaurant',
        'total_orders_count', 'total_revenue_display',
        'total_fee_amount_display', 'is_paid'
    ]
    list_filter = ['is_paid', 'restaurant', 'month_date']
    search_fields = ['restaurant__name']
    date_hierarchy = 'month_date'
    ordering = ['-month_date', 'restaurant']
    readonly_fields = ['created_at', 'updated_at']
    actions = ['mark_as_paid', 'mark_as_unpaid', 'export_statement_csv']

    @admin.display(description='Month')
    def month_date_display(self, obj):
        return obj.month_date.strftime('%B %Y')

    @admin.display(description='Total revenue')
    def total_revenue_display(self, obj):
        return f"₹{obj.total_revenue:,.2f}"

    @admin.display(description='Total fee')
    def total_fee_amount_display(self, obj):
        return f"₹{obj.total_fee_amount:,.2f}"

    @admin.action(description='Mark selected statements as paid')
    def mark_as_paid(self, request, queryset):
        updated = queryset.update(is_paid=True, paid_at=timezone.now())
        self.message_user(request, f"{updated} statement(s) marked as paid.")

    @admin.action(description='Mark selected statements as unpaid')
    def mark_as_unpaid(self, request, queryset):
        updated = queryset.update(is_paid=False, paid_at=None)
        self.message_user(request, f"{updated} statement(s) marked as unpaid.")

    @admin.action(description='Export monthly statements as CSV')
    def export_statement_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="monthly_fee_statements.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Month', 'Restaurant', 'Total Orders',
            'Total Revenue', 'Total Fee Owed', 'Paid Status', 'Paid Date'
        ])
        for stmt in queryset.select_related('restaurant').order_by('-month_date', 'restaurant__name'):
            writer.writerow([
                stmt.month_date.strftime('%B %Y'),
                stmt.restaurant.name if stmt.restaurant else '—',
                stmt.total_orders_count,
                stmt.total_revenue,
                stmt.total_fee_amount,
                'Yes' if stmt.is_paid else 'No',
                stmt.paid_at.strftime('%Y-%m-%d %H:%M') if stmt.paid_at else '—',
            ])
        return response


# ── Menu admins (lightweight — owners manage menu, but useful for debugging) ──


class MenuItemAddOnInline(admin.TabularInline):
    model = MenuItemAddOn
    extra = 1
    autocomplete_fields = ['addon']


@admin.register(ItemType)
class ItemTypeAdmin(admin.ModelAdmin):
    list_display  = ['name', 'restaurant', 'sort_order']
    list_filter   = ['restaurant']
    search_fields = ['name']
    ordering      = ['restaurant', 'sort_order', 'name']


@admin.register(AddOn)
class AddOnAdmin(admin.ModelAdmin):
    list_display  = ['name', 'restaurant', 'price', 'max_qty', 'stock', 'is_active']
    list_filter   = ['restaurant', 'is_active']
    search_fields = ['name']
    readonly_fields = ['id']


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display  = ['name', 'restaurant', 'item_type', 'base_price', 'is_available', 'is_veg']
    list_filter   = ['restaurant', 'is_available', 'is_veg', 'item_type']
    search_fields = ['name', 'restaurant__name']
    readonly_fields = ['id']
    inlines       = [MenuItemAddOnInline]


@admin.register(StaffFilter)
class StaffFilterAdmin(admin.ModelAdmin):
    list_display = ['name', 'restaurant', 'item_count', 'updated_at']
    list_filter = ['restaurant']
    search_fields = ['name', 'restaurant__name']
    filter_horizontal = ['items']

    @admin.display(description='Items')
    def item_count(self, obj):
        return obj.items.count()


@admin.register(MenuItemAddOn)
class MenuItemAddOnAdmin(admin.ModelAdmin):
    list_display  = ['menu_item', 'addon']
    list_filter   = ['menu_item__restaurant']
    search_fields = ['menu_item__name', 'addon__name']
    autocomplete_fields = ['menu_item', 'addon']


# ── Ledger Admin ─────────────────────────────────────────────────────────────

@admin.register(MerchantLedgerBalance)
class MerchantLedgerBalanceAdmin(admin.ModelAdmin):
    list_display = ('restaurant', 'available_balance', 'pending_settlement', 'updated_at')
    search_fields = ('restaurant__name',)
    readonly_fields = ('available_balance', 'pending_settlement', 'updated_at')

class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0
    readonly_fields = ('account_type', 'amount', 'created_at')
    can_delete = False

@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'restaurant', 'entry_type', 'reference_id', 'created_at')
    list_filter = ('entry_type', 'created_at')
    search_fields = ('restaurant__name', 'reference_id')
    readonly_fields = ('id', 'restaurant', 'entry_type', 'reference_id', 'created_at')
    inlines = [JournalLineInline]

@admin.register(SettlementBatch)
class SettlementBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'total_amount', 'created_at', 'processed_at')
    list_filter = ('status', 'created_at')
    readonly_fields = ('id', 'status', 'total_amount', 'created_at', 'processed_at')

@admin.register(SettlementRecord)
class SettlementRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'restaurant', 'batch', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('restaurant__name', 'batch__id')
    readonly_fields = ('id', 'restaurant', 'batch', 'amount', 'status', 'provider_transfer_id', 'created_at', 'updated_at')


