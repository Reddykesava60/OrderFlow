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
    OwnerAuditLog, PlatformFeeRecord, Restaurant, StaffFilter, User,
)
from core.ratelimit import rate_limit
from core.storage import get_supabase_storage_config, upload_bytes_public, upload_public_image
from core.timeutils import local_day_bounds
from kitchen.models import PaymentEvent
from ordering.models import Order, OrderItem, OrderItemAddOn
from ordering.orders.services import expire_overdue_unpaid_cash_orders

logger = logging.getLogger(__name__)


def _write_owner_audit(*, restaurant, user, action, customer=None, details=None):
    OwnerAuditLog.objects.create(restaurant=restaurant, user=user, customer=customer, action=action, details=details or {})

class StaffFilterView(OwnerRequiredMixin, View):

    def get(self, request):
        restaurant = self.get_restaurant()
        filters = StaffFilter.objects.filter(restaurant=restaurant).prefetch_related('items').order_by('name')
        menu_items = MenuItem.objects.filter(restaurant=restaurant).order_by('name')
        return render(request, 'owner/staff_filters.html', {'restaurant': restaurant, 'filters': filters, 'menu_items': menu_items})

    def post(self, request):
        restaurant = self.get_restaurant()
        name = request.POST.get('name', '').strip()
        raw_item_ids = request.POST.getlist('item_ids') or request.POST.getlist('items')
        selected_item_ids = list(MenuItem.objects.filter(restaurant=restaurant, id__in=raw_item_ids).values_list('id', flat=True))
        if not name:
            messages.error(request, 'Filter name is required.')
            return redirect('owner:staff_filters')
        staff_filter = StaffFilter(restaurant=restaurant, name=name)
        try:
            staff_filter.full_clean()
            staff_filter.save()
            staff_filter.items.set(selected_item_ids)
            messages.success(request, f"Filter '{staff_filter.name}' created.")
        except Exception as e:
            messages.error(request, str(e))
        return redirect('owner:staff_filters')

class StaffFilterEditView(OwnerRequiredMixin, View):

    def post(self, request, filter_id):
        restaurant = self.get_restaurant()
        staff_filter = get_object_or_404(StaffFilter, id=filter_id, restaurant=restaurant)
        name = request.POST.get('name', '').strip()
        raw_item_ids = request.POST.getlist('item_ids') or request.POST.getlist('items')
        selected_item_ids = list(MenuItem.objects.filter(restaurant=restaurant, id__in=raw_item_ids).values_list('id', flat=True))
        if not name:
            messages.error(request, 'Filter name is required.')
            return redirect('owner:staff_filters')
        staff_filter.name = name
        try:
            staff_filter.full_clean()
            staff_filter.save()
            staff_filter.items.set(selected_item_ids)
            messages.success(request, f"Filter '{staff_filter.name}' updated.")
        except Exception as e:
            messages.error(request, str(e))
        return redirect('owner:staff_filters')

class StaffFilterDeleteView(OwnerRequiredMixin, View):

    def post(self, request, filter_id):
        restaurant = self.get_restaurant()
        staff_filter = get_object_or_404(StaffFilter, id=filter_id, restaurant=restaurant)
        filter_name = staff_filter.name
        staff_filter.delete()
        messages.success(request, f"Filter '{filter_name}' deleted.")
        return redirect('owner:staff_filters')

class StaffView(OwnerRequiredMixin, View):

    def get(self, request):
        restaurant = self.get_restaurant()
        staff = User.objects.filter(restaurant=restaurant, role=User.Role.STAFF).order_by('role', 'username')
        return render(request, 'owner/staff.html', {'restaurant': restaurant, 'staff': staff, 'staff_count': staff.count()})

class StaffCreateView(OwnerRequiredMixin, View):

    def post(self, request):
        restaurant = self.get_restaurant()
        data = request.POST
        username = data.get('username', '').strip().lower()
        if not username:
            messages.error(request, 'Username is required.')
            return redirect('owner:staff')
        if User.objects.filter(username__iexact=username, restaurant=restaurant).exists():
            messages.error(request, f"Username '{username}' already exists in this restaurant.")
            return redirect('owner:staff')
        temp_password = data.get('password', '').strip() or _gen_temp_password()
        with transaction.atomic():
            user = User.objects.create_user(username=username, password=temp_password, restaurant=restaurant, role=User.Role.STAFF, allow_cash_collection='allow_cash_collection' in data, allow_order_completion='allow_order_completion' in data, must_change_password=True, is_active=True)
            _write_owner_audit(restaurant=restaurant, user=request.user, action=OwnerAuditLog.ActionType.CREATE_STAFF, details={'username': username, 'permissions': {'allow_cash_collection': user.allow_cash_collection, 'allow_order_completion': user.allow_order_completion}})
        request.session[f'temp_pw_{user.id}'] = temp_password
        messages.success(request, f"Staff account '{username}' created.")
        return redirect('owner:staff_created', user_id=user.id)

