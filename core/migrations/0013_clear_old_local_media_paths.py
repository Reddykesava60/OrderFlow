# core/migrations/0013_clear_old_local_media_paths.py
"""
Data migration: Clear any old local file paths (e.g. 'menu_images/foo.jpg')
from image fields that were converted to TextField in 0012.

After this migration, only valid Supabase public URLs (starting with 'http')
or empty strings will remain in image/logo/photo fields.
"""
from django.db import migrations


def clear_stale_local_paths(apps, schema_editor):
    """Blank out image fields that contain local file paths instead of URLs."""
    MenuItem = apps.get_model('core', 'MenuItem')
    AddOn = apps.get_model('core', 'AddOn')
    Restaurant = apps.get_model('core', 'Restaurant')
    User = apps.get_model('core', 'User')

    for Model, field in [
        (MenuItem, 'image'),
        (AddOn, 'image'),
        (Restaurant, 'logo'),
        (User, 'photo'),
    ]:
        # Any non-empty value that doesn't start with http is a stale local path.
        updated = (
            Model.objects
            .exclude(**{field: ''})
            .exclude(**{f'{field}__startswith': 'http'})
            .update(**{field: ''})
        )
        if updated:
            print(f"  Cleared {updated} stale local path(s) from {Model.__name__}.{field}")


def noop(apps, schema_editor):
    pass  # No reverse needed — old local paths are irrecoverable anyway.


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0012_media_fields_to_supabase_urls'),
    ]

    operations = [
        migrations.RunPython(clear_stale_local_paths, noop),
    ]
