import csv
import re
import sys
import pymssql

# --- Name normalization -----------------------------------------------
# Source databases sometimes carry a legacy/internal name that differs
# from the current product designation you want in the output.
# Add (pattern, replacement) pairs here as needed per source.
NAME_NORMALIZATION = [
    (re.compile(r"HY[\s\-]?150", re.IGNORECASE), "HY-200"),
    # Add future rename rules here, e.g.:
    # (re.compile(r"KB[\s\-]?II", re.IGNORECASE), "KB3"),
]


def normalize(value):
    if value is None:
        return value
    for pattern, replacement in NAME_NORMALIZATION:
        value = pattern.sub(replacement, value)
    return value


QUERY = """
SELECT
    ad.PartName,
    an.Standard,
    an.Diameter        AS AnchorDiameterMM,
    an.MaterialKey     AS AnchorMaterialGrade,
    ad.Length          AS AnchorLengthMM,
    ad.ThreadLength    AS ThreadLengthMM,
    ad.TopDistance     AS TopDistanceMM,
    ad.Weight          AS AnchorWeightKG,
    nut.Name           AS NutName,
    nut.ItemNumber     AS NutItemNumber,
    nut.Height         AS NutHeightMM,
    nut.OutsideDiameter AS NutOutsideDiameterMM,
    washer.Name        AS WasherName,
    washer.ItemNumber  AS WasherItemNumber,
    washer.OutsideDiameter AS WasherOutsideDiameterMM
FROM AnchorsDefinition ad
JOIN AnchorsName an
    ON ad.AnchorID = an.ID
LEFT JOIN SetNutsBolts nut
    ON nut.Standard = an.DIN1 AND nut.Diameter = an.Diameter1 AND nut.Material = an.Material1
LEFT JOIN SetNutsBolts washer
    ON washer.Standard = an.DIN2 AND washer.Diameter = an.Diameter2 AND washer.Material = an.Material2
ORDER BY an.Diameter, ad.Length;
"""

NORMALIZE_FIELDS = ["PartName", "Standard"]


def main():
    if len(sys.argv) != 3:
        print("Usage: python export_catalog.py <DatabaseName> <output.csv>")
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

    for row in rows:
        for field in NORMALIZE_FIELDS:
            row[field] = normalize(row[field])

    print(f"{len(rows)} anchor records joined and normalized from {database}.\n")

    if rows:
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {out_path}")

        print("\nFirst 3 records:")
        for r in rows[:3]:
            print(f"  {r}")
    else:
        print("No rows returned — nothing written.")

    conn.close()


if __name__ == "__main__":
    main()
