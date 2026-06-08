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
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);

        -- Revoke API-facing roles; ignore if roles don't exist (e.g. local dev)
        BEGIN
            EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', tbl);
        EXCEPTION WHEN undefined_object THEN
            NULL;  -- role does not exist, skip
        END;
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
        EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', tbl);
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_secure_django_migrations'),
    ]

    operations = [
        migrations.RunSQL(
            sql=ENABLE_RLS_SQL,
            reverse_sql=DISABLE_RLS_SQL,
        ),
    ]
