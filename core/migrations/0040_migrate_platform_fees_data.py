from django.db import migrations

def migrate_platform_fees_data(apps, schema_editor):
    PlatformSettings = apps.get_model('core', 'PlatformSettings')
    Restaurant = apps.get_model('core', 'Restaurant')

    settings = PlatformSettings.objects.first()
    if not settings:
        return
    
    restaurants_to_update = []
    for restaurant in Restaurant.objects.all():
        updated = False
        if not restaurant.custom_fee_mode:
            restaurant.custom_fee_mode = settings.platform_fee_mode
            updated = True
        if restaurant.custom_fee_percent is None:
            restaurant.custom_fee_percent = settings.platform_fee_percent
            updated = True
        if restaurant.custom_fee_fixed_amount is None:
            restaurant.custom_fee_fixed_amount = settings.platform_fee_fixed_amount
            updated = True
            
        if updated:
            restaurants_to_update.append(restaurant)

    if restaurants_to_update:
        Restaurant.objects.bulk_update(restaurants_to_update, ['custom_fee_mode', 'custom_fee_percent', 'custom_fee_fixed_amount'])

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0039_migrate_cash_timeout'),
    ]

    operations = [
        migrations.RunPython(migrate_platform_fees_data, reverse_code=migrations.RunPython.noop),
    ]