class StaffDeleteView(OwnerRequiredMixin, View):

    def post(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant, role=User.Role.STAFF)
        username = user.username
        _write_owner_audit(restaurant=restaurant, user=request.user, action=OwnerAuditLog.ActionType.DELETE_STAFF, details={'username': username, 'permissions': {'allow_cash_collection': user.allow_cash_collection, 'allow_order_completion': user.allow_order_completion}})
        user.delete()
        from kitchen.services import broadcast_user_disconnect
        broadcast_user_disconnect(user_id)
        messages.success(request, f"'{username}' removed.")
        return redirect('owner:staff')

class StaffCreatedView(OwnerRequiredMixin, View):
    """Show temp password exactly once then clear it from session."""

    def get(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant)
        temp_pw = request.session.pop(f'temp_pw_{user.id}', None)
        if not temp_pw:
            return redirect('owner:staff')
        return render(request, 'owner/staff_created.html', {'restaurant': restaurant, 'new_user': user, 'temp_pw': temp_pw})

class StaffEditView(OwnerRequiredMixin, View):

    def get(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant, role=User.Role.STAFF)
        return render(request, 'owner/staff_edit.html', {'restaurant': restaurant, 'staff_user': user})

    def post(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant, role=User.Role.STAFF)
        data = request.POST
        before = {'allow_cash_collection': user.allow_cash_collection, 'allow_order_completion': user.allow_order_completion, 'is_active': user.is_active}
        user.allow_cash_collection = 'allow_cash_collection' in data
        user.allow_order_completion = 'allow_order_completion' in data
        user.is_active = 'is_active' in data
        user.save(update_fields=['allow_cash_collection', 'allow_order_completion', 'is_active'])
        _write_owner_audit(restaurant=restaurant, user=request.user, action=OwnerAuditLog.ActionType.EDIT_STAFF, details={'username': user.username, 'before': before, 'after': {'allow_cash_collection': user.allow_cash_collection, 'allow_order_completion': user.allow_order_completion, 'is_active': user.is_active}})
        from kitchen.services import broadcast_user_disconnect
        broadcast_user_disconnect(user.id)
        messages.success(request, f"'{user.username}' updated.")
        return redirect('owner:staff')

@method_decorator(rate_limit('staff_reset_pw', limit=5, window=900), name='dispatch')
class StaffResetPasswordView(OwnerRequiredMixin, View):

    def post(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant, role=User.Role.STAFF)
        temp_password = _gen_temp_password()
        user.set_password(temp_password)
        user.must_change_password = True
        user.save()
        _write_owner_audit(restaurant=restaurant, user=request.user, action=OwnerAuditLog.ActionType.RESET_STAFF_PASSWORD, details={'username': user.username})
        request.session[f'temp_pw_{user.id}'] = temp_password
        from kitchen.services import broadcast_user_disconnect
        broadcast_user_disconnect(user.id)
        messages.success(request, f"Password reset for '{user.username}'.")
        return redirect('owner:staff_created', user_id=user.id)

class StaffPermissionToggleView(OwnerRequiredMixin, View):
    """POST /owner/staff/<user_id>/toggle-permission/ — AJAX toggle for permissions."""

    def post(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant, role=User.Role.STAFF)
        permission = request.POST.get('permission')
        valid_permissions = ['allow_cash_collection', 'allow_order_completion', 'is_active']
        if permission not in valid_permissions:
            return JsonResponse({'error': 'Invalid permission'}, status=400)
        current_val = getattr(user, permission)
        setattr(user, permission, not current_val)
        user.save(update_fields=[permission])
        _write_owner_audit(restaurant=restaurant, user=request.user, action=OwnerAuditLog.ActionType.TOGGLE_STAFF_PERMISSION, details={'username': user.username, 'permission': permission, 'before': current_val, 'after': getattr(user, permission)})
        from kitchen.services import broadcast_user_disconnect
        broadcast_user_disconnect(user.id)
        return JsonResponse({'status': 'success', 'permission': permission, 'value': getattr(user, permission)})