import csv
import sys
import pymssql

QUERY = """
SELECT
    sb.Name             AS PartName,
    sb.Standard,
    sb.Material          AS BoltMaterialGrade,
    sb.Diameter          AS BoltDiameterMM,
    sb.Length            AS BoltLengthMM,
    sb.ScrewHeadOuterDiameter AS HeadDiameterMM,
    sb.HeadHeight        AS HeadHeightMM,
    sb.Weight            AS BoltWeightKG,
    nut.Name             AS NutName,
    nut.ItemNumber       AS NutItemNumber,
    nut.Height           AS NutHeightMM,
    nut.OutsideDiameter  AS NutOutsideDiameterMM
FROM SetBolts sb
LEFT JOIN SetOfBolts sob
    ON sob.Standard = sb.Standard AND sob.Diameter = sb.Diameter AND sob.Material = sb.Material
LEFT JOIN SetNutsBolts nut
    ON nut.Standard = sob.DIN1 AND nut.Diameter = sob.[Diameter1 (mm)] AND nut.Material = sob.Material1
ORDER BY sb.Diameter, sb.Length;
"""


def main():
    if len(sys.argv) != 3:
        print("Usage: python export_bolts.py <DatabaseName> <output.csv>")
        sys.exit(1)

    database = sys.argv[1]
    out_path = sys.argv[2]

    conn = pymssql.connect(
        server="127.0.0.1",
        port=1433,
        user="sa",
        password="Scratch2026!Pw",
        database=database,
    )
    cur = conn.cursor(as_dict=True)
    cur.execute(QUERY)
    rows = cur.fetchall()

    print(f"{len(rows)} bolt records joined from {database}.\n")

    if rows:
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {out_path}")

        print("\nFirst 3 records:")
        for r in rows[:3]:
            print(f"  {r}")

        no_nut = sum(1 for r in rows if r["NutName"] is None)
        if no_nut:
            print(f"\n{no_nut} of {len(rows)} rows had no matching nut record.")
    else:
        print("No rows returned — nothing written.")

    conn.close()


if __name__ == "__main__":
    main()
