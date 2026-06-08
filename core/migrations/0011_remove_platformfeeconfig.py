from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0010_remove_stafffilter_unique_stafffilter_lower_per_owner_and_more'),
    ]

    operations = [
        migrations.DeleteModel(
            name='PlatformFeeConfig',
        ),
    ]

