import sys
import pymssql

if len(sys.argv) != 2:
    print("Usage: python db_inspect.py <DatabaseName>")
    sys.exit(1)

database = sys.argv[1]

conn = pymssql.connect(
    server="127.0.0.1",
    port=1433,
    user="sa",
    password="Scratch2026!Pw",
    database=database,
)
cur = conn.cursor(as_dict=True)

cur.execute("""
    SELECT TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
    ORDER BY TABLE_NAME
""")
tables = [t["TABLE_NAME"] for t in cur.fetchall()]

print(f"Database: {database}")
print(f"{len(tables)} tables found: {', '.join(tables)}\n")

for table in tables:
    print("=" * 70)
    print(f"TABLE: dbo.{table}")
    print("=" * 70)

    cur.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table,))
    for c in cur.fetchall():
        length = f"({c['CHARACTER_MAXIMUM_LENGTH']})" if c['CHARACTER_MAXIMUM_LENGTH'] else ""
        print(f"  {c['COLUMN_NAME']:<30} {c['DATA_TYPE']}{length:<10} NULL={c['IS_NULLABLE']}")

    cur.execute(f"SELECT COUNT(*) AS cnt FROM dbo.[{table}]")
    count = cur.fetchone()["cnt"]
    print(f"\n  Row count: {count}")

    if count > 0:
        cur.execute(f"SELECT TOP 3 * FROM dbo.[{table}]")
        for r in cur.fetchall():
            print(f"    {r}")

    print()

conn.close()
