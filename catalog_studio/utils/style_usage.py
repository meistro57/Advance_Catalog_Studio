# utils/style_usage.py
"""Read-only "used by" and orphan analysis for drawing-style exports.

Two questions the Style Manager cannot answer:

- **Who uses this shared record?** An appearance, label strategy, qualifier set
  or dimension setup is a library row. Editing it changes every style that
  points at it, and the export renumbers every key into one range so the link is
  easy to miss. This module walks up the containment chain from the selected
  row and reports every `DetailStyle` that depends on it, with the chain.
- **Which rows does no drawing style reach?** Rows in the style tables that no
  path from a `DetailStyle` reaches are dead weight in the export (superseded
  rules, library entries used only by another library). They are listed for
  review only.

The chain is declared in `ASCENT_EDGES` below, from the verified export shape
(`docs/drawing-style-schema.md`), because `InfoTableRelations` states every
reference but not which side contains which. Every edge means: *a row of the
child table is reached from a row of the parent table whose `parent_column`
equals the child row's `child_column`*. Editions of Advance Steel that rename
tables simply miss edges instead of producing wrong ones, and nothing is
inferred from name similarity.

The attached specification names `DetStyle`, `DetStyleViews`, `DetView`,
`DetDimStrategy`, `DetObjectsSet`, `DetDimDefinition` and `DetDimPoints`; none of
those exist in an Advance Steel 2026 export. The observed names are
`DetailStyle`, `DetViewRequest`, `DetObjReprMapsNew`/`DetObjReprMapItems`,
`DetViewDimStrategyNew`/`DetViewDimStrategyItems`,
`DetViewDimRequestLinear` and `DetViewDimPointSelection`, which is what this
chain uses.

Everything here is read-only: nothing is deleted, deduplicated, purged,
compacted or rewritten.
"""

from collections import defaultdict

from utils import db as dbcore

ROW_LIMIT = 5000
MAX_DEPTH = 12
MAX_PATHS = 400
CANDIDATE_LIMIT = 300

STYLE_TABLE = "DetailStyle"
ROOT_TABLES = ("DetailStyle", "DetailMasterTable")
LABEL_COLUMNS = ("RunName", "Description", "Name", "PartName")
NULL_REFS = {None, 0, -1, "", "0", "-1"}

