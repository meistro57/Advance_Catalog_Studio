import pymssql

conn = pymssql.connect(
    server="127.0.0.1",
    port=1433,
    user="sa",
    password="Scratch2026!Pw",
    database="HiltiHY200",
)
cur = conn.cursor(as_dict=True)

tables = [
    "AnchorsDefinition",
    "AnchorsHoleDefinition",
    "AnchorsName",
    "AnchorsStandard",
    "BoltsDiameters",
    "BoltsDistances",
    "SetNutsBolts",
    "Sets",
    "Sources",
    "StrengthClass",
]

for table in tables:
    print("=" * 70)
    print(f"TABLE: dbo.{table}")
    print("=" * 70)

    cur.execute(f"""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table,))
    cols = cur.fetchall()
    for c in cols:
        length = f"({c['CHARACTER_MAXIMUM_LENGTH']})" if c['CHARACTER_MAXIMUM_LENGTH'] else ""
        print(f"  {c['COLUMN_NAME']:<30} {c['DATA_TYPE']}{length:<10} NULL={c['IS_NULLABLE']}")

    cur.execute(f"SELECT COUNT(*) AS cnt FROM dbo.[{table}]")
    count = cur.fetchone()['cnt']
    print(f"\n  Row count: {count}")

    if count > 0:
        cur.execute(f"SELECT TOP 3 * FROM dbo.[{table}]")
        rows = cur.fetchall()
        print(f"  Sample rows:")
        for r in rows:
            print(f"    {r}")

    print()

conn.close()
