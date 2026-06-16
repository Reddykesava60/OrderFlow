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


def _csv_safe(value):
    """Escape CSV cell values that could be interpreted as formulas by spreadsheet apps."""
    s = str(value) if value is not None else ''
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r', '\n'):
        return "'" + s
    return s

class OwnerOrderReceiptView(OwnerRequiredMixin, View):

    def get(self, request, order_id):
        restaurant = self.get_restaurant()
        expire_overdue_unpaid_cash_orders(restaurant=restaurant)
        order = get_object_or_404(Order.objects.select_related('restaurant').prefetch_related('items__addons'), id=order_id, restaurant=restaurant)
        return render(request, 'owner/order_receipt.html', {'restaurant': restaurant, 'order': order})