# (child_table, child_column, parent_table, parent_column)
# "A child row is reached from a parent row whose parent_column equals the
# child's child_column."  Verified against the sample exports: the child column
# may hold the row's own identity (a shared appearance's Key, looked up in the
# rules that use it) or a foreign key (a view request's ObjReprMap).
ASCENT_EDGES = [
    # view requests belong to a style (Request1..Request10)
    *[(("DetViewRequest"), "Key", STYLE_TABLE, f"Request{i}") for i in range(1, 11)],
    ("DetViewRequestCategories", "DetViewRequest", "DetViewRequest", "Key"),
    ("DetViewSystemAndBox", "Key", "DetViewRequest", "SystemAndBox"),
    ("DetViewLengthClip", "Key", "DetViewRequest", "LengthclipXY"),
    ("DetObjReprMapsNew", "Key", "DetViewRequest", "ObjReprMap"),
    ("DetViewDimStrategyNew", "Key", "DetViewRequest", "DimStrategy"),
    # representation rules share their map's Key; Appearance etc. are lookups
    ("DetObjReprMapItems", "Key", "DetObjReprMapsNew", "Key"),
    ("DetObjAppearance", "Key", "DetObjReprMapItems", "Appearance"),
    ("DetObjAnnotationStrategy", "Key", "DetObjReprMapItems", "AnnotationStrategy"),
    ("DetObjQualifierSet", "Key", "DetObjReprMapItems", "ObjQualifier"),
    ("Linetypes", "Key", "DetObjReprMapItems", "LineType"),
    # annotation strategies point at the label formula and arrangement
    ("DetAnnotationType", "Key", "DetObjAnnotationStrategy", "AnnotationType"),
    ("DetArrangerStrategy", "Key", "DetObjAnnotationStrategy", "ArrangerStrategy"),
    ("DetObjAnnotationGroup", "Key", "DetObjAnnotationStrategy", "Group"),
    # appearances point at hatch and grid settings
    ("DetHatchSettings", "Key", "DetObjAppearance", "HatchVisible"),
    ("DetHatchSettings", "Key", "DetObjAppearance", "HatchHidden"),
    ("DetGridReferenceSettings", "Key", "DetObjAppearance", "GridReference"),
    # qualifier sets
    ("DetObjQualifierSetGroup", "Key", "DetObjQualifierSet", "Group"),
    ("DetObjQualifierSetItem", "IdDetObjQualifierSet", "DetObjQualifierSet", "Key"),
    # dimension strategy chain
    ("DetViewDimStrategyItems", "Key", "DetViewDimStrategyNew", "Key"),
    ("DetViewDimRequestLinear", "Key", "DetViewDimStrategyItems", "RequestLinear"),
    *[(("DetViewDimPointSelection"), "Key", "DetViewDimRequestLinear", f"Point{i}")
      for i in range(1, 16)],
    ("DetObjQualifierSet", "Key", "DetViewDimPointSelection", "Objects"),
    # detail processes and style map
    ("DetailStyle", "Key", "DetailMasterTable", "StyleKey"),
    ("DetailStyleMapItems", "DetailStyle", "DetailStyle", "Key"),
    ("DetailStyleMapNew", "Key", "DetailStyleMapItems", "Key"),
    ("DetObjQualifierSet", "Key", "DetailStyleMapItems", "ObjQualifierSet"),
    ("DetailStyleMapNew", "Key", "DetailProcessStep", "StyleMap"),
    ("DetailFilenameSelector", "Key", "DetailProcessStep", "FilenameSelector"),
    *[(("DetailProcessStep"), "Key", "DetailProcessDefinition", f"Step{i}")
      for i in range(1, 8)],
    # picker categories
    ("DetBaseCategories", "Key", "DetailMasterTable", "BaseCategory"),
    ("DetViewArrangeStrategy", "Key", STYLE_TABLE, "ViewArrangeStrategy"),
]

# --------------------------------------------------------------------------
# Index helpers
# --------------------------------------------------------------------------

def node(table, row, pk_by_table):
    """Stable identity for a row: (table, primary-key values)."""
    pk = pk_by_table.get(table) or []
    return (table, tuple(row.get(column) for column in pk))


def same_value(left, right):
    """Tolerant comparison for key values coming from tokens (strings) and SQL."""
    if left == right:
        return True
    if left is None or right is None:
        return False
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return str(left) == str(right)


def row_label(row, table=None):
    """Human label: a name column first, then the key columns."""
    for column in LABEL_COLUMNS:
        value = row.get(column)
        if value is not None and str(value).strip():
            return str(value).strip()
    parts = []
    for column in ("Key", "Order", "ID"):
        value = row.get(column)
        if value is not None and value not in NULL_REFS:
            parts.append(f"{column} {value}")
    text = ", ".join(parts)
    return f"{table} {text}".strip() if table else (text or "row")


def build_index(rows_by_table, tables_present=None):
    """{(table, column, value): [rows]} for every populated value."""
    index = defaultdict(list)
    for table, rows in rows_by_table.items():
        if tables_present is not None and table not in tables_present:
            continue
        for row in rows or []:
            for column, value in row.items():
                if value is None or value in NULL_REFS:
                    continue
                index[(table, column, value)].append(row)
    return index


def edge_tables(edges=None):
    tables = set()
    for child_table, _child_column, parent_table, _parent_column in edges or ASCENT_EDGES:
        tables.add(child_table)
        tables.add(parent_table)
    return tables


# --------------------------------------------------------------------------
# Upward walk
# --------------------------------------------------------------------------

