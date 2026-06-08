from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0011_remove_platformfeeconfig'),
    ]

    operations = [
        migrations.AlterField(
            model_name='restaurant',
            name='logo',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='photo',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='menuitem',
            name='image',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='addon',
            name='image',
            field=models.TextField(blank=True),
        ),
    ]

