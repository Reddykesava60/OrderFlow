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


def _parse_optional_stock(raw_value):
    raw_value = (raw_value or '').strip()
    if raw_value == '':
        return None
    return int(raw_value)

def _apply_owner_item_stock_settings(item, data):
    stock_value = _parse_optional_stock(data.get('stock'))
    item.stock = stock_value
    requested_available = 'is_available' in data
    if stock_value == 0:
        item.is_available = False
        item.auto_hidden_due_to_stock = True
    else:
        item.is_available = requested_available
        item.auto_hidden_due_to_stock = False

def _store_menu_item_image(restaurant, item, uploaded_file):
    image_url = upload_public_image(bucket='menu-images', path=f'{restaurant.id}/{item.id}.webp', uploaded_file=uploaded_file)
    item.image = image_url
    item.save(update_fields=['image'])
    return image_url

def _store_addon_image(restaurant, addon, uploaded_file):
    image_url = upload_public_image(bucket='menu-images', path=f'{restaurant.id}/addons/{addon.id}.webp', uploaded_file=uploaded_file)
    addon.image = image_url
    addon.save(update_fields=['image'])
    return image_url

class MenuView(OwnerRequiredMixin, View):
    """List all menu items with availability toggle."""

    def get(self, request):
        restaurant = self.get_restaurant()
        has_active_addon = Exists(MenuItemAddOn.objects.filter(menu_item=OuterRef('pk'), addon__is_active=True))
        items = MenuItem.objects.filter(restaurant=restaurant).select_related('item_type').annotate(has_addons=has_active_addon).order_by('item_type__sort_order', 'sort_order', 'name')
        item_types = ItemType.objects.filter(restaurant=restaurant).order_by('sort_order')
        addons = AddOn.objects.filter(restaurant=restaurant).select_related().order_by('name')
        return render(request, 'owner/menu.html', {'restaurant': restaurant, 'items': items, 'item_types': item_types, 'addons': addons})

class MenuItemCreateView(OwnerRequiredMixin, View):

    def get(self, request):
        restaurant = self.get_restaurant()
        return render(request, 'owner/menu_item_form.html', {'restaurant': restaurant, 'item_types': ItemType.objects.filter(restaurant=restaurant), 'all_addons': AddOn.objects.filter(restaurant=restaurant, is_active=True), 'item': None})

    def post(self, request):
        restaurant = self.get_restaurant()
        data = request.POST
        item = MenuItem(restaurant=restaurant, item_type=ItemType.objects.filter(id=data.get('item_type'), restaurant=restaurant).first() if data.get('item_type') else None, name=data.get('name', '').strip(), description=data.get('description', '').strip(), base_price=data.get('base_price', '0'), parcel_surcharge=data.get('parcel_surcharge', '0') or '0', is_veg='is_veg' in data, spice_configurable='spice_configurable' in data, sort_order=int(data.get('sort_order') or 0))
        _apply_owner_item_stock_settings(item, data)
        try:
            item.full_clean()
            item.save()
            if request.FILES.get('image'):
                try:
                    _store_menu_item_image(restaurant, item, request.FILES['image'])
                except Exception as upload_err:
                    logger.exception('Menu image upload failed for item %s', item.id)
                    messages.warning(request, f'Item created but image upload failed: {upload_err}')
            for addon_id in data.getlist('addons'):
                addon = AddOn.objects.filter(id=addon_id, restaurant=restaurant).first()
                if addon:
                    MenuItemAddOn.objects.get_or_create(menu_item=item, addon=addon)
            messages.success(request, f"'{item.name}' created.")
            return redirect('owner:menu')
        except Exception as e:
            messages.error(request, str(e))
            return render(request, 'owner/menu_item_form.html', {'restaurant': restaurant, 'item_types': ItemType.objects.filter(restaurant=restaurant), 'all_addons': AddOn.objects.filter(restaurant=restaurant, is_active=True), 'item': None, 'data': data})

