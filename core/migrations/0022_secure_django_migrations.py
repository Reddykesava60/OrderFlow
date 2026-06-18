from django.db import migrations

def forward(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("""
            DO $$
            BEGIN
                -- Fix A: Disable public access to the migrations table
                REVOKE ALL ON public.django_migrations FROM anon, authenticated;
            EXCEPTION WHEN OTHERS THEN
                -- Ignore error if anon/authenticated roles do not exist
            END $$;

            -- Fix B: Enable RLS
            ALTER TABLE public.django_migrations ENABLE ROW LEVEL SECURITY;
        """)

def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("""
            ALTER TABLE public.django_migrations DISABLE ROW LEVEL SECURITY;
            DO $$
            BEGIN
                GRANT ALL ON public.django_migrations TO anon, authenticated;
            EXCEPTION WHEN OTHERS THEN
                -- Ignore error
            END $$;
        """)

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_alter_restaurantpaymentconfig_razorpay_key_secret_and_more'),
    ]

    operations = [
        migrations.RunPython(forward, reverse)
    ]
