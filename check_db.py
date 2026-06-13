import sqlite3

conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def print_table(table_name):
    print(f"\n=== {table_name} ===")
    cur.execute(f"SELECT * FROM {table_name}")
    rows = cur.fetchall()
    for i, r in enumerate(rows):
        print(f"Row {i+1}:", dict(r))

print_table("sales_order")
print_table("payments_transaction")
print_table("payments_webhook_log")
