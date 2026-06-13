import os
import django
import json

with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.prod')
django.setup()

from django.db import connection

print("\n--- webhook_logs ---")
try:
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT id, created_at, processed_at, signature_valid, failed_reason, raw_payload 
            FROM webhook_logs 
            WHERE raw_payload LIKE '%order_T15w3vZ6Ets9yW%'
        """)
        rows = cur.fetchall()
        for row in rows:
            print(f"ID: {row[0]}")
            print(f"Created At: {row[1]}")
            print(f"Processed At: {row[2]}")
            print(f"Signature Valid: {row[3]}")
            print(f"Failed Reason: {row[4]}")
            payload = json.loads(row[5]) if row[5] else {}
            print(f"Event Type: {payload.get('event')}")
            print("-" * 20)
        if not rows:
            print("No rows found.")
except Exception as e:
    print(f"Query failed: {e}")

print("\n--- Payment Events (kitchen_paymentevent) ---")
try:
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT id, event_type, created_at, metadata
            FROM kitchen_paymentevent
            WHERE metadata LIKE '%order_T15w3vZ6Ets9yW%'
        """)
        rows = cur.fetchall()
        for row in rows:
            print(f"ID: {row[0]}, Type: {row[1]}, Created: {row[2]}")
        if not rows:
            print("No rows found.")
except Exception as e:
    print(f"Query failed: {e}")
