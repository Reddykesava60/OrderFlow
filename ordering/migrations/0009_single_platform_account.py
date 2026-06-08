# Generated manually for Single Platform Account architecture
# Run `python manage.py migrate ordering 0009` to apply.

import django.db.models.deletion
import uuid
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_single_platform_account'),
        ('ordering', '0008_order_ord_rest_status_created_idx_and_more'),
    ]

    operations = [
        # 1. Add gateway_account_source to PaymentTransaction
        migrations.AddField(
            model_name='paymenttransaction',
            name='gateway_account_source',
            field=models.CharField(
                choices=[('PLATFORM', 'Platform'), ('RESTAURANT', 'Restaurant')],
                default='PLATFORM',
                help_text='Whether credentials came from PLATFORM env vars or RESTAURANT-specific config.',
                max_length=20,
            ),
        ),
        # 2. Add gateway_account_identifier to PaymentTransaction
        migrations.AddField(
            model_name='paymenttransaction',
            name='gateway_account_identifier',
            field=models.CharField(
                blank=True,
                help_text='Identifier for the gateway account used (e.g. masked key_id or account name).',
                max_length=160,
            ),
        ),
        # 3. Create RestaurantBalance model
        migrations.CreateModel(
            name='RestaurantBalance',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('gross_amount', models.DecimalField(
                    decimal_places=2, help_text='Total order amount collected via gateway.', max_digits=10)),
                ('platform_commission', models.DecimalField(
                    decimal_places=2, help_text='Platform fee deducted from gross amount.', max_digits=10)),
                ('commission_rate_snapshot', models.DecimalField(
                    decimal_places=2, help_text='Commission rate (%) at the time of this entry — immutable after creation.', max_digits=5)),
                ('net_amount', models.DecimalField(
                    decimal_places=2, help_text='Amount owed to restaurant (gross − commission).', max_digits=10)),
                ('settlement_status', models.CharField(
                    choices=[('pending', 'Pending'), ('settled', 'Settled'), ('refunded', 'Refunded')],
                    default='pending', max_length=20)),
                ('settlement_reference', models.CharField(
                    blank=True, help_text='External reference for manual settlement (bank ref, UTR, etc.).', max_length=200)),
                ('settlement_date', models.DateTimeField(blank=True, null=True)),
                ('gateway_account_source', models.CharField(
                    choices=[('PLATFORM', 'Platform'), ('RESTAURANT', 'Restaurant')],
                    default='PLATFORM', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('order', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='balance_entries', to='ordering.order')),
                ('payment_transaction', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='balance_entries', to='ordering.paymenttransaction')),
                ('restaurant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='balance_entries', to='core.restaurant')),
            ],
            options={
                'db_table': 'restaurant_balances',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(
                        fields=['restaurant', 'settlement_status', 'created_at'],
                        name='rest_bal_settle_created_idx',
                    ),
                    models.Index(
                        fields=['restaurant', 'created_at'],
                        name='rest_bal_rest_created_idx',
                    ),
                ],
            },
        ),
    ]
