from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import OwnerAuditLog, Restaurant


class OwnerAuditLogTests(TestCase):
	def setUp(self):
		self.restaurant = Restaurant.objects.create(name='Audit Test', slug='audit-test')
		self.owner = get_user_model().objects.create_user(
			username='owner',
			password='pass1234',
			role='OWNER',
			restaurant=self.restaurant,
		)
		self.staff = get_user_model().objects.create_user(
			username='staff1',
			password='pass1234',
			role='STAFF',
			restaurant=self.restaurant,
			allow_cash_collection=False,
			allow_view_all_orders=False,
			allow_order_completion=False,
		)
		self.client.force_login(self.owner)

	def test_staff_permission_toggle_writes_audit_log(self):
		response = self.client.post(
			reverse('owner:staff_toggle_permission', args=[self.staff.id]),
			data={'permission': 'allow_cash_collection'},
		)

		self.assertEqual(response.status_code, 200)
		log = OwnerAuditLog.objects.get(restaurant=self.restaurant)
		self.assertEqual(log.action, OwnerAuditLog.ActionType.TOGGLE_STAFF_PERMISSION)
		self.assertEqual(log.details['permission'], 'allow_cash_collection')
		self.assertFalse(log.details['before'])
		self.assertTrue(log.details['after'])

	def test_config_update_writes_audit_log_without_secret_values(self):
		response = self.client.post(
			reverse('owner:config'),
			data={
				'is_open': 'on',
				'reopen_message': 'Back in 10',
				'cash_enabled': 'on',
				'upi_enabled': 'on',
				'account_name': 'DineFlow Live',
				'razorpay_key_id': 'rzp_live_1234567890',
				'razorpay_key_secret': 'secret-value',
				'razorpay_webhook_secret': 'webhook-secret',
				'razorpay_is_active': 'on',
				'slug': 'audit-test',
			},
		)

		self.assertEqual(response.status_code, 302)
		log = OwnerAuditLog.objects.get(restaurant=self.restaurant)
		self.assertEqual(log.action, OwnerAuditLog.ActionType.UPDATE_RESTAURANT_CONFIG)
		self.assertEqual(log.details['restaurant_config_after']['reopen_message'], 'Back in 10')
		self.assertEqual(log.details['payment_config_after']['account_name'], 'DineFlow Live')
		self.assertTrue(log.details['payment_config_after']['razorpay_key_secret_present'])
		self.assertTrue(log.details['payment_config_after']['razorpay_webhook_secret_present'])
