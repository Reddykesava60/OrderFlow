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

import base64
import qrcode
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

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


def _gen_temp_password(length=12):
    """Cryptographically random temp password — shown once, never stored in plain text."""
    alphabet = string.ascii_letters + string.digits + '!@#$%'
    return ''.join((secrets.choice(alphabet) for _ in range(length)))

class SecureLogoutView(View):
    http_method_names = ['post']

    def post(self, request):
        auth_logout(request)
        return redirect('owner:login')

@method_decorator(rate_limit('owner_login', limit=10, window=300), name='dispatch')
class OwnerLoginView(LoginView):
    template_name = 'owner/login.html'

@method_decorator(rate_limit('change_password', limit=5, window=900), name='dispatch')
class ChangePasswordView(View):

    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('owner:login')
        return render(request, 'owner/change_password.html', {'must_change': getattr(request.user, 'must_change_password', False)})

    def post(self, request):
        if not request.user.is_authenticated:
            return redirect('owner:login')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return redirect('owner:change_password')
        try:
            validate_password(new_password, user=request.user)
        except ValidationError as exc:
            for message in exc.messages:
                messages.error(request, message)
            return redirect('owner:change_password')
        request.user.set_password(new_password)
        request.user.must_change_password = False
        request.user.save(update_fields=['password', 'must_change_password'])
        update_session_auth_hash(request, request.user)
        messages.success(request, 'Password updated.')
        if request.user.is_owner:
            return redirect('owner:dashboard')
        return redirect('kitchen:kds')


class MfaSetupView(OwnerRequiredMixin, View):
    def get(self, request):
        if not request.user.mfa_enabled:
            return redirect('owner:dashboard')
        if request.user.is_verified():
            return redirect('owner:dashboard')
        
        device, created = TOTPDevice.objects.get_or_create(user=request.user, name="default")
        
        qr_url = device.config_url
        img = qrcode.make(qr_url)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        
        return render(request, 'owner/mfa_setup.html', {'qr_code': qr_b64, 'secret': device.key})

    def post(self, request):
        if not request.user.mfa_enabled:
            return redirect('owner:dashboard')
        if request.user.is_verified():
            return redirect('owner:dashboard')
            
        token = request.POST.get('token', '').strip()
        device = TOTPDevice.objects.filter(user=request.user).first()
        
        if not device:
            messages.error(request, "No device found.")
            return redirect('owner:mfa_setup')
            
        if device.verify_token(token):
            device.confirmed = True
            device.save()
            otp_login(request, device)
            return redirect('owner:dashboard')
            
        messages.error(request, "Invalid token. Try again.")
        return redirect('owner:mfa_setup')


class MfaVerifyView(OwnerRequiredMixin, View):
    def get(self, request):
        if not request.user.mfa_enabled:
            return redirect('owner:dashboard')
        if request.user.is_verified():
            return redirect('owner:dashboard')
        device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
        if not device:
            return redirect('owner:mfa_setup')
        return render(request, 'owner/mfa_verify.html')
        
    def post(self, request):
        if not request.user.mfa_enabled:
            return redirect('owner:dashboard')
        if request.user.is_verified():
            return redirect('owner:dashboard')
        token = request.POST.get('token', '').strip()
        device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
        if not device:
            return redirect('owner:mfa_setup')
            
        if device.verify_token(token):
            otp_login(request, device)
            return redirect('owner:dashboard')
            
        messages.error(request, "Invalid code.")
        return redirect('owner:mfa_verify')