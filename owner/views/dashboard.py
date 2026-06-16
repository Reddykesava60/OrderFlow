import csv
import io
import logging
import secrets
import string
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import logout as auth_logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Count, Q, Exists, OuterRef
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from core.mixins import OwnerRequiredMixin
from core.models import (
    AddOn, ItemType, MenuItem, MenuItemAddOn,
    OwnerAuditLog, PlatformFeeRecord, Restaurant, RestaurantPaymentConfig, StaffFilter, User,
)
from core.ratelimit import rate_limit
from core.storage import get_supabase_storage_config, upload_bytes_public, upload_public_image
from core.timeutils import local_day_bounds
from kitchen.models import PaymentEvent
from ordering.models import Order, OrderItem, OrderItemAddOn
from ordering.orders.services import expire_overdue_unpaid_cash_orders

logger = logging.getLogger(__name__)


def _today_stats(restaurant):
    """
    Return gross revenue, total platform fees, net revenue, and
    order counts for today, derived entirely from the immutable ledger.
    """
    from ordering.models import RestaurantLedger
    today = timezone.localdate()
    today_start, today_end = local_day_bounds(today)
    ledger_entries = RestaurantLedger.objects.filter(restaurant=restaurant, created_at__gte=today_start, created_at__lt=today_end)
    gross = ledger_entries.filter(entry_type=RestaurantLedger.EntryType.CREDIT_ORDER).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_fees_negative = ledger_entries.filter(entry_type=RestaurantLedger.EntryType.DEBIT_PLATFORM_FEE).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_fees = abs(total_fees_negative)
    net = gross - total_fees
    cash_total = ledger_entries.filter(entry_type=RestaurantLedger.EntryType.CREDIT_ORDER, order__payment_method=Order.PaymentMethod.CASH).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    upi_total = ledger_entries.filter(entry_type=RestaurantLedger.EntryType.CREDIT_ORDER, order__payment_method=Order.PaymentMethod.UPI).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    post_total = ledger_entries.filter(entry_type=RestaurantLedger.EntryType.CREDIT_ORDER, order__payment_method=Order.PaymentMethod.POST_PAYMENT).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    order_counts = Order.objects.filter(restaurant=restaurant, status__in=[Order.Status.PENDING, Order.Status.PREP_STARTED, Order.Status.COMPLETED], created_at__gte=today_start, created_at__lt=today_end).aggregate(total=Count('id'), cash=Count('id', filter=Q(payment_method=Order.PaymentMethod.CASH)), upi=Count('id', filter=Q(payment_method=Order.PaymentMethod.UPI)), post=Count('id', filter=Q(payment_method=Order.PaymentMethod.POST_PAYMENT)))
    return {'gross': gross, 'fees': total_fees, 'net': net, 'cash_total': cash_total, 'upi_total': upi_total, 'post_total': post_total, 'order_total': order_counts['total'], 'order_cash': order_counts['cash'], 'order_upi': order_counts['upi'], 'order_post': order_counts['post']}

def _month_stats(restaurant):
    """
    Return month-to-date stats derived entirely from the immutable ledger.
    """
    from ordering.models import RestaurantLedger
    today = timezone.localdate()
    month_start = today.replace(day=1)
    ledger_entries = RestaurantLedger.objects.filter(restaurant=restaurant, created_at__gte=month_start)
    gross = ledger_entries.filter(entry_type=RestaurantLedger.EntryType.CREDIT_ORDER).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_fees_negative = ledger_entries.filter(entry_type=RestaurantLedger.EntryType.DEBIT_PLATFORM_FEE).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_fees = abs(total_fees_negative)
    net = gross - total_fees
    return {'gross': gross, 'fees': total_fees, 'net': net}

def _dashboard_inventory_cards(restaurant):
    today = timezone.localdate()
    today_start, today_end = local_day_bounds(today)
    active_statuses = [Order.Status.PENDING, Order.Status.PREP_STARTED, Order.Status.COMPLETED]
    item_sales = {row['menu_item_id']: row['sold_today'] for row in OrderItem.objects.filter(order__restaurant=restaurant, order__created_at__gte=today_start, order__created_at__lt=today_end, order__status__in=active_statuses, menu_item_id__isnull=False).values('menu_item_id').annotate(sold_today=Sum('quantity'))}
    addon_sales = {row['addon_id']: row['sold_today'] for row in OrderItemAddOn.objects.filter(order_item__order__restaurant=restaurant, order_item__order__created_at__gte=today_start, order_item__order__created_at__lt=today_end, order_item__order__status__in=active_statuses, addon_id__isnull=False).values('addon_id').annotate(sold_today=Sum('quantity'))}
    item_ids_with_addons = set(MenuItemAddOn.objects.filter(menu_item__restaurant=restaurant, addon__is_active=True).values_list('menu_item_id', flat=True))
    items = list(MenuItem.objects.filter(restaurant=restaurant).select_related('item_type').order_by('name'))
    for item in items:
        item.sold_today = item_sales.get(item.id, 0) or 0
        item.stock_label = 'Unlimited' if item.stock is None else str(item.stock)
        item.stock_state = 'out' if item.stock == 0 else 'limited' if item.stock is not None else 'unlimited'
        item.has_addons = item.id in item_ids_with_addons
    items.sort(key=lambda menu_item: (-menu_item.sold_today, menu_item.name.lower()))
    addons = list(AddOn.objects.filter(restaurant=restaurant).select_related().order_by('name'))
    for addon in addons:
        addon.sold_today = addon_sales.get(addon.id, 0) or 0
        addon.stock_label = 'Unlimited' if addon.stock is None else str(addon.stock)
        addon.stock_state = 'out' if addon.stock == 0 else 'limited' if addon.stock is not None else 'unlimited'
    addons.sort(key=lambda addon_item: (-addon_item.sold_today, addon_item.name.lower()))
    return (items, addons)

