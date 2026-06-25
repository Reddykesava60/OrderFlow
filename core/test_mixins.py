import json
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.views import View

from core.models import User, Restaurant, OwnerAuditLog
from core.mixins import CashCollectionMixin, OrderCompletionMixin, OwnerRequiredMixin

# Dummy views that perform a "side effect"
class DummyCashView(CashCollectionMixin, View):
    def post(self, request, *args, **kwargs):
        # The side effect
        request.user.restaurant.name = "Cash Modified"
        request.user.restaurant.save()
        return HttpResponse("OK")

class DummyOrderView(OrderCompletionMixin, View):
    def post(self, request, *args, **kwargs):
        # The side effect
        request.user.restaurant.name = "Order Modified"
        request.user.restaurant.save()
        return HttpResponse("OK")

class DummyOwnerView(OwnerRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        # The side effect
        OwnerAuditLog.objects.create(
            restaurant=request.user.restaurant,
            user=request.user,
            action=OwnerAuditLog.ActionType.UPDATE_RESTAURANT_CONFIG
        )
        return HttpResponse("OK")


class MixinSecurityTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.restaurant = Restaurant.objects.create(name="Original Name")
        
        # Staff user without permissions
        self.staff_user = User.objects.create(
            username="staff1",
            role=User.Role.STAFF,
            restaurant=self.restaurant,
            allow_cash_collection=False,
            allow_order_completion=False
        )
        
        # Staff user with permissions
        self.staff_with_perms = User.objects.create(
            username="staff_perms",
            role=User.Role.STAFF,
            restaurant=self.restaurant,
            allow_cash_collection=True,
            allow_order_completion=True
        )

        # Owner user
        self.owner_user = User.objects.create(
            username="owner1",
            role=User.Role.OWNER,
            restaurant=self.restaurant
        )

    def test_cash_collection_mixin_blocks_unauthorized_side_effects(self):
        request = self.factory.post('/dummy')
        request.user = self.staff_user
        
        response = DummyCashView.as_view()(request)
        
        # Must return 403
        self.assertEqual(response.status_code, 403)
        
        # Side effect MUST NOT occur
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.name, "Original Name")

    def test_cash_collection_mixin_allows_authorized(self):
        request = self.factory.post('/dummy')
        request.user = self.staff_with_perms
        response = DummyCashView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.name, "Cash Modified")

    def test_order_completion_mixin_blocks_unauthorized_side_effects(self):
        request = self.factory.post('/dummy')
        request.user = self.staff_user
        
        response = DummyOrderView.as_view()(request)
        
        # Must return 403
        self.assertEqual(response.status_code, 403)
        
        # Side effect MUST NOT occur
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.name, "Original Name")

    def test_order_completion_mixin_allows_authorized(self):
        request = self.factory.post('/dummy')
        request.user = self.staff_with_perms
        response = DummyOrderView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.name, "Order Modified")

    def test_owner_required_mixin_blocks_unauthorized_side_effects(self):
        request = self.factory.post('/dummy')
        request.user = self.staff_with_perms  # even with perms, not an owner
        
        response = DummyOwnerView.as_view()(request)
        
        # Must return 403
        self.assertEqual(response.status_code, 403)
        
        # Side effect MUST NOT occur
        self.assertEqual(OwnerAuditLog.objects.count(), 0)

    def test_owner_required_mixin_allows_owner(self):
        request = self.factory.post('/dummy')
        request.user = self.owner_user
        request.user.is_verified = lambda: True
        response = DummyOwnerView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(OwnerAuditLog.objects.count(), 1)

    def test_owner_required_mixin_blocks_unverified_mfa(self):
        request = self.factory.post('/dummy')
        request.user = self.owner_user
        request.user.is_verified = lambda: False  # MFA not verified
        response = DummyOwnerView.as_view()(request)
        
        # Must redirect to MFA verify
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/owner/mfa/verify/')
        
        # Side effect MUST NOT occur
        self.assertEqual(OwnerAuditLog.objects.count(), 0)