class MenuItemEditView(OwnerRequiredMixin, View):

    def get(self, request, item_id):
        restaurant = self.get_restaurant()
        item = get_object_or_404(MenuItem, id=item_id, restaurant=restaurant)
        linked_addon_ids = set(MenuItemAddOn.objects.filter(menu_item=item).values_list('addon_id', flat=True))
        return render(request, 'owner/menu_item_form.html', {'restaurant': restaurant, 'item_types': ItemType.objects.filter(restaurant=restaurant), 'all_addons': AddOn.objects.filter(restaurant=restaurant, is_active=True), 'item': item, 'linked_addon_ids': linked_addon_ids})

    def post(self, request, item_id):
        restaurant = self.get_restaurant()
        item = get_object_or_404(MenuItem, id=item_id, restaurant=restaurant)
        data = request.POST
        item.name = data.get('name', '').strip()
        item.description = data.get('description', '').strip()
        item.base_price = data.get('base_price', '0')
        item.parcel_surcharge = data.get('parcel_surcharge', '0') or '0'
        item.is_veg = 'is_veg' in data
        item.spice_configurable = 'spice_configurable' in data
        item.sort_order = int(data.get('sort_order') or 0)
        item.item_type = ItemType.objects.filter(id=data.get('item_type'), restaurant=restaurant).first() if data.get('item_type') else None
        _apply_owner_item_stock_settings(item, data)
        try:
            item.full_clean()
            item.save()
            if request.FILES.get('image'):
                try:
                    _store_menu_item_image(restaurant, item, request.FILES['image'])
                except Exception as upload_err:
                    logger.exception('Menu image upload failed for item %s', item.id)
                    messages.warning(request, f'Image upload failed: {upload_err}')
            selected = set(data.getlist('addons'))
            existing = set((str(aid) for aid in MenuItemAddOn.objects.filter(menu_item=item).values_list('addon_id', flat=True)))
            for addon_id in selected - existing:
                addon = AddOn.objects.filter(id=addon_id, restaurant=restaurant).first()
                if addon:
                    MenuItemAddOn.objects.get_or_create(menu_item=item, addon=addon)
            MenuItemAddOn.objects.filter(menu_item=item, addon_id__in=existing - selected).delete()
            messages.success(request, f"'{item.name}' updated.")
            return redirect('owner:menu')
        except Exception as e:
            messages.error(request, str(e))
            return redirect('owner:menu_edit', item_id=item_id)

class MenuItemDeleteView(OwnerRequiredMixin, View):

    def post(self, request, item_id):
        restaurant = self.get_restaurant()
        item = get_object_or_404(MenuItem, id=item_id, restaurant=restaurant)
        active = OrderItem.objects.filter(menu_item=item, order__status__in=[Order.Status.PENDING, Order.Status.PREP_STARTED]).exists()
        if active:
            messages.error(request, f"Cannot delete '{item.name}' — it has active orders.")
            return redirect('owner:menu')
        name = item.name
        item.delete()
        messages.success(request, f"'{name}' deleted.")
        return redirect('owner:menu')

class ToggleAvailabilityView(OwnerRequiredMixin, View):
    """POST /owner/menu/toggle/{item_id}/ — Alpine.js inline toggle."""

    def post(self, request, item_id):
        restaurant = self.get_restaurant()
        item = get_object_or_404(MenuItem, id=item_id, restaurant=restaurant)
        if not item.is_available and item.stock == 0:
            payload = {'is_available': False, 'has_addons': MenuItemAddOn.objects.filter(menu_item=item, addon__is_active=True).exists(), 'message': 'Cannot enable an item while stock is 0.'}
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse(payload, status=409)
            messages.error(request, payload['message'])
            return redirect('owner:menu')
        item.is_available = not item.is_available
        item.auto_hidden_due_to_stock = False
        item.save(update_fields=['is_available', 'auto_hidden_due_to_stock'])
        has_addons = MenuItemAddOn.objects.filter(menu_item=item, addon__is_active=True).exists()
        payload = {'is_available': item.is_available, 'has_addons': has_addons}
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse(payload)
        messages.success(request, f"'{item.name}' is now {('available' if item.is_available else 'hidden from customers')}.")
        return redirect('owner:menu')

class AddOnCreateView(OwnerRequiredMixin, View):

    def post(self, request):
        restaurant = self.get_restaurant()
        data = request.POST
        try:
            addon = AddOn(restaurant=restaurant, name=data.get('name', '').strip(), price=data.get('price', '0'), max_qty=int(data.get('max_qty') or 5), stock=_parse_optional_stock(data.get('stock')), is_active=True)
            addon.full_clean()
            addon.save()
            if request.FILES.get('image'):
                try:
                    _store_addon_image(restaurant, addon, request.FILES['image'])
                except Exception as upload_err:
                    logger.exception('Add-on image upload failed for add-on %s', addon.id)
                    messages.warning(request, f'Add-on created but image upload failed: {upload_err}')
            messages.success(request, 'Add-on created.')
        except Exception as e:
            messages.error(request, str(e))
        return redirect('owner:menu')

