"""Enable Row Level Security on every table in the public schema.

Supabase exposes the ``public`` schema via PostgREST.  Any table without RLS
enabled (and without privileges revoked from ``anon``/``authenticated``) is
flagged as a security vulnerability by the Supabase Advisor.

This migration:
1. Loops over *every* table in ``public`` and enables RLS.
2. Revokes ``ALL`` from ``anon`` and ``authenticated`` – Django connects as the
   database owner (``postgres``), which bypasses RLS, so the application is
   unaffected.
3. Is idempotent – safe to re-run.
"""

from django.db import migrations


ENABLE_RLS_SQL = """\
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT tablename
          FROM pg_tables
         WHERE schemaname = 'public'
    LOOP
        -- Enable RLS (idempotent – no error if already enabled)
        EXECUTE format('ALTER TABLE public.%%I ENABLE ROW LEVEL SECURITY', tbl);

        -- Revoke API-facing roles; ignore if roles don't exist (e.g. local dev)
        BEGIN
            EXECUTE format('REVOKE ALL ON public.%%I FROM anon, authenticated', tbl);
        EXCEPTION WHEN undefined_object THEN
            NULL;  -- role does not exist, skip
        END;
        IF tbl = 'django_migrations' THEN
            -- Ensure the connecting role can always read/write its own migration history
            EXECUTE 'DROP POLICY IF EXISTS django_migrations_access ON public.django_migrations';
            EXECUTE format('CREATE POLICY django_migrations_access ON public.django_migrations FOR ALL TO %%I USING (true) WITH CHECK (true)', current_user);
        END IF;
    END LOOP;
END $$;
"""

DISABLE_RLS_SQL = """\
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT tablename
          FROM pg_tables
         WHERE schemaname = 'public'
    LOOP
        EXECUTE format('ALTER TABLE public.%%I DISABLE ROW LEVEL SECURITY', tbl);
    END LOOP;
END $$;
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(ENABLE_RLS_SQL)

def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(DISABLE_RLS_SQL)

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_secure_django_migrations'),
    ]

    operations = [
        migrations.RunPython(forward, reverse)
    ]
