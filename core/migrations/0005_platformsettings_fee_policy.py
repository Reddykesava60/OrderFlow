from decimal import Decimal

from django.db import migrations, models


def seed_fee_policy_defaults(apps, schema_editor):
    PlatformSettings = apps.get_model('core', 'PlatformSettings')
    obj, _ = PlatformSettings.objects.get_or_create(
        singleton_key=1,
        defaults={
            'cash_payment_timeout_minutes': 10,
            'platform_fee_mode': 'PERCENTAGE',
            'platform_fee_percent': Decimal('3.00'),
            'platform_fee_fixed_amount': Decimal('0.00'),
        },
    )
    changed = False
    if not obj.platform_fee_mode:
        obj.platform_fee_mode = 'PERCENTAGE'
        changed = True
    if obj.platform_fee_percent is None:
        obj.platform_fee_percent = Decimal('3.00')
        changed = True
    if obj.platform_fee_fixed_amount is None:
        obj.platform_fee_fixed_amount = Decimal('0.00')
        changed = True
    if changed:
        obj.save(update_fields=['platform_fee_mode', 'platform_fee_percent', 'platform_fee_fixed_amount'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_platformsettings'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformsettings',
            name='platform_fee_fixed_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Used when fee mode is Fixed per order.', max_digits=10),
        ),
        migrations.AddField(
            model_name='platformsettings',
            name='platform_fee_mode',
            field=models.CharField(choices=[('PERCENTAGE', 'Percentage'), ('FIXED', 'Fixed per order')], default='PERCENTAGE', help_text='Choose whether platform fee is calculated as a percentage or fixed amount per order.', max_length=20),
        ),
        migrations.AddField(
            model_name='platformsettings',
            name='platform_fee_percent',
            field=models.DecimalField(decimal_places=2, default=Decimal('3.00'), help_text='Used when fee mode is Percentage.', max_digits=5),
        ),
        migrations.RunPython(seed_fee_policy_defaults, migrations.RunPython.noop),
    ]