def parent_links(table, row, index, edges=None):
    """Rows that reach this row: [(parent_table, parent_row, via_column)]."""
    links = []
    for child_table, child_column, parent_table, parent_column in edges or ASCENT_EDGES:
        if child_table != table:
            continue
        value = row.get(child_column)
        if value is None or value in NULL_REFS:
            continue
        for parent in index.get((parent_table, parent_column, value), []):
            if parent is not row:
                links.append((parent_table, parent, child_column))
    return links


def child_links(table, row, index, edges=None):
    """Rows this row reaches (the inverse of parent_links)."""
    links = []
    for child_table, child_column, parent_table, parent_column in edges or ASCENT_EDGES:
        if parent_table != table:
            continue
        value = row.get(parent_column)
        if value is None or value in NULL_REFS:
            continue
        for child in index.get((child_table, child_column, value), []):
            if child is not row:
                links.append((child_table, child, parent_column))
    return links


def usage(rows_by_table, pk_by_table, table, pk_values, edges=None,
          tables_present=None, max_depth=MAX_DEPTH, max_paths=MAX_PATHS):
    """Report the drawing styles that depend on one row."""
    index = build_index(rows_by_table, tables_present)
    pk_columns = pk_by_table.get(table) or []

    matches = [r for r in rows_by_table.get(table) or []
               if all(same_value(r.get(c), v) for c, v in zip(pk_columns, pk_values))]
    if not matches:
        return {"ok": False,
                "error": "No row in that table matches the selected record.",
                "record": None, "styles": [], "direct": [], "truncated": False}
    start = matches[0]
    record = {
        "table": table,
        "label": row_label(start, table),
        "pk": {c: start.get(c) for c in pk_columns},
    }

    visited = {node(table, start, pk_by_table)}
    styles = {}
    direct = {}
    truncated = False
    queue = [(table, start, [])]

    while queue and not truncated:
        current_table, current_row, path = queue.pop(0)
        if len(path) >= max_depth:
            truncated = True
            break
        for parent_table, parent, via in parent_links(current_table, current_row,
                                                      index, edges):
            step = {
                "table": parent_table,
                "column": via,
                "label": row_label(parent, parent_table),
            }
            direct.setdefault(parent_table, set()).add(step["label"])
            new_path = path + [step]
            if parent_table == STYLE_TABLE:
                key = parent.get("Key")
                if key not in styles or len(new_path) < len(styles[key]["path"]):
                    styles[key] = {
                        "key": key,
                        "name": row_label(parent, parent_table),
                        "owner": parent.get("OwnerText"),
                        "path": new_path,
                    }
                continue
            ident = node(parent_table, parent, pk_by_table)
            if ident in visited:
                continue
            visited.add(ident)
            if len(visited) > max_paths:
                truncated = True
                break
            queue.append((parent_table, parent, new_path))
        if truncated:
            break

    masters = {}
    for row in rows_by_table.get("DetailMasterTable") or []:
        masters.setdefault(row.get("StyleKey"), row)
    results = []
    for key, style in styles.items():
        master = masters.get(key) or {}
        results.append({
            **style,
            "master_name": row_label(master, "DetailMasterTable") if master else None,
            "categories": {
                "base": master.get("BaseCategory"),
                "sub": master.get("SubCategory"),
            },
        })

    return {
        "ok": True,
        "record": record,
        "styles": sorted(results, key=lambda s: (str(s.get("name") or ""), str(s.get("key")))),
        "direct": [
            {"table": t, "labels": sorted(labels)}
            for t, labels in sorted(direct.items())
        ],
        "truncated": truncated,
    }


# --------------------------------------------------------------------------
# Reachability / orphan scan
# --------------------------------------------------------------------------

def reachable_nodes(rows_by_table, pk_by_table, edges=None, tables_present=None):
    """Every row reachable downwards from a DetailStyle row."""
    index = build_index(rows_by_table, tables_present)
    seen = set()
    queue = []
    for root_table in (STYLE_TABLE, "DetailMasterTable"):
        for row in rows_by_table.get(root_table) or []:
            ident = node(root_table, row, pk_by_table)
            if ident not in seen:
                seen.add(ident)
                queue.append((root_table, row))
    while queue:
        table, row = queue.pop()
        for child_table, child, _via in child_links(table, row, index, edges):
            ident = node(child_table, child, pk_by_table)
            if ident in seen:
                continue
            seen.add(ident)
            queue.append((child_table, child))
    return seen


