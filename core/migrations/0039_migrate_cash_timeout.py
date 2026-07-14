from django.db import migrations, models

def migrate_cash_timeout_data(apps, schema_editor):
    PlatformSettings = apps.get_model('core', 'PlatformSettings')
    RestaurantConfig = apps.get_model('core', 'RestaurantConfig')

    settings = PlatformSettings.objects.first()
    default_timeout = settings.cash_payment_timeout_minutes if settings else 10

    for config in RestaurantConfig.objects.all():
        if getattr(config, 'cash_payment_timeout_minutes_override', None) is None:
            config.cash_payment_timeout_minutes_override = default_timeout
        config.save()

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0038_remove_restaurant_commission_rate'),
    ]

    operations = [
        migrations.RunPython(migrate_cash_timeout_data, reverse_code=migrations.RunPython.noop),
        migrations.RenameField(
            model_name='restaurantconfig',
            old_name='cash_payment_timeout_minutes_override',
            new_name='cash_payment_timeout_minutes',
        ),
        migrations.AlterField(
            model_name='restaurantconfig',
            name='cash_payment_timeout_minutes',
            field=models.PositiveIntegerField(default=10, help_text='Minutes before an unpaid cash order expires automatically.'),
        ),
        migrations.RemoveField(
            model_name='platformsettings',
            name='cash_payment_timeout_minutes',
        ),
    ]
