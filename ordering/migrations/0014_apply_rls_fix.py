# Generated manually to apply RLS

from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('ordering', '0013_enable_rls_on_financial_tables'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE restaurant_balances ENABLE ROW LEVEL SECURITY;",
                "ALTER TABLE ordering_settlement ENABLE ROW LEVEL SECURITY;",
                "ALTER TABLE restaurant_ledger ENABLE ROW LEVEL SECURITY;",
            ],
            reverse_sql=[
                "ALTER TABLE restaurant_balances DISABLE ROW LEVEL SECURITY;",
                "ALTER TABLE ordering_settlement DISABLE ROW LEVEL SECURITY;",
                "ALTER TABLE restaurant_ledger DISABLE ROW LEVEL SECURITY;",
            ]
        ),
    ]
