import logging
from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from core.models import Customer
from core.services import create_customer, update_customer_pin, set_customer_status

from ordering.models import LedgerEntry
from ordering.services import record_customer_payment
from core.mixins import OwnerRequiredMixin

logger = logging.getLogger(__name__)

class CustomerListView(OwnerRequiredMixin, View):
    def get(self, request):
        return render(request, 'owner/customers.html', {
            'restaurant': request.user.restaurant
        })

class CustomerListApiView(OwnerRequiredMixin, View):
    def get(self, request):
        customers = Customer.objects.filter(restaurant=request.user.restaurant).order_by('-created_at')
        data = [{
            'id': str(c.id),
            'serial_number': c.serial_number,
            'name': c.name,
            'phone': c.phone,
            'balance': float(c.balance),
            'credit_limit': float(c.credit_limit) if c.credit_limit is not None else None,
            'is_post_payment_enabled': c.is_post_payment_enabled,
            'is_blocked': c.is_blocked,
        } for c in customers]
        return JsonResponse({'customers': data})

class CustomerCreateView(OwnerRequiredMixin, View):
    def post(self, request):
        try:
            name = request.POST.get('name')
            phone = request.POST.get('phone')
            pin = request.POST.get('pin')
            credit_limit_str = request.POST.get('credit_limit')
            
            if not name or not phone or not pin:
                return JsonResponse({'error': 'Name, phone, and PIN are required.'}, status=400)
                
            credit_limit = None
            if credit_limit_str:
                credit_limit = Decimal(credit_limit_str)
                
            customer = create_customer(
                restaurant=request.user.restaurant,
                name=name,
                phone=phone,
                pin=pin,
                credit_limit=credit_limit,
                owner_user=request.user
            )
            return JsonResponse({'success': True, 'customer_id': str(customer.id)})
        except Exception as e:
            logger.exception("Error creating customer")
            return JsonResponse({'error': str(e)}, status=400)

class CustomerEditView(OwnerRequiredMixin, View):
    def post(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id, restaurant=request.user.restaurant)
        try:
            is_post_payment_enabled = request.POST.get('is_post_payment_enabled') == 'true'
            is_blocked = request.POST.get('is_blocked') == 'true'
            credit_limit_str = request.POST.get('credit_limit')
            
            credit_limit = Decimal(credit_limit_str) if credit_limit_str else None
            
            set_customer_status(
                customer,
                is_post_payment_enabled=is_post_payment_enabled,
                is_blocked=is_blocked,
                credit_limit=credit_limit,
                owner_user=request.user
            )
            return JsonResponse({'success': True})
        except Exception as e:
            logger.exception("Error editing customer")
            return JsonResponse({'error': str(e)}, status=400)

class CustomerPaymentView(OwnerRequiredMixin, View):
    def post(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id, restaurant=request.user.restaurant)
        try:
            amount_str = request.POST.get('amount')
            if not amount_str:
                return JsonResponse({'error': 'Amount is required.'}, status=400)
                
            payment_method = request.POST.get('payment_method', 'Cash')
            description = request.POST.get('description', '')
            
            amount = Decimal(amount_str)
            if amount <= 0:
                return JsonResponse({'error': 'Amount must be greater than zero.'}, status=400)
                
            record_customer_payment(customer, amount, payment_method, description, owner_user=request.user)
            return JsonResponse({'success': True, 'new_balance': float(customer.balance)})
        except Exception as e:
            logger.exception("Error recording customer payment")
            return JsonResponse({'error': str(e)}, status=400)

class CustomerResetPinView(OwnerRequiredMixin, View):
    def post(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id, restaurant=request.user.restaurant)
        try:
            new_pin = request.POST.get('new_pin')
            if not new_pin:
                return JsonResponse({'error': 'New PIN is required.'}, status=400)
                
            update_customer_pin(customer, new_pin, owner_user=request.user)
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

class CustomerLedgerView(OwnerRequiredMixin, View):
    def get(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id, restaurant=request.user.restaurant)
        entries = LedgerEntry.objects.filter(customer=customer).order_by('-created_at')[:50]
        data = [{
            'id': str(e.id),
            'entry_type': e.entry_type,
            'amount': float(e.amount),
            'balance_after': float(e.balance_after),
            'description': e.description,
            'created_at': e.created_at.isoformat()
        } for e in entries]
        return JsonResponse({'entries': data})