def orphan_report(rows_by_table, pk_by_table, edges=None, tables_present=None,
                  sample=5):
    """Rows in the style tables that no path from a DetailStyle reaches."""
    edges = edges or ASCENT_EDGES
    reachable = reachable_nodes(rows_by_table, pk_by_table, edges, tables_present)
    used_by = defaultdict(set)
    for child_table, child_column, parent_table, parent_column in edges:
        used_by[child_table].add(f"{parent_table}.{parent_column}")

    tables = []
    total = 0
    for table in sorted(rows_by_table):
        if table in ROOT_TABLES:
            continue
        rows = rows_by_table.get(table) or []
        if not rows:
            continue
        misses = [r for r in rows if node(table, r, pk_by_table) not in reachable]
        if not misses:
            continue
        total += len(misses)
        tables.append({
            "table": table,
            "reached_from": sorted(used_by.get(table, [])),
            "rows": len(rows),
            "unreferenced": len(misses),
            "samples": [{"label": row_label(row, table)} for row in misses[:sample]],
        })
    return {"tables": tables, "total": total}


# --------------------------------------------------------------------------
# Catalog reading (read-only)
# --------------------------------------------------------------------------

def _rows(database, table):
    if table not in set(dbcore.list_tables(database)):
        return []
    return dbcore.get_rows(database, table, limit=ROW_LIMIT)


def load_graph(database):
    """Rows and primary keys for every table the chain touches."""
    tables_present = set(dbcore.list_tables(database))
    tables = sorted(edge_tables() & tables_present)
    rows_by_table = {t: _rows(database, t) for t in tables}
    pk_by_table = {t: dbcore.get_primary_key_columns(database, t) for t in tables}
    return {
        "tables_present": tables_present,
        "rows_by_table": rows_by_table,
        "pk_by_table": pk_by_table,
    }


def build_page_model(database, table=None, token=None):
    """Everything the usage page needs for one database."""
    graph = load_graph(database)
    rows_by_table = graph["rows_by_table"]
    pk_by_table = graph["pk_by_table"]
    tables_present = graph["tables_present"]

    index = build_index(rows_by_table, tables_present)
    shared_tables = sorted({
        child_table for child_table, _c, _p, _pc in ASCENT_EDGES
        if child_table not in ROOT_TABLES and rows_by_table.get(child_table)
    })

    candidates = []
    if table in shared_tables:
        pk_columns = pk_by_table.get(table) or []
        for row in rows_by_table.get(table) or []:
            if not pk_columns:
                continue
            parents = parent_links(table, row, index)
            if not parents:
                continue
            candidates.append({
                "label": row_label(row, table),
                "token": dbcore.make_row_token(row, pk_columns),
                "references": len(parents),
            })
        candidates.sort(key=lambda c: (-c["references"], c["label"]))
        candidates = candidates[:CANDIDATE_LIMIT]

    report = None
    if table and token:
        pk_columns = pk_by_table.get(table) or []
        try:
            pk_values = dbcore.parse_row_token(token, pk_columns)
        except Exception:
            pk_values = None
        if pk_columns and pk_values is not None:
            report = usage(
                rows_by_table, pk_by_table, table,
                [pk_values[c] for c in pk_columns],
                tables_present=tables_present,
            )
        else:
            report = {"ok": False, "record": None, "styles": [], "direct": [],
                      "truncated": False,
                      "error": "That record token could not be decoded."}

    return {
        "database": database,
        "orphans": orphan_report(rows_by_table, pk_by_table,
                                 tables_present=tables_present),
        "shared_tables": shared_tables,
        "selected_table": table if table in shared_tables else None,
        "candidates": candidates,
        "selected_token": token,
        "report": report,
        "row_limit": ROW_LIMIT,
        "truncated_rows": [t for t, rows in rows_by_table.items() if len(rows) >= ROW_LIMIT],
    }
