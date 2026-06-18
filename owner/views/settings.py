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

from owner.views.staff import _write_owner_audit
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


class ConfigView(OwnerRequiredMixin, View):

    def get(self, request):
        restaurant = self.get_restaurant()
        payment_config, _ = RestaurantPaymentConfig.objects.get_or_create(restaurant=restaurant)
        return render(request, 'owner/config.html', {'restaurant': restaurant, 'config': restaurant.config, 'payment_config': payment_config, 'menu_public_url': request.build_absolute_uri(reverse('ordering:menu', args=[restaurant.slug]))})

    def post(self, request):
        restaurant = self.get_restaurant()
        config = restaurant.config
        payment_config, _ = RestaurantPaymentConfig.objects.get_or_create(restaurant=restaurant)
        data = request.POST
        before_config = {'is_open': config.is_open, 'reopen_message': config.reopen_message, 'cash_enabled': config.cash_enabled, 'upi_enabled': config.upi_enabled, 'slug': restaurant.slug}
        before_payment = {'account_name': payment_config.account_name, 'razorpay_key_id_present': bool(payment_config.razorpay_key_id), 'razorpay_key_secret_present': bool(payment_config.get_razorpay_key_secret()), 'razorpay_webhook_secret_present': bool(payment_config.get_razorpay_webhook_secret()), 'is_active': payment_config.is_active}
        config.is_open = 'is_open' in data
        config.reopen_message = data.get('reopen_message', '').strip()
        cash = 'cash_enabled' in data
        upi = 'upi_enabled' in data
        if not cash and (not upi):
            messages.error(request, 'At least one payment method must be enabled.')
            return redirect('owner:config')
        payment_config.account_name = data.get('account_name', '').strip()
        payment_config.razorpay_key_id = data.get('razorpay_key_id', '').strip()
        key_secret = data.get('razorpay_key_secret', '').strip()
        webhook_secret = data.get('razorpay_webhook_secret', '').strip()
        if key_secret:
            payment_config.set_razorpay_key_secret(key_secret)
        if webhook_secret:
            payment_config.set_razorpay_webhook_secret(webhook_secret)
        payment_config.is_active = 'razorpay_is_active' in data
        if upi and (not payment_config.is_usable):
            messages.error(request, "To enable UPI, complete and activate this restaurant's Razorpay settings first.")
            return redirect('owner:config')
        config.cash_enabled = cash
        config.upi_enabled = upi
        config.save()
        payment_config.save()
        new_slug = data.get('slug', '').strip().lower()
        if new_slug and new_slug != restaurant.slug:
            from django.utils.text import slugify
            clean_slug = slugify(new_slug)
            if not clean_slug:
                messages.error(request, 'Invalid slug.')
                return redirect('owner:config')
            if Restaurant.objects.filter(slug=clean_slug).exclude(id=restaurant.id).exists():
                messages.error(request, f"Slug '{clean_slug}' is already taken.")
                return redirect('owner:config')
            restaurant.slug = clean_slug
            restaurant.menu_qr_code_url = ''
            restaurant.save(update_fields=['slug', 'menu_qr_code_url'])
            messages.info(request, f"Slug changed to '{clean_slug}'. Update your QR code.")
        messages.success(request, 'Settings saved.')
        _write_owner_audit(restaurant=restaurant, user=request.user, action=OwnerAuditLog.ActionType.UPDATE_RESTAURANT_CONFIG, details={'restaurant_config_before': before_config, 'restaurant_config_after': {'is_open': config.is_open, 'reopen_message': config.reopen_message, 'cash_enabled': config.cash_enabled, 'upi_enabled': config.upi_enabled, 'slug': restaurant.slug}, 'payment_config_before': before_payment, 'payment_config_after': {'account_name': payment_config.account_name, 'razorpay_key_id_present': bool(payment_config.razorpay_key_id), 'razorpay_key_secret_present': bool(payment_config.get_razorpay_key_secret()), 'razorpay_webhook_secret_present': bool(payment_config.get_razorpay_webhook_secret()), 'is_active': payment_config.is_active}})
        return redirect('owner:config')

class MenuQrCodeDownloadView(OwnerRequiredMixin, View):
    """
    GET /owner/config/qr-code/menu.png
    Generates a QR code pointing to the public menu URL and returns it as a download.
    Also uploads the PNG to Supabase Storage if configured (bucket: qr-codes).
    """

    def get(self, request):
        restaurant = self.get_restaurant()
        menu_path = reverse('ordering:menu', args=[restaurant.slug])
        menu_url = request.build_absolute_uri(menu_path)
        import qrcode
        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(menu_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        buf = io.BytesIO()
        img.save(buf)
        png_bytes = buf.getvalue()
        if get_supabase_storage_config():
            try:
                public_url = upload_bytes_public(bucket='qr-codes', path=f'{restaurant.id}.png', content=png_bytes, content_type='image/png')
                restaurant.menu_qr_code_url = public_url
                restaurant.save(update_fields=['menu_qr_code_url'])
            except Exception:
                logger.exception('Failed uploading menu QR code to Supabase Storage for %s', restaurant.id)
        response = HttpResponse(png_bytes, content_type='image/png')
        response['Content-Disposition'] = f'attachment; filename="{restaurant.slug}_menu_qr.png"'
        return response