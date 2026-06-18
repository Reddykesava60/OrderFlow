# core/mixins.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseForbidden
from django.shortcuts import redirect


class ActiveStaffMixin(LoginRequiredMixin):
    """
    Any authenticated, active staff or owner of this restaurant.
    Covers: KDS Kitchen tab, Preparing tab, Start Prep.
    restaurant_id is sourced exclusively from the session (SEC-04).
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_active:
            return HttpResponseForbidden("Account deactivated.")
        # Superusers (platform dev) have no restaurant — block from staff views
        if request.user.is_superuser or not request.user.restaurant:
            return HttpResponseForbidden("Not a restaurant account.")
        return super().dispatch(request, *args, **kwargs)

    def get_restaurant(self):
        """Always sourced from the authenticated session — never from URL or POST."""
        return self.request.user.restaurant


class CashCollectionMixin(ActiveStaffMixin):
    """allow_cash_collection=True OR role=OWNER."""
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if hasattr(response, 'status_code') and response.status_code in (302, 403):
            return response
        user = request.user
        if not (user.allow_cash_collection or user.is_owner):
            return HttpResponseForbidden("Cash collection permission required.")
        return response


class OrderCompletionMixin(ActiveStaffMixin):
    """allow_order_completion=True OR role=OWNER."""
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if hasattr(response, 'status_code') and response.status_code in (302, 403):
            return response
        user = request.user
        if not (user.allow_order_completion or user.is_owner):
            return HttpResponseForbidden("Order completion permission required.")
        return response


class OwnerRequiredMixin(ActiveStaffMixin):
    """role=OWNER only. Enforces MFA verification."""
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if hasattr(response, 'status_code') and response.status_code in (302, 403):
            return response
        if not self.request.user.is_owner:
            return HttpResponseForbidden("Owner access required.")
            
        from django.urls import reverse
        exempt_paths = [reverse('owner:mfa_setup'), reverse('owner:mfa_verify'), reverse('owner:logout')]
        if request.path not in exempt_paths:
            if not request.user.is_verified():
                return redirect('owner:mfa_verify')
                
        return response