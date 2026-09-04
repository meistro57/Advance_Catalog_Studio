import pymssql

conn = pymssql.connect(
    server="127.0.0.1",
    port=1433,
    user="sa",
    password="Scratch2026!Pw",
    database="BoltsA325",
)
cur = conn.cursor(as_dict=True)

print("=== Sets table (all rows) ===")
cur.execute("SELECT * FROM Sets")
for r in cur.fetchall():
    print(f"  {r}")

print("\n=== SetOfBolts grouped by [Set] (Diameter = 12.7) ===")
cur.execute("""
    SELECT [Set], DIN1, [Diameter1 (mm)], Material1, DIN2, [Diameter2 (mm)], Material2,
           DIN3, [Diameter3 (mm)], Material3
    FROM SetOfBolts
    WHERE Diameter = 12.7
    ORDER BY [Set]
""")
for r in cur.fetchall():
    print(f"  {r}")

conn.close()
