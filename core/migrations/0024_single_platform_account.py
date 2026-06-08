# Generated manually for Single Platform Account architecture
# Run `python manage.py migrate core 0024` to apply.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_enable_rls_all_tables'),
    ]

    operations = [
        # 1. Per-restaurant commission override (NULL = use PlatformSettings default)
        migrations.AddField(
            model_name='restaurant',
            name='commission_rate',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Per-restaurant commission override (%). NULL = use PlatformSettings default.',
                max_digits=5,
                null=True,
            ),
        ),
        # 2. Operational status for RestaurantPaymentConfig
        migrations.AddField(
            model_name='restaurantpaymentconfig',
            name='config_status',
            field=models.CharField(
                choices=[
                    ('ACTIVE', 'Active'),
                    ('DISABLED', 'Disabled'),
                    ('MIGRATED_TO_PLATFORM', 'Migrated to Platform'),
                ],
                default='ACTIVE',
                help_text='Operational status. MIGRATED_TO_PLATFORM means this config is superseded by platform credentials.',
                max_length=25,
            ),
        ),
    ]
