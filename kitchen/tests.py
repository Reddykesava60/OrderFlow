from unittest.mock import patch
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Restaurant,
    MenuItem,
    AddOn,
    ItemType,
    PlatformSettings,
    StaffFilter,
    MenuItemAddOn,
)
from ordering.models import Order
from ordering.models import OrderItem, OrderItemAddOn, WorkStatus
from ordering.checkout.services import place_cash_order


class CashCollectTimeoutApiTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Kitchen Test', slug='kitchen-test')
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            name='Dosa',
            base_price=Decimal('55.00'),
            stock=5,
        )
        self.user = get_user_model().objects.create_user(
            username='kdsstaff',
            password='pass1234',
            role='STAFF',
            restaurant=self.restaurant,
            allow_cash_collection=True,
        )
        self.client.force_login(self.user)

        settings_obj = PlatformSettings.get_solo()
        settings_obj.cash_payment_timeout_minutes = 10
        settings_obj.save(update_fields=['cash_payment_timeout_minutes'])

    def test_collect_cash_returns_timeout_for_expired_order(self):
        order = place_cash_order(
            self.restaurant,
            cart_lines=[
                {
                    'item_id': str(self.item.id),
                    'quantity': 1,
                    'dining_option': 'DINE_IN',
                    'addons': [],
                }
            ],
            customer_name='Bob',
            table_number='B2',
        )
        order.created_at = timezone.now() - timezone.timedelta(minutes=11)
        order.save(update_fields=['created_at'])

        response = self.client.post(reverse('kitchen:cash_collect', args=[order.id]))
        payload = response.json()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload.get('error'), 'PAYMENT_TIMEOUT')


class KDSPollMetaTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Poll Test', slug='poll-test')
        self.item_type = ItemType.objects.create(restaurant=self.restaurant, name='Main', sort_order=1)
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            item_type=self.item_type,
            name='Idly',
            base_price=Decimal('40.00'),
            stock=10,
        )
        self.user = get_user_model().objects.create_user(
            username='pollstaff',
            password='pass1234',
            role='STAFF',
            restaurant=self.restaurant,
            allow_cash_collection=True,
        )
        self.client.force_login(self.user)

        settings_obj = PlatformSettings.get_solo()
        settings_obj.cash_payment_timeout_minutes = 12
        settings_obj.save(update_fields=['cash_payment_timeout_minutes'])

    def test_poll_includes_cash_timeout_minutes(self):
        response = self.client.get(reverse('kitchen:poll'))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get('cash_timeout_minutes'), 12)

    def test_view_all_orders_permission_does_not_unlock_payments(self):
        viewer = get_user_model().objects.create_user(
            username='viewer',
            password='pass1234',
            role='STAFF',
            restaurant=self.restaurant,

            allow_cash_collection=False,
        )
        place_cash_order(
            self.restaurant,
            cart_lines=[
                {
                    'item_id': str(self.item.id),
                    'quantity': 1,
                    'dining_option': 'DINE_IN',
                    'addons': [],
                }
            ],
            customer_name='Alice',
            table_number='A1',
        )

        self.client.force_login(viewer)
        response = self.client.get(reverse('kitchen:poll'))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload.get('payments', [])), 0)
        self.assertFalse(payload['permissions']['can_collect'])
        self.assertTrue(payload['permissions']['can_view_all'])

    def test_kitchen_shows_all_orders_without_station_restriction(self):
        other_type = ItemType.objects.create(restaurant=self.restaurant, name='Other', sort_order=2)

        own_item = MenuItem.objects.create(
            restaurant=self.restaurant,
            item_type=self.item_type,
            name='Sambar',
            base_price=Decimal('30.00'),
            stock=10,
        )
        other_item = MenuItem.objects.create(
            restaurant=self.restaurant,
            item_type=other_type,
            name='Vada',
            base_price=Decimal('25.00'),
            stock=10,
        )

        own_order = place_cash_order(
            self.restaurant,
            cart_lines=[{
                'item_id': str(own_item.id),
                'quantity': 1,
                'dining_option': 'DINE_IN',
                'addons': [],
            }],
            customer_name='Own',
            table_number='T1',
        )
        other_order = place_cash_order(
            self.restaurant,
            cart_lines=[{
                'item_id': str(other_item.id),
                'quantity': 1,
                'dining_option': 'DINE_IN',
                'addons': [],
            }],
            customer_name='Other',
            table_number='T2',
        )
        Order.objects.filter(id__in=[own_order.id, other_order.id]).update(status=Order.Status.PENDING)

        viewer = get_user_model().objects.create_user(
            username='viewer2',
            password='pass1234',
            role='STAFF',
            restaurant=self.restaurant,

            allow_cash_collection=False,
        )

        self.client.force_login(viewer)
        response = self.client.get(reverse('kitchen:poll'))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        kitchen_order_numbers = sorted(order['order_number'] for order in payload.get('kitchen', []))
        self.assertEqual(kitchen_order_numbers, sorted([own_order.order_number, other_order.order_number]))
        self.assertEqual(len(payload.get('all_orders', [])), 2)
        self.assertTrue(payload['kitchen'][0]['menu_item_ids'])

    def test_poll_includes_owner_defined_staff_filters(self):
        owner = get_user_model().objects.create_user(
            username='owner-filter',
            password='pass1234',
            role='OWNER',
            restaurant=self.restaurant,
        )
        staff_filter = StaffFilter.objects.create(restaurant=owner.restaurant, name='Idly Filter')
        staff_filter.items.set([self.item])

        response = self.client.get(reverse('kitchen:poll'))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload.get('staff_filters', [])), 1)
        self.assertEqual(payload['staff_filters'][0]['name'], 'Idly Filter')
        self.assertEqual(payload['staff_filters'][0]['item_ids'], [str(self.item.id)])

    def test_poll_work_units_include_menu_item_id_and_category_name(self):
        addon = AddOn.objects.create(
            restaurant=self.restaurant,
            name='Extra Chutney',
            price=Decimal('5.00'),
            max_qty=5,
            stock=None,
            is_active=True,
        )
        MenuItemAddOn.objects.create(menu_item=self.item, addon=addon)

        order = place_cash_order(
            self.restaurant,
            cart_lines=[{
                'item_id': str(self.item.id),
                'quantity': 1,
                'dining_option': 'DINE_IN',
                'addons': [{'addon_id': str(addon.id), 'quantity': 1}],
            }],
            customer_name='Alice',
            table_number='A1',
        )
        # move to kitchen workflow
        Order.objects.filter(id=order.id).update(status=Order.Status.PENDING)
        order.refresh_from_db()

        # Ensure both item + add-on are pending so they appear in the item work unit
        order_item = OrderItem.objects.get(order=order)
        OrderItem.objects.filter(id=order_item.id).update(prep_status=WorkStatus.PENDING)
        OrderItemAddOn.objects.filter(order_item=order_item).update(prep_status=WorkStatus.PENDING)

        response = self.client.get(reverse('kitchen:poll'))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload.get('kitchen'))
        work_units = payload['kitchen'][0].get('work_units', [])
        self.assertTrue(work_units)

        unit_by_kind = {u.get('kind'): u for u in work_units}
        self.assertIn('item', unit_by_kind)
        self.assertNotIn('addon', unit_by_kind)

        item_unit = unit_by_kind['item']

        self.assertEqual(item_unit.get('menu_item_id'), str(self.item.id))
        self.assertEqual(item_unit.get('category_name'), self.item_type.name)

        attached = item_unit.get('attached_addons') or []
        self.assertTrue(attached)
        self.assertEqual(attached[0].get('status'), WorkStatus.PENDING)


class KDSActionPermissionTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Action Test', slug='action-test')
        self.item_type = ItemType.objects.create(restaurant=self.restaurant, name='Main', sort_order=1)
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            item_type=self.item_type,
            name='Poori',
            base_price=Decimal('60.00'),
            stock=20,
        )

    def test_start_prep_requires_mark_orders_done_permission(self):
        staff = get_user_model().objects.create_user(
            username='kitchen-no-complete',
            password='pass1234',
            role='STAFF',
            restaurant=self.restaurant,
            allow_order_completion=False,
        )

        order = place_cash_order(
            self.restaurant,
            cart_lines=[{
                'item_id': str(self.item.id),
                'quantity': 1,
                'dining_option': 'DINE_IN',
                'addons': [],
            }],
            customer_name='Prep User',
            table_number='P1',
        )
        Order.objects.filter(id=order.id).update(status=Order.Status.PENDING)
        order.refresh_from_db()
        order_item = order.items.first()

        self.client.force_login(staff)
        response = self.client.post(reverse('kitchen:start_item_prep', args=[order_item.id]))
        self.assertEqual(response.status_code, 403)


class KDSPrepToggleTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Prep Toggle Test', slug='prep-toggle')
        self.item_type = ItemType.objects.create(restaurant=self.restaurant, name='Main', sort_order=1)
        self.item = MenuItem.objects.create(
            restaurant=self.restaurant,
            item_type=self.item_type,
            name='Dosa',
            base_price=Decimal('55.00'),
            stock=5,
        )
        self.addon = AddOn.objects.create(
            restaurant=self.restaurant,
            name='Extra Chutney',
            price=Decimal('5.00'),
            max_qty=5,
            is_active=True,
        )
        MenuItemAddOn.objects.create(menu_item=self.item, addon=self.addon)
        self.user = get_user_model().objects.create_user(
            username='kdstoggle',
            password='pass1234',
            role='STAFF',
            restaurant=self.restaurant,
            allow_order_completion=True,

        )
        self.client.force_login(self.user)

    def _create_order(self):
        order = place_cash_order(
            self.restaurant,
            cart_lines=[{
                'item_id': str(self.item.id),
                'quantity': 1,
                'dining_option': 'DINE_IN',
                'addons': [{'addon_id': str(self.addon.id), 'quantity': 1}],
            }],
            customer_name='Bob',
            table_number='B1',
        )
        Order.objects.filter(id=order.id).update(status=Order.Status.PENDING)
        order.refresh_from_db()
        return order

    def test_prep_on_start_prep_goes_to_preparing(self):
        # Default is kds_prep_enabled=True
        order = self._create_order()
        response = self.client.post(reverse('kitchen:start_prep', args=[order.id]))
        self.assertEqual(response.status_code, 200)

        order_item = order.items.first()
        item_addon = order_item.addons.first()
        self.assertEqual(order_item.prep_status, WorkStatus.PREPARING)
        self.assertEqual(item_addon.prep_status, WorkStatus.PREPARING)

    def test_prep_off_start_prep_goes_to_completed(self):
        self.restaurant.config.kds_prep_enabled = False
        self.restaurant.config.save()

        order = self._create_order()
        response = self.client.post(reverse('kitchen:start_prep', args=[order.id]))
        self.assertEqual(response.status_code, 200)

        order_item = order.items.first()
        item_addon = order_item.addons.first()
        self.assertEqual(order_item.prep_status, WorkStatus.COMPLETED)
        self.assertEqual(item_addon.prep_status, WorkStatus.COMPLETED)

    @patch('kitchen.views.trigger_kds_refresh')
    def test_prep_off_start_prep_triggers_refresh(self, mock_refresh):
        self.restaurant.config.kds_prep_enabled = False
        self.restaurant.config.save()

        order = self._create_order()
        response = self.client.post(reverse('kitchen:start_prep', args=[order.id]))
        self.assertEqual(response.status_code, 200)
        mock_refresh.assert_called_once_with(self.restaurant.id)

    def test_prep_off_start_item_prep_goes_to_completed(self):
        self.restaurant.config.kds_prep_enabled = False
        self.restaurant.config.save()

        order = self._create_order()
        order_item = order.items.first()
        response = self.client.post(reverse('kitchen:start_item_prep', args=[order_item.id]))
        self.assertEqual(response.status_code, 200)

        order_item.refresh_from_db()
        item_addon = order_item.addons.first()
        self.assertEqual(order_item.prep_status, WorkStatus.COMPLETED)
        # _complete_item_group completes the item and its addons
        self.assertEqual(item_addon.prep_status, WorkStatus.COMPLETED)

    def test_prep_off_start_addon_prep_goes_to_completed(self):
        self.restaurant.config.kds_prep_enabled = False
        self.restaurant.config.save()

        order = self._create_order()
        order_item = order.items.first()
        item_addon = order_item.addons.first()
        response = self.client.post(reverse('kitchen:start_addon_prep', args=[item_addon.id]))
        self.assertEqual(response.status_code, 200)

        order_item.refresh_from_db()
        item_addon.refresh_from_db()
        # _complete_item_group completes the item and its addons
        self.assertEqual(order_item.prep_status, WorkStatus.COMPLETED)
        self.assertEqual(item_addon.prep_status, WorkStatus.COMPLETED)
