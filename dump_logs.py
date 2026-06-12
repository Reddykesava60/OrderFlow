import sqlite3
import json

conn = sqlite3.connect('db.sqlite3')
cur = conn.cursor()

cur.execute("SELECT payment_transaction_id, failed_reason, raw_payload FROM payments_webhook_log WHERE processed_at IS NULL")
rows = cur.fetchall()

if not rows:
    print("No failed webhook logs found!")
else:
    for row in rows:
        txn_id, reason, raw = row
        print(f"Transaction ID: {txn_id}")
        print(f"Reason: {reason}")
        print(f"Raw: {raw[:500]}")
        
        # Check transaction amount
        if txn_id:
            cur.execute("SELECT amount FROM payments_transaction WHERE id = ?", (txn_id,))
            txn = cur.fetchone()
            print(f"Transaction DB Amount: {txn[0] if txn else 'Not found'}")
        print("-" * 50)

conn.close()
