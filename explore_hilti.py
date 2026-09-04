import pymssql

conn = pymssql.connect(
    server="127.0.0.1",
    port=1433,
    user="sa",
    password="Scratch2026!Pw",
    database="HiltiHY200",
)
cur = conn.cursor(as_dict=True)

cur.execute("""
    SELECT TABLE_SCHEMA, TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
    ORDER BY TABLE_SCHEMA, TABLE_NAME
""")

tables = cur.fetchall()
print(f"{len(tables)} tables found:\n")
for t in tables:
    print(f"  {t['TABLE_SCHEMA']}.{t['TABLE_NAME']}")

conn.close()