class DashboardView(OwnerRequiredMixin, View):

    def get(self, request):
        restaurant = self.get_restaurant()
        expire_overdue_unpaid_cash_orders(restaurant=restaurant)
        today = timezone.localdate()
        stats = _today_stats(restaurant)
        month_stats = _month_stats(restaurant)
        item_cards, addon_cards = _dashboard_inventory_cards(restaurant)
        today_start, today_end = local_day_bounds(today)
        today_orders = Order.objects.filter(restaurant=restaurant, created_at__gte=today_start, created_at__lt=today_end).order_by('-created_at')
        from ordering.models import RestaurantLedger, Settlement
        last_entry = RestaurantLedger.objects.filter(restaurant=restaurant).order_by('-created_at').first()
        available_balance = last_entry.balance_after if last_entry else Decimal('0.00')
        pending_settlements = Settlement.objects.filter(restaurant=restaurant, status__in=[Settlement.Status.PENDING, Settlement.Status.PROCESSING]).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        return render(request, 'owner/dashboard.html', {'restaurant': restaurant, 'stats': stats, 'month_stats': month_stats, 'available_balance': available_balance, 'pending_settlements': pending_settlements, 'item_cards': item_cards, 'addon_cards': addon_cards, 'today_orders': today_orders})

class ReconcileView(OwnerRequiredMixin, View):

    def get(self, request):
        restaurant = self.get_restaurant()
        today = timezone.localdate()
        date_str = request.GET.get('date', str(today))
        try:
            from datetime import date
            filter_date = date.fromisoformat(date_str)
        except ValueError:
            filter_date = today
        filter_start, filter_end = local_day_bounds(filter_date)
        events = PaymentEvent.objects.filter(restaurant=restaurant, created_at__gte=filter_start, created_at__lt=filter_end).select_related('staff_user', 'order').order_by('-created_at')
        fee_records = PlatformFeeRecord.objects.filter(restaurant=restaurant, created_at__gte=filter_start, created_at__lt=filter_end).order_by('-created_at')
        digital_events = events.filter(event_type__in=[PaymentEvent.EventType.RAZORPAY_CONFIRMED, PaymentEvent.EventType.DIGITAL_PAYMENT_CONFIRMED])
        digital_total = digital_events.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        digital_count = digital_events.count()
        cash_events = events.filter(event_type=PaymentEvent.EventType.CASH_COLLECTED)
        cash_total = cash_events.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        cash_count = cash_events.count()
        post_orders = Order.objects.filter(restaurant=restaurant, created_at__gte=filter_start, created_at__lt=filter_end, payment_method=Order.PaymentMethod.POST_PAYMENT, status__in=[Order.Status.PENDING, Order.Status.PREP_STARTED, Order.Status.COMPLETED])
        post_total = post_orders.aggregate(t=Sum('total'))['t'] or Decimal('0.00')
        post_count = post_orders.count()
        gross = cash_total + digital_total + post_total
        total_fees = fee_records.filter(is_refunded=False).aggregate(t=Sum('fee_amount'))['t'] or Decimal('0.00')
        net = gross - total_fees
        fee_map = {str(fr.order_id): fr for fr in fee_records if fr.order_id}
        cash_by_staff = list(cash_events.values('staff_user__username').annotate(total=Sum('amount'), count=Count('id')).order_by('-total'))
        post_count = post_orders.count()
        orders = Order.objects.filter(restaurant=restaurant, created_at__gte=filter_start, created_at__lt=filter_end).order_by('-created_at')
        if request.GET.get('export') == 'csv':
            return self._export_csv(restaurant, orders, fee_records, filter_date)
        return render(request, 'owner/reconcile.html', {'restaurant': restaurant, 'events': events, 'orders': orders, 'fee_records': fee_records, 'fee_map': fee_map, 'filter_date': filter_date, 'gross': gross, 'total_fees': total_fees, 'net': net, 'cash_total': cash_total, 'cash_count': cash_count, 'cash_by_staff': cash_by_staff, 'digital_total': digital_total, 'digital_count': digital_count, 'post_total': post_total, 'post_count': post_count, 'month_stats': _month_stats(restaurant)})

    def _export_csv(self, restaurant, orders, fee_records, filter_date):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="dineflow_{restaurant.slug}_{filter_date}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Time', 'Order Number', 'Status', 'Payment Method', 'Total', 'Fee amount', 'Fee rate %', 'Refunded'])
        fee_map = {fr.order_id: fr for fr in fee_records if fr.order_id}
        for ord in orders:
            fr = fee_map.get(ord.id)
            writer.writerow([ord.created_at.strftime('%H:%M'), ord.order_number, ord.get_status_display(), ord.get_payment_method_display(), ord.total, fr.fee_amount if fr else '', fr.fee_rate_snapshot if fr else '', 'Yes' if fr and fr.is_refunded else 'No' if fr else ''])
        return response