class AddOnEditView(OwnerRequiredMixin, View):

    def get(self, request, addon_id):
        restaurant = self.get_restaurant()
        addon = get_object_or_404(AddOn, id=addon_id, restaurant=restaurant)
        menu_items = MenuItem.objects.filter(restaurant=restaurant).order_by('item_type__sort_order', 'sort_order', 'name')
        linked_item_ids = list(MenuItemAddOn.objects.filter(addon=addon).values_list('menu_item_id', flat=True))
        return render(request, 'owner/addon_form.html', {
            'restaurant': restaurant,
            'addon': addon,
            'menu_items': menu_items,
            'linked_item_ids': linked_item_ids,
        })

    def post(self, request, addon_id):
        restaurant = self.get_restaurant()
        addon = get_object_or_404(AddOn, id=addon_id, restaurant=restaurant)
        data = request.POST
        addon.name = data.get('name', '').strip()
        addon.price = data.get('price', '0')
        addon.max_qty = int(data.get('max_qty') or 5)
        addon.stock = _parse_optional_stock(data.get('stock'))
        try:
            addon.full_clean()
            addon.save()
            if request.FILES.get('image'):
                try:
                    _store_addon_image(restaurant, addon, request.FILES['image'])
                except Exception as upload_err:
                    logger.exception('Add-on image upload failed for add-on %s', addon.id)
                    messages.warning(request, f'Image upload failed: {upload_err}')
                    
            raw_item_ids = request.POST.getlist('item_ids')
            selected_item_ids = list(MenuItem.objects.filter(restaurant=restaurant, id__in=raw_item_ids).values_list('id', flat=True))
            MenuItemAddOn.objects.filter(addon=addon).delete()
            MenuItemAddOn.objects.bulk_create([
                MenuItemAddOn(menu_item_id=item_id, addon=addon)
                for item_id in selected_item_ids
            ])
            
            messages.success(request, f"'{addon.name}' updated.")
            return redirect('owner:menu')
        except Exception as e:
            messages.error(request, str(e))
            return render(request, 'owner/addon_form.html', {'restaurant': restaurant, 'addon': addon})

class AddOnToggleView(OwnerRequiredMixin, View):

    def post(self, request, addon_id):
        restaurant = self.get_restaurant()
        addon = get_object_or_404(AddOn, id=addon_id, restaurant=restaurant)
        addon.is_active = not addon.is_active
        addon.save(update_fields=['is_active'])
        messages.success(request, f"'{addon.name}' {('activated' if addon.is_active else 'deactivated')}.")
        return redirect('owner:menu')

class ItemTypeCreateView(OwnerRequiredMixin, View):

    def post(self, request):
        restaurant = self.get_restaurant()
        name = request.POST.get('name', '').strip()
        if name:
            ItemType.objects.get_or_create(restaurant=restaurant, name=name, defaults={'sort_order': 0})
            messages.success(request, f"Category '{name}' created.")
        return redirect('owner:menu')

class ItemTypeEditView(OwnerRequiredMixin, View):

    def get(self, request, category_id):
        restaurant = self.get_restaurant()
        category = get_object_or_404(ItemType, id=category_id, restaurant=restaurant)
        menu_items = MenuItem.objects.filter(restaurant=restaurant).order_by('sort_order', 'name')
        linked_item_ids = list(category.items.values_list('id', flat=True))
        return render(request, 'owner/category_form.html', {
            'restaurant': restaurant,
            'category': category,
            'menu_items': menu_items,
            'linked_item_ids': linked_item_ids,
        })

    def post(self, request, category_id):
        restaurant = self.get_restaurant()
        category = get_object_or_404(ItemType, id=category_id, restaurant=restaurant)
        
        name = request.POST.get('name', '').strip()
        if name:
            category.name = name
            category.save()
            
        raw_item_ids = request.POST.getlist('item_ids')
        selected_item_ids = list(MenuItem.objects.filter(restaurant=restaurant, id__in=raw_item_ids).values_list('id', flat=True))
        
        with transaction.atomic():
            # Unlink items that are currently in this category but were NOT selected
            MenuItem.objects.filter(restaurant=restaurant, item_type=category).exclude(id__in=selected_item_ids).update(item_type=None)
            
            # Link items that ARE selected to this category
            if selected_item_ids:
                MenuItem.objects.filter(restaurant=restaurant, id__in=selected_item_ids).update(item_type=category)
                
        messages.success(request, f"Category '{category.name}' updated.")
        return redirect('owner:menu')