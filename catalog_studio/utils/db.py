# utils/db.py
"""SQL Server operations against the scratch container: attach/detach
databases, browse tables generically, and edit/duplicate/delete rows
regardless of which catalog schema (anchors, bolts, whatever) is loaded."""

import re

import pymssql

from config import DB_CONFIG, CONTAINER_ATTACH_PATH

VALID_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def valid_identifier(name: str) -> bool:
    return bool(VALID_IDENTIFIER.match(name or ""))


def connect(database=None):
    conn = pymssql.connect(
        server=DB_CONFIG["server"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=database,
        autocommit=True,
    )
    cur = conn.cursor(as_dict=True)
    return conn, cur


def list_databases():
    conn, cur = connect()
    cur.execute("SELECT name FROM sys.databases WHERE database_id > 4 ORDER BY name")
    names = [r["name"] for r in cur.fetchall()]
    conn.close()
    return names


def attach_database(db_name: str, mdf_filename: str, ldf_filename: str):
    if not valid_identifier(db_name):
        raise ValueError("Database name must be letters, numbers, underscores only.")
    mdf_path = f"{CONTAINER_ATTACH_PATH}/{mdf_filename}"
    ldf_path = f"{CONTAINER_ATTACH_PATH}/{ldf_filename}"
    conn, cur = connect()
    cur.execute(f"""
        CREATE DATABASE [{db_name}] ON
        (FILENAME = N'{mdf_path}'),
        (FILENAME = N'{ldf_path}')
        FOR ATTACH;
    """)
    conn.close()


def detach_database(db_name: str):
    if not valid_identifier(db_name):
        raise ValueError("Invalid database name.")
    conn, cur = connect()
    cur.execute(f"ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;")
    cur.execute(f"EXEC sp_detach_db N'{db_name}';")
    conn.close()


def list_tables(database: str):
    conn, cur = connect(database)
    cur.execute("""
        SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """)
    names = [r["TABLE_NAME"] for r in cur.fetchall()]
    conn.close()
    return names


def get_columns(database: str, table: str):
    conn, cur = connect(database)
    cur.execute("""
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table,))
    cols = cur.fetchall()
    conn.close()
    return cols


def get_row_count(database: str, table: str) -> int:
    conn, cur = connect(database)
    cur.execute(f"SELECT COUNT(*) AS cnt FROM [{table}]")
    count = cur.fetchone()["cnt"]
    conn.close()
    return count


def get_rows(database: str, table: str, limit: int = 1000):
    conn, cur = connect(database)
    cur.execute(f"SELECT TOP {int(limit)} * FROM [{table}]")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_rows_filtered(database: str, table: str, filter_col: str, filter_op: str, filter_val: str, limit: int = 1000):
    """Filter a table by one of its own columns."""
    conn, cur = connect(database)
    if filter_op == "contains":
        cur.execute(
            f"SELECT TOP {int(limit)} * FROM [{table}] WHERE [{filter_col}] LIKE %s",
            (_like_pattern(filter_val),),
        )
    else:
        cur.execute(
            f"SELECT TOP {int(limit)} * FROM [{table}] WHERE [{filter_col}] = %s",
            (filter_val,),
        )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_rows_joined_filter(database: str, table: str, join_table: str, local_col: str,
                           foreign_col: str, join_column: str, join_value: str, limit: int = 1000):
    """Filter a table by a column on a RELATED table (e.g. AnchorsDefinition
    filtered by AnchorsName.Diameter, joined via AnchorID -> ID)."""
    conn, cur = connect(database)
    cur.execute(f"""
        SELECT TOP {int(limit)} t.*
        FROM [{table}] t
        JOIN [{join_table}] j ON t.[{local_col}] = j.[{foreign_col}]
        WHERE j.[{join_column}] = %s
    """, (join_value,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_column_values(database: str, table: str, column: str, limit: int = 200):
    """Distinct non-null values for a column, for populating a filter dropdown."""
    conn, cur = connect(database)
    cur.execute(
        f"SELECT DISTINCT TOP {int(limit)} [{column}] AS v FROM [{table}] "
        f"WHERE [{column}] IS NOT NULL ORDER BY [{column}]"
    )
    values = [r["v"] for r in cur.fetchall()]
    conn.close()
    return values


# Per-table "virtual" filters that reach into a related table. Add more here
# as other schemas need it (e.g. a bolt table filtering by hardware set).
VIRTUAL_FILTERS = {
    "AnchorsDefinition": {
        "label": "Diameter (via linked anchor)",
        "join_table": "AnchorsName",
        "local_col": "AnchorID",
        "foreign_col": "ID",
        "join_column": "Diameter",
    },
}


def get_row(database: str, table: str, pk_col: str, pk_val):
    conn, cur = connect(database)
    cur.execute(f"SELECT * FROM [{table}] WHERE [{pk_col}] = %s", (pk_val,))
    row = cur.fetchone()
    conn.close()
    return row


def guess_primary_key(database: str, table: str):
    """Prefer an actual PK/identity column; fall back to a column named ID."""
    conn, cur = connect(database)
    cur.execute("""
        SELECT c.name
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        JOIN sys.tables t ON t.object_id = i.object_id
        WHERE t.name = %s AND i.is_primary_key = 1
    """, (table,))
    row = cur.fetchone()
    conn.close()
    if row:
        return row["name"]
    cols = [c["COLUMN_NAME"] for c in get_columns(database, table)]
    return "ID" if "ID" in cols else None


def is_identity_column(database: str, table: str, column: str) -> bool:
    if not column:
        return False
    conn, cur = connect(database)
    cur.execute("""
        SELECT COUNT(*) AS cnt
        FROM sys.identity_columns ic
        JOIN sys.tables t ON ic.object_id = t.object_id
        WHERE t.name = %s AND ic.name = %s
    """, (table, column))
    result = cur.fetchone()["cnt"] > 0
    conn.close()
    return result


def coerce_value(value, data_type: str):
    if value is None or value == "":
        return None
    if data_type in ("float", "real", "decimal", "numeric"):
        return float(value)
    if data_type in ("int", "bigint", "smallint", "tinyint"):
        return int(value)
    if data_type == "bit":
        return 1 if str(value).lower() in ("1", "true", "on", "yes") else 0
    return value


def update_row(database: str, table: str, pk_col: str, pk_val, updates: dict):
    conn, cur = connect(database)
    set_clause = ", ".join(f"[{c}] = %s" for c in updates)
    values = list(updates.values()) + [pk_val]
    cur.execute(f"UPDATE [{table}] SET {set_clause} WHERE [{pk_col}] = %s", values)
    conn.close()


def insert_row(database: str, table: str, values: dict):
    conn, cur = connect(database)
    cols = list(values.keys())
    col_list = ", ".join(f"[{c}]" for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))
    cur.execute(
        f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})",
        list(values.values()),
    )
    conn.close()


def duplicate_row(database: str, table: str, pk_col: str, pk_val):
    """Clone a row. If the PK is an IDENTITY column, SQL Server assigns the
    new ID automatically. Otherwise we compute the next integer PK ourselves."""
    row = get_row(database, table, pk_col, pk_val)
    if not row:
        return None

    conn, cur = connect(database)
    identity = is_identity_column(database, table, pk_col)

    if identity or not pk_col:
        cols = [c for c in row.keys() if c != pk_col] if pk_col else list(row.keys())
        values = [row[c] for c in cols]
        col_list = ", ".join(f"[{c}]" for c in cols)
        placeholders = ", ".join(["%s"] * len(cols))
        cur.execute(f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})", values)
        new_id = None
    else:
        cur.execute(f"SELECT MAX([{pk_col}]) AS max_id FROM [{table}]")
        max_id = cur.fetchone()["max_id"] or 0
        new_id = max_id + 1
        cols = [c for c in row.keys() if c != pk_col]
        values = [row[c] for c in cols]
        col_list = ", ".join(f"[{c}]" for c in [pk_col] + cols)
        placeholders = ", ".join(["%s"] * (len(cols) + 1))
        cur.execute(
            f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})",
            [new_id] + values,
        )

    conn.close()
    return new_id


def delete_row(database: str, table: str, pk_col: str, pk_val):
    conn, cur = connect(database)
    cur.execute(f"DELETE FROM [{table}] WHERE [{pk_col}] = %s", (pk_val,))
    conn.close()


# --------------------------------------------------------------------------
# Fresh catalog creation
# --------------------------------------------------------------------------

def create_empty_database(db_name: str):
    if not valid_identifier(db_name):
        raise ValueError("Database name must be letters, numbers, underscores only.")
    mdf_path = f"{CONTAINER_ATTACH_PATH}/{db_name}.mdf"
    ldf_path = f"{CONTAINER_ATTACH_PATH}/{db_name}_log.ldf"
    conn, cur = connect()
    cur.execute(f"""
        CREATE DATABASE [{db_name}] ON
        (NAME = N'{db_name}', FILENAME = N'{mdf_path}')
        LOG ON
        (NAME = N'{db_name}_log', FILENAME = N'{ldf_path}');
    """)
    conn.close()


def get_physical_files(database: str) -> dict:
    """Ask SQL Server directly for a database's real mdf/ldf paths inside the
    container. Never assume the physical filename matches the database name --
    they can diverge (e.g. attached under a different name than the source file)."""
    conn, cur = connect()
    cur.execute("""
        SELECT mf.type_desc, mf.physical_name
        FROM sys.master_files mf
        JOIN sys.databases d ON mf.database_id = d.database_id
        WHERE d.name = %s
    """, (database,))
    rows = cur.fetchall()
    conn.close()
    result = {}
    for r in rows:
        if r["type_desc"] == "ROWS":
            result["mdf"] = r["physical_name"]
        elif r["type_desc"] == "LOG":
            result["ldf"] = r["physical_name"]
    return result


def run_script(database: str, statements: list):
    """Run a list of DDL/DML statements against a database, one at a time."""
    conn, cur = connect(database)
    for stmt in statements:
        cur.execute(stmt)
    conn.close()


def guess_catalog_type(database: str) -> str:
    tables = set(list_tables(database))
    if "AnchorsDefinition" in tables:
        return "anchor"
    if "SetBolts" in tables:
        return "bolt"
    return "unknown"


# --------------------------------------------------------------------------
# Database-wide find & replace
# --------------------------------------------------------------------------

def _like_pattern(value: str) -> str:
    """Escape LIKE wildcards so a literal search string behaves literally."""
    escaped = value.replace("[", "[[]").replace("%", "[%]").replace("_", "[_]")
    return f"%{escaped}%"


def find_text_columns(database: str):
    """Return [(table, column)] for every string-type column in the database."""
    conn, cur = connect(database)
    cur.execute("""
        SELECT TABLE_NAME, COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE DATA_TYPE IN ('nvarchar', 'varchar', 'nchar', 'char', 'text', 'ntext')
        ORDER BY TABLE_NAME, COLUMN_NAME
    """)
    cols = [(r["TABLE_NAME"], r["COLUMN_NAME"]) for r in cur.fetchall()]
    conn.close()
    return cols


def preview_find_replace(database: str, find_text: str) -> dict:
    """Return {'table.column': match_count} for every text column containing find_text."""
    results = {}
    pattern = _like_pattern(find_text)
    for table, column in find_text_columns(database):
        conn, cur = connect(database)
        cur.execute(f"SELECT COUNT(*) AS cnt FROM [{table}] WHERE [{column}] LIKE %s", (pattern,))
        count = cur.fetchone()["cnt"]
        conn.close()
        if count:
            results[f"{table}.{column}"] = count
    return results


def apply_find_replace(database: str, find_text: str, replace_text: str) -> dict:
    """Run REPLACE() across every text column of every table. Returns {'table.column': rows_updated}."""
    results = {}
    pattern = _like_pattern(find_text)
    for table, column in find_text_columns(database):
        conn, cur = connect(database)
        cur.execute(
            f"UPDATE [{table}] SET [{column}] = REPLACE([{column}], %s, %s) "
            f"WHERE [{column}] LIKE %s",
            (find_text, replace_text, pattern),
        )
        affected = cur.rowcount
        conn.close()
        if affected:
            results[f"{table}.{column}"] = affected
    return results


# --------------------------------------------------------------------------
# Diameter Management & Cascading Clone
# --------------------------------------------------------------------------

STANDARD_DIAMETERS = [
    {"fraction": '1/4"', "label": '1/4" (6.35 mm)', "mm": 6.35, "run_name": " 1/4 inch", "token": "1/4"},
    {"fraction": '5/16"', "label": '5/16" (7.938 mm)', "mm": 7.9375, "run_name": " 5/16 inch", "token": "5/16"},
    {"fraction": '3/8"', "label": '3/8" (9.525 mm)', "mm": 9.525, "run_name": " 3/8 inch", "token": "3/8"},
    {"fraction": '7/16"', "label": '7/16" (11.113 mm)', "mm": 11.1125, "run_name": " 7/16 inch", "token": "7/16"},
    {"fraction": '1/2"', "label": '1/2" (12.7 mm)', "mm": 12.7, "run_name": " 1/2 inch", "token": "1/2"},
    {"fraction": '9/16"', "label": '9/16" (14.288 mm)', "mm": 14.2875, "run_name": " 9/16 inch", "token": "9/16"},
    {"fraction": '5/8"', "label": '5/8" (15.875 mm)', "mm": 15.875, "run_name": " 5/8 inch", "token": "5/8"},
    {"fraction": '3/4"', "label": '3/4" (19.05 mm)', "mm": 19.05, "run_name": " 3/4 inch", "token": "3/4"},
    {"fraction": '7/8"', "label": '7/8" (22.225 mm)', "mm": 22.225, "run_name": " 7/8 inch", "token": "7/8"},
    {"fraction": '1"', "label": '1" (25.4 mm)', "mm": 25.4, "run_name": " 1 inch", "token": "1"},
    {"fraction": '1 1/8"', "label": '1 1/8" (28.575 mm)', "mm": 28.575, "run_name": " 1 1/8 inch", "token": "1 1/8"},
    {"fraction": '1 1/4"', "label": '1 1/4" (31.75 mm)', "mm": 31.75, "run_name": " 1 1/4 inch", "token": "1 1/4"},
    {"fraction": '1 3/8"', "label": '1 3/8" (34.925 mm)', "mm": 34.925, "run_name": " 1 3/8 inch", "token": "1 3/8"},
    {"fraction": '1 1/2"', "label": '1 1/2" (38.1 mm)', "mm": 38.1, "run_name": " 1 1/2 inch", "token": "1 1/2"},
    {"fraction": 'M6', "label": 'M6 (6.0 mm)', "mm": 6.0, "run_name": "  6.00 mm", "token": "M6"},
    {"fraction": 'M8', "label": 'M8 (8.0 mm)', "mm": 8.0, "run_name": "  8.00 mm", "token": "M8"},
    {"fraction": 'M10', "label": 'M10 (10.0 mm)', "mm": 10.0, "run_name": " 10.00 mm", "token": "M10"},
    {"fraction": 'M12', "label": 'M12 (12.0 mm)', "mm": 12.0, "run_name": " 12.00 mm", "token": "M12"},
    {"fraction": 'M14', "label": 'M14 (14.0 mm)', "mm": 14.0, "run_name": " 14.00 mm", "token": "M14"},
    {"fraction": 'M16', "label": 'M16 (16.0 mm)', "mm": 16.0, "run_name": " 16.00 mm", "token": "M16"},
    {"fraction": 'M18', "label": 'M18 (18.0 mm)', "mm": 18.0, "run_name": " 18.00 mm", "token": "M18"},
    {"fraction": 'M20', "label": 'M20 (20.0 mm)', "mm": 20.0, "run_name": " 20.00 mm", "token": "M20"},
    {"fraction": 'M22', "label": 'M22 (22.0 mm)', "mm": 22.0, "run_name": " 22.00 mm", "token": "M22"},
    {"fraction": 'M24', "label": 'M24 (24.0 mm)', "mm": 24.0, "run_name": " 24.00 mm", "token": "M24"},
    {"fraction": 'M27', "label": 'M27 (27.0 mm)', "mm": 27.0, "run_name": " 27.00 mm", "token": "M27"},
    {"fraction": 'M30', "label": 'M30 (30.0 mm)', "mm": 30.0, "run_name": " 30.00 mm", "token": "M30"},
    {"fraction": 'M36', "label": 'M36 (36.0 mm)', "mm": 36.0, "run_name": " 36.00 mm", "token": "M36"},
]


def guess_token(run_name: str, dia_mm: float) -> str:
    if not run_name:
        return str(dia_mm)
    s = run_name.strip()
    m = re.match(r'^(.*?)\s*(?:inch|in|\"|mm)$', s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s


def smart_replace_name(name: str, replace_from: str, replace_to: str) -> str:
    if not name or not replace_from or not replace_to:
        return name
    # Pattern 1: Bolt name e.g. 'A325TC 1/2 x 1' -> replace diameter token right before ' x '
    p1 = re.compile(r'(?<=\s)' + re.escape(replace_from) + r'(?=\s*x\b)', re.IGNORECASE)
    if p1.search(name):
        return p1.sub(replace_to, name)
    # Pattern 2: Component name e.g. 'A563 Nut 1/2' or 'Washer F436 - 1/2'
    p2 = re.compile(r'(?<=[-\s])' + re.escape(replace_from) + r'(?=$|\s)', re.IGNORECASE)
    if p2.search(name):
        return p2.sub(replace_to, name)
    return name.replace(replace_from, replace_to)


def get_catalog_diameters(database: str) -> list:
    """Return all diameters present in the database with row counts across related tables."""
    conn, cur = connect(database)
    tables = set(list_tables(database))
    catalog_type = guess_catalog_type(database)

    diam_dict = {}

    if "BoltsDiameters" in tables:
        cur.execute("SELECT [Key], RunName, Description FROM BoltsDiameters ORDER BY [Key]")
        for r in cur.fetchall():
            k = r["Key"]
            diam_dict[k] = {
                "key": k,
                "run_name": r["RunName"] or "",
                "description": r["Description"] or "",
                "token": guess_token(r["RunName"], k),
                "counts": {},
            }

    check_tables = []
    if catalog_type == "bolt":
        check_tables = [t for t in ["BoltsDistances", "ScrewNew", "SetOfBolts", "SetNutsBolts", "SetBolts"] if t in tables]
    elif catalog_type == "anchor":
        check_tables = [t for t in ["BoltsDistances", "AnchorsName", "SetNutsBolts"] if t in tables]
    else:
        check_tables = [t for t in ["BoltsDistances", "ScrewNew", "SetOfBolts", "SetNutsBolts", "SetBolts", "AnchorsName"] if t in tables]

    for t in check_tables:
        cur.execute(f"SELECT Diameter, COUNT(*) AS cnt FROM [{t}] GROUP BY Diameter")
        for r in cur.fetchall():
            d = r["Diameter"]
            if d not in diam_dict:
                diam_dict[d] = {
                    "key": d,
                    "run_name": f"{d} mm",
                    "description": "",
                    "token": str(d),
                    "counts": {},
                }
            diam_dict[d]["counts"][t] = r["cnt"]

    conn.close()

    result = []
    for k in sorted(diam_dict.keys()):
        item = diam_dict[k]
        total_related = sum(item["counts"].values())
        item["total_related"] = total_related
        item["is_orphan"] = (total_related == 0)
        result.append(item)

    return result


def preview_clone_diameter(
    database: str,
    source_dia: float,
    target_dia: float,
    target_name: str,
    replace_from: str = "",
    replace_to: str = "",
    scale_dimensions: bool = True,
    scale_along_across: bool = True,
    include_tables: list = None,
) -> dict:
    conn, cur = connect(database)
    tables = set(list_tables(database))
    catalog_type = guess_catalog_type(database)
    scale = (target_dia / source_dia) if source_dia else 1.0

    preview = {
        "database": database,
        "catalog_type": catalog_type,
        "source_dia": source_dia,
        "target_dia": target_dia,
        "target_name": target_name,
        "scale": round(scale, 4),
        "tables": {},
        "orphans_found": [],
    }

    # Check for potential orphans in BoltsDiameters (e.g. key != target_dia but RunName token matches replace_to)
    if "BoltsDiameters" in tables:
        cur.execute("SELECT [Key], RunName FROM BoltsDiameters")
        for r in cur.fetchall():
            k = r["Key"]
            token = guess_token(r["RunName"], k)
            if replace_to and token == replace_to and abs(k - target_dia) > 0.001:
                preview["orphans_found"].append({"key": k, "run_name": r["RunName"]})

    # 1. BoltsDiameters
    if "BoltsDiameters" in tables and (include_tables is None or "BoltsDiameters" in include_tables):
        preview["tables"]["BoltsDiameters"] = {
            "count": 1,
            "samples": [{"Key": target_dia, "RunName": target_name, "Description": None}],
        }

    # 2. BoltsDistances
    if "BoltsDistances" in tables and (include_tables is None or "BoltsDistances" in include_tables):
        cur.execute("SELECT * FROM BoltsDistances WHERE Diameter = %s", (source_dia,))
        src_rows = cur.fetchall()
        samples = []
        for r in src_rows:
            along_val = round(r["along"] * scale, 4) if scale_along_across and r.get("along") is not None else r.get("along")
            across_val = round(r["across"] * scale, 4) if scale_along_across and r.get("across") is not None else r.get("across")
            desc = r.get("Description") or ""
            desc = desc.replace(str(source_dia).replace(".", ","), str(target_dia).replace(".", ","))\
                       .replace(str(source_dia), str(target_dia))
            samples.append({
                "Diameter": target_dia,
                "HoleTolerance": r["HoleTolerance"],
                "along": along_val,
                "across": across_val,
                "Description": desc,
            })
        preview["tables"]["BoltsDistances"] = {
            "count": len(samples),
            "samples": samples[:3],
        }

    # Bolt catalog specific tables
    if catalog_type == "bolt":
        # 3. ScrewNew
        if "ScrewNew" in tables and (include_tables is None or "ScrewNew" in include_tables):
            cur.execute("SELECT * FROM ScrewNew WHERE Diameter = %s", (source_dia,))
            src_rows = cur.fetchall()
            samples = []
            for r in src_rows:
                r_dict = dict(r)
                r_dict["Diameter"] = target_dia
                samples.append(r_dict)
            preview["tables"]["ScrewNew"] = {
                "count": len(samples),
                "samples": samples[:3],
            }

        # 4. SetOfBolts
        if "SetOfBolts" in tables and (include_tables is None or "SetOfBolts" in include_tables):
            cur.execute("SELECT * FROM SetOfBolts WHERE Diameter = %s", (source_dia,))
            src_rows = cur.fetchall()
            samples = []
            for r in src_rows:
                r_dict = dict(r)
                r_dict["Diameter"] = target_dia
                for i in range(1, 7):
                    c_name = f"Diameter{i} (mm)"
                    if c_name in r_dict and r_dict[c_name] is not None and abs(r_dict[c_name] - source_dia) < 0.001:
                        r_dict[c_name] = target_dia
                samples.append(r_dict)
            preview["tables"]["SetOfBolts"] = {
                "count": len(samples),
                "samples": samples[:3],
            }

        # 5. SetNutsBolts
        if "SetNutsBolts" in tables and (include_tables is None or "SetNutsBolts" in include_tables):
            cur.execute("SELECT * FROM SetNutsBolts WHERE Diameter = %s", (source_dia,))
            src_rows = cur.fetchall()
            samples = []
            for r in src_rows:
                r_dict = dict(r)
                r_dict["Diameter"] = target_dia
                if r_dict.get("Name"):
                    r_dict["Name"] = smart_replace_name(r_dict["Name"], replace_from, replace_to)
                if scale_dimensions:
                    if r_dict.get("OutsideDiameter"):
                        r_dict["OutsideDiameter"] = round(r_dict["OutsideDiameter"] * scale, 4)
                    if r_dict.get("Height"):
                        r_dict["Height"] = round(r_dict["Height"] * scale, 4)
                    if r_dict.get("Weight"):
                        r_dict["Weight"] = round(r_dict["Weight"] * (scale ** 2), 5)
                samples.append(r_dict)
            preview["tables"]["SetNutsBolts"] = {
                "count": len(samples),
                "samples": samples[:3],
            }

        # 6. SetBolts
        if "SetBolts" in tables and (include_tables is None or "SetBolts" in include_tables):
            cur.execute("SELECT * FROM SetBolts WHERE Diameter = %s", (source_dia,))
            src_rows = cur.fetchall()
            samples = []
            for r in src_rows:
                r_dict = dict(r)
                r_dict["Diameter"] = target_dia
                if r_dict.get("Name"):
                    r_dict["Name"] = smart_replace_name(r_dict["Name"], replace_from, replace_to)
                if scale_dimensions:
                    if r_dict.get("ScrewHeadOuterDiameter"):
                        r_dict["ScrewHeadOuterDiameter"] = round(r_dict["ScrewHeadOuterDiameter"] * scale, 4)
                    if r_dict.get("HeadHeight"):
                        r_dict["HeadHeight"] = round(r_dict["HeadHeight"] * scale, 4)
                    if r_dict.get("Weight"):
                        r_dict["Weight"] = round(r_dict["Weight"] * (scale ** 2), 5)
                samples.append(r_dict)
            preview["tables"]["SetBolts"] = {
                "count": len(samples),
                "samples": samples[:3],
            }

    # Anchor catalog specific tables
    elif catalog_type == "anchor":
        if "SetNutsBolts" in tables and (include_tables is None or "SetNutsBolts" in include_tables):
            cur.execute("SELECT * FROM SetNutsBolts WHERE Diameter = %s", (source_dia,))
            src_rows = cur.fetchall()
            samples = []
            for r in src_rows:
                r_dict = dict(r)
                r_dict["Diameter"] = target_dia
                if r_dict.get("Name"):
                    r_dict["Name"] = smart_replace_name(r_dict["Name"], replace_from, replace_to)
                if scale_dimensions:
                    if r_dict.get("OutsideDiameter"):
                        r_dict["OutsideDiameter"] = round(r_dict["OutsideDiameter"] * scale, 4)
                    if r_dict.get("Height"):
                        r_dict["Height"] = round(r_dict["Height"] * scale, 4)
                    if r_dict.get("Weight"):
                        r_dict["Weight"] = round(r_dict["Weight"] * (scale ** 2), 5)
                samples.append(r_dict)
            preview["tables"]["SetNutsBolts"] = {
                "count": len(samples),
                "samples": samples[:3],
            }

        if "AnchorsName" in tables and (include_tables is None or "AnchorsName" in include_tables):
            cur.execute("SELECT * FROM AnchorsName WHERE Diameter = %s", (source_dia,))
            src_rows = cur.fetchall()
            samples = []
            for r in src_rows:
                r_dict = dict(r)
                r_dict["Diameter"] = target_dia
                for i in range(1, 7):
                    if f"Diameter{i}" in r_dict and r_dict[f"Diameter{i}"] is not None and abs(r_dict[f"Diameter{i}"] - source_dia) < 0.001:
                        r_dict[f"Diameter{i}"] = target_dia
                samples.append(r_dict)
            preview["tables"]["AnchorsName"] = {
                "count": len(samples),
                "samples": samples[:3],
            }

            if "AnchorsDefinition" in tables:
                cur.execute("""
                    SELECT COUNT(*) as cnt
                    FROM AnchorsDefinition ad
                    JOIN AnchorsName an ON ad.AnchorID = an.ID
                    WHERE an.Diameter = %s
                """, (source_dia,))
                def_cnt = cur.fetchone()["cnt"]
                preview["tables"]["AnchorsDefinition"] = {"count": def_cnt, "samples": []}

            if "AnchorsHoleDefinition" in tables:
                cur.execute("""
                    SELECT COUNT(*) as cnt
                    FROM AnchorsHoleDefinition ah
                    JOIN AnchorsName an ON ah.AnchorNameID = an.ID
                    WHERE an.Diameter = %s
                """, (source_dia,))
                hole_cnt = cur.fetchone()["cnt"]
                preview["tables"]["AnchorsHoleDefinition"] = {"count": hole_cnt, "samples": []}

    conn.close()
    preview["total_rows"] = sum(t["count"] for t in preview["tables"].values())
    return preview


def apply_clone_diameter(
    database: str,
    source_dia: float,
    target_dia: float,
    target_name: str,
    replace_from: str = "",
    replace_to: str = "",
    scale_dimensions: bool = True,
    scale_along_across: bool = True,
    include_tables: list = None,
    cleanup_keys: list = None,
) -> dict:
    conn = pymssql.connect(
        server=DB_CONFIG["server"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=database,
        autocommit=False,
    )
    cur = conn.cursor(as_dict=True)
    tables = set(list_tables(database))
    catalog_type = guess_catalog_type(database)
    scale = (target_dia / source_dia) if source_dia else 1.0
    inserted_counts = {}

    try:
        # 0. Clean up any orphan keys if requested
        if cleanup_keys and "BoltsDiameters" in tables:
            for k in cleanup_keys:
                cur.execute("DELETE FROM BoltsDiameters WHERE [Key] = %s", (float(k),))

        # 1. BoltsDiameters
        if "BoltsDiameters" in tables and (include_tables is None or "BoltsDiameters" in include_tables):
            cur.execute("SELECT COUNT(*) AS cnt FROM BoltsDiameters WHERE [Key] = %s", (target_dia,))
            if cur.fetchone()["cnt"] > 0:
                cur.execute("UPDATE BoltsDiameters SET RunName = %s WHERE [Key] = %s", (target_name, target_dia))
            else:
                cur.execute("INSERT INTO BoltsDiameters ([Key], RunName) VALUES (%s, %s)", (target_dia, target_name))
            inserted_counts["BoltsDiameters"] = 1

        # 2. BoltsDistances
        if "BoltsDistances" in tables and (include_tables is None or "BoltsDistances" in include_tables):
            cur.execute("DELETE FROM BoltsDistances WHERE Diameter = %s", (target_dia,))
            cur.execute("SELECT * FROM BoltsDistances WHERE Diameter = %s", (source_dia,))
            src_rows = cur.fetchall()
            for r in src_rows:
                along_val = round(r["along"] * scale, 4) if scale_along_across and r.get("along") is not None else r.get("along")
                across_val = round(r["across"] * scale, 4) if scale_along_across and r.get("across") is not None else r.get("across")
                desc = r.get("Description") or ""
                desc = desc.replace(str(source_dia).replace(".", ","), str(target_dia).replace(".", ","))\
                           .replace(str(source_dia), str(target_dia))
                cur.execute("""
                    INSERT INTO BoltsDistances (Diameter, HoleTolerance, along, across, Description)
                    VALUES (%s, %s, %s, %s, %s)
                """, (target_dia, r["HoleTolerance"], along_val, across_val, desc))
            inserted_counts["BoltsDistances"] = len(src_rows)

        if catalog_type == "bolt":
            # 3. ScrewNew
            if "ScrewNew" in tables and (include_tables is None or "ScrewNew" in include_tables):
                cur.execute("DELETE FROM ScrewNew WHERE Diameter = %s", (target_dia,))
                cur.execute("SELECT * FROM ScrewNew WHERE Diameter = %s", (source_dia,))
                src_rows = cur.fetchall()
                if src_rows:
                    cols = list(src_rows[0].keys())
                    col_str = ", ".join(f"[{c}]" for c in cols)
                    placeholders = ", ".join(["%s"] * len(cols))
                    for r in src_rows:
                        r_dict = dict(r)
                        r_dict["Diameter"] = target_dia
                        cur.execute(f"INSERT INTO ScrewNew ({col_str}) VALUES ({placeholders})", [r_dict[c] for c in cols])
                inserted_counts["ScrewNew"] = len(src_rows)

            # 4. SetOfBolts
            if "SetOfBolts" in tables and (include_tables is None or "SetOfBolts" in include_tables):
                cur.execute("DELETE FROM SetOfBolts WHERE Diameter = %s", (target_dia,))
                cur.execute("SELECT * FROM SetOfBolts WHERE Diameter = %s", (source_dia,))
                src_rows = cur.fetchall()
                if src_rows:
                    cols = list(src_rows[0].keys())
                    col_str = ", ".join(f"[{c}]" for c in cols)
                    placeholders = ", ".join(["%s"] * len(cols))
                    for r in src_rows:
                        r_dict = dict(r)
                        r_dict["Diameter"] = target_dia
                        for i in range(1, 7):
                            c_name = f"Diameter{i} (mm)"
                            if c_name in r_dict and r_dict[c_name] is not None and abs(r_dict[c_name] - source_dia) < 0.001:
                                r_dict[c_name] = target_dia
                        cur.execute(f"INSERT INTO SetOfBolts ({col_str}) VALUES ({placeholders})", [r_dict[c] for c in cols])
                inserted_counts["SetOfBolts"] = len(src_rows)

            # 5. SetNutsBolts
            if "SetNutsBolts" in tables and (include_tables is None or "SetNutsBolts" in include_tables):
                cur.execute("DELETE FROM SetNutsBolts WHERE Diameter = %s", (target_dia,))
                cur.execute("SELECT * FROM SetNutsBolts WHERE Diameter = %s", (source_dia,))
                src_rows = cur.fetchall()
                if src_rows:
                    cols = list(src_rows[0].keys())
                    col_str = ", ".join(f"[{c}]" for c in cols)
                    placeholders = ", ".join(["%s"] * len(cols))
                    for r in src_rows:
                        r_dict = dict(r)
                        r_dict["Diameter"] = target_dia
                        if r_dict.get("Name"):
                            r_dict["Name"] = smart_replace_name(r_dict["Name"], replace_from, replace_to)
                        if scale_dimensions:
                            if r_dict.get("OutsideDiameter"):
                                r_dict["OutsideDiameter"] = round(r_dict["OutsideDiameter"] * scale, 4)
                            if r_dict.get("Height"):
                                r_dict["Height"] = round(r_dict["Height"] * scale, 4)
                            if r_dict.get("Weight"):
                                r_dict["Weight"] = round(r_dict["Weight"] * (scale ** 2), 5)
                        cur.execute(f"INSERT INTO SetNutsBolts ({col_str}) VALUES ({placeholders})", [r_dict[c] for c in cols])
                inserted_counts["SetNutsBolts"] = len(src_rows)

            # 6. SetBolts
            if "SetBolts" in tables and (include_tables is None or "SetBolts" in include_tables):
                cur.execute("DELETE FROM SetBolts WHERE Diameter = %s", (target_dia,))
                cur.execute("SELECT * FROM SetBolts WHERE Diameter = %s", (source_dia,))
                src_rows = cur.fetchall()
                if src_rows:
                    cols = list(src_rows[0].keys())
                    col_str = ", ".join(f"[{c}]" for c in cols)
                    placeholders = ", ".join(["%s"] * len(cols))
                    for r in src_rows:
                        r_dict = dict(r)
                        r_dict["Diameter"] = target_dia
                        if r_dict.get("Name"):
                            r_dict["Name"] = smart_replace_name(r_dict["Name"], replace_from, replace_to)
                        if scale_dimensions:
                            if r_dict.get("ScrewHeadOuterDiameter"):
                                r_dict["ScrewHeadOuterDiameter"] = round(r_dict["ScrewHeadOuterDiameter"] * scale, 4)
                            if r_dict.get("HeadHeight"):
                                r_dict["HeadHeight"] = round(r_dict["HeadHeight"] * scale, 4)
                            if r_dict.get("Weight"):
                                r_dict["Weight"] = round(r_dict["Weight"] * (scale ** 2), 5)
                        cur.execute(f"INSERT INTO SetBolts ({col_str}) VALUES ({placeholders})", [r_dict[c] for c in cols])
                inserted_counts["SetBolts"] = len(src_rows)

        elif catalog_type == "anchor":
            # SetNutsBolts
            if "SetNutsBolts" in tables and (include_tables is None or "SetNutsBolts" in include_tables):
                cur.execute("DELETE FROM SetNutsBolts WHERE Diameter = %s", (target_dia,))
                cur.execute("SELECT * FROM SetNutsBolts WHERE Diameter = %s", (source_dia,))
                src_rows = cur.fetchall()
                if src_rows:
                    cols = list(src_rows[0].keys())
                    col_str = ", ".join(f"[{c}]" for c in cols)
                    placeholders = ", ".join(["%s"] * len(cols))
                    for r in src_rows:
                        r_dict = dict(r)
                        r_dict["Diameter"] = target_dia
                        if r_dict.get("Name"):
                            r_dict["Name"] = smart_replace_name(r_dict["Name"], replace_from, replace_to)
                        if scale_dimensions:
                            if r_dict.get("OutsideDiameter"):
                                r_dict["OutsideDiameter"] = round(r_dict["OutsideDiameter"] * scale, 4)
                            if r_dict.get("Height"):
                                r_dict["Height"] = round(r_dict["Height"] * scale, 4)
                            if r_dict.get("Weight"):
                                r_dict["Weight"] = round(r_dict["Weight"] * (scale ** 2), 5)
                        cur.execute(f"INSERT INTO SetNutsBolts ({col_str}) VALUES ({placeholders})", [r_dict[c] for c in cols])
                inserted_counts["SetNutsBolts"] = len(src_rows)

            # AnchorsName and children
            if "AnchorsName" in tables and (include_tables is None or "AnchorsName" in include_tables):
                cur.execute("SELECT * FROM AnchorsName WHERE Diameter = %s", (source_dia,))
                src_anchors = cur.fetchall()
                total_anchors = 0
                total_defs = 0
                total_holes = 0

                is_an_identity = is_identity_column(database, "AnchorsName", "ID")
                is_ad_identity = is_identity_column(database, "AnchorsDefinition", "ID") if "AnchorsDefinition" in tables else False
                is_ah_identity = is_identity_column(database, "AnchorsHoleDefinition", "ID") if "AnchorsHoleDefinition" in tables else False

                for ar in src_anchors:
                    old_id = ar["ID"]
                    ar_dict = dict(ar)
                    ar_dict["Diameter"] = target_dia
                    for i in range(1, 7):
                        if f"Diameter{i}" in ar_dict and ar_dict[f"Diameter{i}"] is not None and abs(ar_dict[f"Diameter{i}"] - source_dia) < 0.001:
                            ar_dict[f"Diameter{i}"] = target_dia

                    if is_an_identity:
                        cols = [c for c in ar_dict.keys() if c != "ID"]
                        col_str = ", ".join(f"[{c}]" for c in cols)
                        placeholders = ", ".join(["%s"] * len(cols))
                        cur.execute(f"INSERT INTO AnchorsName ({col_str}) VALUES ({placeholders}); SELECT SCOPE_IDENTITY() AS new_id;", [ar_dict[c] for c in cols])
                        new_id = cur.fetchone()["new_id"]
                    else:
                        cur.execute("SELECT MAX(ID) AS max_id FROM AnchorsName")
                        new_id = (cur.fetchone()["max_id"] or 0) + 1
                        ar_dict["ID"] = new_id
                        cols = list(ar_dict.keys())
                        col_str = ", ".join(f"[{c}]" for c in cols)
                        placeholders = ", ".join(["%s"] * len(cols))
                        cur.execute(f"INSERT INTO AnchorsName ({col_str}) VALUES ({placeholders})", [ar_dict[c] for c in cols])
                    total_anchors += 1

                    # AnchorsDefinition
                    if "AnchorsDefinition" in tables:
                        cur.execute("SELECT * FROM AnchorsDefinition WHERE AnchorID = %s", (old_id,))
                        defs = cur.fetchall()
                        for dr in defs:
                            dr_dict = dict(dr)
                            dr_dict["AnchorID"] = new_id
                            if dr_dict.get("PartName"):
                                dr_dict["PartName"] = smart_replace_name(dr_dict["PartName"], replace_from, replace_to)
                            if scale_dimensions:
                                if dr_dict.get("HeadDiameter"):
                                    dr_dict["HeadDiameter"] = round(dr_dict["HeadDiameter"] * scale, 4)
                                if dr_dict.get("HeadHeight"):
                                    dr_dict["HeadHeight"] = round(dr_dict["HeadHeight"] * scale, 4)
                                if dr_dict.get("Weight"):
                                    dr_dict["Weight"] = round(dr_dict["Weight"] * (scale ** 2), 5)

                            if is_ad_identity:
                                d_cols = [c for c in dr_dict.keys() if c != "ID"]
                                d_col_str = ", ".join(f"[{c}]" for c in d_cols)
                                d_placeholders = ", ".join(["%s"] * len(d_cols))
                                cur.execute(f"INSERT INTO AnchorsDefinition ({d_col_str}) VALUES ({d_placeholders})", [dr_dict[c] for c in d_cols])
                            else:
                                cur.execute("SELECT MAX(ID) AS max_id FROM AnchorsDefinition")
                                d_new_id = (cur.fetchone()["max_id"] or 0) + 1
                                dr_dict["ID"] = d_new_id
                                d_cols = list(dr_dict.keys())
                                d_col_str = ", ".join(f"[{c}]" for c in d_cols)
                                d_placeholders = ", ".join(["%s"] * len(d_cols))
                                cur.execute(f"INSERT INTO AnchorsDefinition ({d_col_str}) VALUES ({d_placeholders})", [dr_dict[c] for c in d_cols])
                            total_defs += 1

                    # AnchorsHoleDefinition
                    if "AnchorsHoleDefinition" in tables:
                        cur.execute("SELECT * FROM AnchorsHoleDefinition WHERE AnchorNameID = %s", (old_id,))
                        holes = cur.fetchall()
                        for hr in holes:
                            hr_dict = dict(hr)
                            hr_dict["AnchorNameID"] = new_id
                            if scale_dimensions and hr_dict.get("HeadDiameter"):
                                hr_dict["HeadDiameter"] = round(hr_dict["HeadDiameter"] * scale, 4)

                            if is_ah_identity:
                                h_cols = [c for c in hr_dict.keys() if c != "ID"]
                                h_col_str = ", ".join(f"[{c}]" for c in h_cols)
                                h_placeholders = ", ".join(["%s"] * len(h_cols))
                                cur.execute(f"INSERT INTO AnchorsHoleDefinition ({h_col_str}) VALUES ({h_placeholders})", [hr_dict[c] for c in h_cols])
                            else:
                                cur.execute("SELECT MAX(ID) AS max_id FROM AnchorsHoleDefinition")
                                h_new_id = (cur.fetchone()["max_id"] or 0) + 1
                                hr_dict["ID"] = h_new_id
                                h_cols = list(hr_dict.keys())
                                h_col_str = ", ".join(f"[{c}]" for c in h_cols)
                                h_placeholders = ", ".join(["%s"] * len(h_cols))
                                cur.execute(f"INSERT INTO AnchorsHoleDefinition ({h_col_str}) VALUES ({h_placeholders})", [hr_dict[c] for c in h_cols])
                            total_holes += 1

                inserted_counts["AnchorsName"] = total_anchors
                if "AnchorsDefinition" in tables:
                    inserted_counts["AnchorsDefinition"] = total_defs
                if "AnchorsHoleDefinition" in tables:
                    inserted_counts["AnchorsHoleDefinition"] = total_holes

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

    return inserted_counts
