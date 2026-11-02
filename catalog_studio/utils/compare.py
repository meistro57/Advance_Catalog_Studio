# utils/compare.py
"""Read-only side-by-side comparison of two attached catalogs.

Answers "which tables and diameters differ between these two databases?" for
before/after exports, a repaired copy against the original, or two versions of
the same library. It only reads: no row is changed, no schema is assumed.

The pure helpers (`table_diff`, `count_diff`, `diameter_diff`, `summary`) take
already-loaded rows so they can be unit-tested without SQL Server;
`build_comparison` is the only function that touches the database and it goes
through `utils.db` like everything else.
"""

from utils import db as dbcore


def table_diff(tables_a, tables_b):
    """Split two table-name lists into shared / only-a / only-b."""
    first, second = set(tables_a), set(tables_b)
    return {
        "shared": sorted(first & second),
        "only_a": sorted(first - second),
        "only_b": sorted(second - first),
    }


def count_diff(tables_a, counts_a, tables_b, counts_b):
    """Per-table row counts for both sides, plus the delta where both exist."""
    diff = table_diff(tables_a, tables_b)
    rows = []
    for table in diff["shared"]:
        a_count = counts_a.get(table, 0)
        b_count = counts_b.get(table, 0)
        rows.append({
            "table": table,
            "a": a_count,
            "b": b_count,
            "delta": b_count - a_count,
            "present": "both",
        })
    for table in diff["only_a"]:
        rows.append({"table": table, "a": counts_a.get(table, 0), "b": None,
                     "delta": None, "present": "a"})
    for table in diff["only_b"]:
        rows.append({"table": table, "a": None, "b": counts_b.get(table, 0),
                     "delta": None, "present": "b"})
    return rows


def _diameter_index(diameters):
    index = {}
    for item in diameters or []:
        try:
            key = round(float(item.get("key")), 6)
        except (TypeError, ValueError):
            continue
        index[key] = item
    return index


def diameter_diff(diameters_a, diameters_b):
    """Compare two `get_catalog_diameters()` lists by diameter key."""
    first = _diameter_index(diameters_a)
    second = _diameter_index(diameters_b)
    rows = []
    for key in sorted(set(first) | set(second)):
        a_item = first.get(key)
        b_item = second.get(key)
        rows.append({
            "key": key,
            "name_a": (a_item or {}).get("run_name"),
            "name_b": (b_item or {}).get("run_name"),
            "records_a": (a_item or {}).get("total_related"),
            "records_b": (b_item or {}).get("total_related"),
            "orphan_a": bool((a_item or {}).get("is_orphan")),
            "orphan_b": bool((b_item or {}).get("is_orphan")),
            "present": "both" if a_item and b_item else ("a" if a_item else "b"),
        })
    return rows


def summary(count_rows, diameter_rows):
    """Counts used by the page header."""
    return {
        "tables_shared": sum(1 for r in count_rows if r["present"] == "both"),
        "tables_only_a": sum(1 for r in count_rows if r["present"] == "a"),
        "tables_only_b": sum(1 for r in count_rows if r["present"] == "b"),
        "tables_changed": sum(
            1 for r in count_rows
            if r["present"] == "both" and r["delta"]
        ),
        "diameters_both": sum(1 for r in diameter_rows if r["present"] == "both"),
        "diameters_only_a": sum(1 for r in diameter_rows if r["present"] == "a"),
        "diameters_only_b": sum(1 for r in diameter_rows if r["present"] == "b"),
    }


def _safe_diameters(database):
    try:
        return dbcore.get_catalog_diameters(database)
    except Exception:
        return []


def build_comparison(database_a, database_b):
    """Load both databases and pair them up. Read-only."""
    tables_a = dbcore.list_tables(database_a)
    tables_b = dbcore.list_tables(database_b)
    counts_a = {t: dbcore.get_row_count(database_a, t) for t in tables_a}
    counts_b = {t: dbcore.get_row_count(database_b, t) for t in tables_b}
    try:
        type_a = dbcore.guess_catalog_type(database_a)
    except Exception:
        type_a = None
    try:
        type_b = dbcore.guess_catalog_type(database_b)
    except Exception:
        type_b = None

    diameter_rows = diameter_diff(_safe_diameters(database_a), _safe_diameters(database_b))
    count_rows = count_diff(tables_a, counts_a, tables_b, counts_b)
    return {
        "a": {
            "database": database_a,
            "catalog_type": type_a,
            "tables": len(tables_a),
            "rows": sum(counts_a.values()),
        },
        "b": {
            "database": database_b,
            "catalog_type": type_b,
            "tables": len(tables_b),
            "rows": sum(counts_b.values()),
        },
        "tables": count_rows,
        "diameters": diameter_rows,
        "summary": summary(count_rows, diameter_rows),
    }
