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

			allow_order_completion=False,
		)
		self.client.force_login(self.owner)
		from django_otp.plugins.otp_totp.models import TOTPDevice
		device = TOTPDevice.objects.create(user=self.owner, confirmed=True)
		session = self.client.session
		session['otp_device_id'] = device.persistent_id
		session.save()

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
				'slug': 'audit-test',
			},
		)

		self.assertEqual(response.status_code, 302)
		log = OwnerAuditLog.objects.get(restaurant=self.restaurant)
		self.assertEqual(log.action, OwnerAuditLog.ActionType.UPDATE_RESTAURANT_CONFIG)
		self.assertEqual(log.details['restaurant_config_after']['reopen_message'], 'Back in 10')


class OwnerMfaTests(TestCase):
	def setUp(self):
		self.restaurant = Restaurant.objects.create(name='MFA Test', slug='mfa-test')
		self.owner = get_user_model().objects.create_user(
			username='owner_mfa',
			password='pass1234',
			role='OWNER',
			restaurant=self.restaurant,
			mfa_enabled=True,
		)

	def test_owner_views_require_mfa_verification(self):
		self.client.login(username='owner_mfa', password='pass1234')
		response = self.client.get(reverse('owner:dashboard'))
		self.assertEqual(response.status_code, 302)
		self.assertEqual(response.url, reverse('owner:mfa_verify'))

	def test_mfa_setup_view_accessible_without_verification(self):
		self.client.login(username='owner_mfa', password='pass1234')
		response = self.client.get(reverse('owner:mfa_setup'))
		self.assertEqual(response.status_code, 200)

	def test_mfa_verify_view_accessible_without_verification(self):
		self.client.login(username='owner_mfa', password='pass1234')
		from django_otp.plugins.otp_totp.models import TOTPDevice
		TOTPDevice.objects.create(user=self.owner, confirmed=True)
		response = self.client.get(reverse('owner:mfa_verify'))
		self.assertEqual(response.status_code, 200)


class KdsPrepEnabledTests(TestCase):
	"""Tests for the kds_prep_enabled toggle on the owner config page."""

	def setUp(self):
		self.restaurant = Restaurant.objects.create(name='KDS Test', slug='kds-test')
		self.owner = get_user_model().objects.create_user(
			username='owner_kds',
			password='pass1234',
			role='OWNER',
			restaurant=self.restaurant,
		)
		self.staff = get_user_model().objects.create_user(
			username='staff_kds',
			password='pass1234',
			role='STAFF',
			restaurant=self.restaurant,
		)
		# Pre-authenticate owner with MFA
		self.client.force_login(self.owner)
		from django_otp.plugins.otp_totp.models import TOTPDevice
		device = TOTPDevice.objects.create(user=self.owner, confirmed=True)
		session = self.client.session
		session['otp_device_id'] = device.persistent_id
		session.save()

	def _post_config(self, extra=None):
		"""POST to config with minimum valid data (cash_enabled on)."""
		data = {
			'cash_enabled': 'on',
			'post_payment_enabled': 'on',
			'slug': self.restaurant.slug,
		}
		if extra:
			data.update(extra)
		return self.client.post(reverse('owner:config'), data=data)

	def test_staff_cannot_toggle_kds_prep_enabled(self):
		"""Staff-role user gets 403 and config stays unchanged."""
		self.restaurant.config.kds_prep_enabled = True
		self.restaurant.config.save()

		self.client.force_login(self.staff)
		response = self.client.post(
			reverse('owner:config'),
			data={'cash_enabled': 'on', 'post_payment_enabled': 'on', 'slug': self.restaurant.slug},
		)

		self.assertEqual(response.status_code, 403)
		self.restaurant.config.refresh_from_db()
		self.assertTrue(self.restaurant.config.kds_prep_enabled)

	def test_owner_can_toggle_kds_prep_enabled_and_audit_logged(self):
		"""Owner toggles kds_prep_enabled True→False; value saved, audit recorded."""
		self.restaurant.config.kds_prep_enabled = True
		self.restaurant.config.save()

		# POST without kds_prep_enabled checkbox → should set it to False
		response = self._post_config()

		self.assertEqual(response.status_code, 302)
		self.restaurant.config.refresh_from_db()
		self.assertFalse(self.restaurant.config.kds_prep_enabled)

		# Verify audit log
		log = OwnerAuditLog.objects.filter(
			restaurant=self.restaurant,
			action=OwnerAuditLog.ActionType.UPDATE_RESTAURANT_CONFIG,
		).latest('created_at')
		self.assertTrue(log.details['restaurant_config_before']['kds_prep_enabled'])
		self.assertFalse(log.details['restaurant_config_after']['kds_prep_enabled'])
