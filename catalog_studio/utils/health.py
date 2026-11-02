# utils/health.py
"""Read-only catalog health report.

Aggregates checks that already live (and are already verified) in the per-type
modules, so one page answers "what is wrong with this database?" without
adding new catalog semantics:

- **bolt** catalogs: orphan diameters and missing related rows, using the
  documented six-table relationship and `db.get_catalog_diameters()` counts;
- **anchor** catalogs: names/definitions that do not pair up, hardware slots
  that resolve to no `SetNutsBolts` record (the same matcher the configurator
  uses), and thread/length sanity;
- **shear-stud** catalogs: the issue list from `shear_studs.get_browser_model`;
- **drawing-style** exports: `drawing_styles.integrity_report` (dangling
  in-file references plus structural notes).

Nothing here writes, repairs or guesses. Findings are reported with the
severity the originating module chose; this module only groups and counts
them. Any rule that is product- or standard-specific stays in its module.
"""

from collections import defaultdict

from utils import bolt_sets as bs
from utils import db as dbcore
from utils import drawing_styles
from utils import shear_studs

ROW_LIMIT = 5000

AREAS = [
    ("structure", "Catalog structure"),
    ("diameters", "Diameters"),
    ("hardware", "Hardware links"),
    ("geometry", "Geometry"),
    ("integrity", "References"),
]

# Documented bolt relationship (README "The six-table bolt relationship").
BOLT_RELATED_TABLES = [
    "BoltsDiameters",
    "BoltsDistances",
    "ScrewNew",
    "SetOfBolts",
    "SetNutsBolts",
    "SetBolts",
]

ANCHOR_TABLES = ["AnchorsName", "AnchorsDefinition", "SetNutsBolts"]

SEVERITY_RANK = {"error": 0, "warn": 1, "info": 2}


def finding(severity, code, message, table=None, area="structure", context=None):
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "table": table,
        "area": area,
        "context": context or {},
    }


def sort_findings(findings):
    """Errors first, then warnings and notes, each in a stable area order."""
    order = {name: index for index, (name, _) in enumerate(AREAS)}
    return sorted(
        findings,
        key=lambda f: (SEVERITY_RANK.get(f["severity"], 3), order.get(f["area"], 99)),
    )


def summarize(findings):
    summary = {"errors": 0, "warnings": 0, "notes": 0, "total": len(findings)}
    for item in findings:
        if item["severity"] == "error":
            summary["errors"] += 1
        elif item["severity"] == "warn":
            summary["warnings"] += 1
        else:
            summary["notes"] += 1
    return summary


def sections(findings):
    """Group sorted findings by area, preserving the AREAS order."""
    grouped = defaultdict(list)
    for item in findings:
        grouped[item["area"]].append(item)
    return [
        {"area": area, "title": title, "findings": grouped[area]}
        for area, title in AREAS
        if grouped[area]
    ]


# --------------------------------------------------------------------------
# Bolt catalogs
# --------------------------------------------------------------------------

def bolt_findings(diameters, tables):
    """Diameter coverage across the documented related tables."""
    findings = []
    present = [t for t in BOLT_RELATED_TABLES if t in tables]
    if "BoltsDiameters" not in tables:
        findings.append(finding(
            "error", "bolts_diameters_missing",
            "This bolt catalog has no BoltsDiameters table, so Advance Steel has "
            "no diameter names to show.",
            "BoltsDiameters", "structure",
        ))
        return findings
    if not diameters:
        findings.append(finding(
            "error", "no_diameters",
            "BoltsDiameters is empty; the catalog offers no bolt sizes.",
            "BoltsDiameters", "structure",
        ))
        return findings

    for item in diameters:
        key = item.get("key")
        label = (item.get("run_name") or "").strip() or f"{key} mm"
        counts = item.get("counts") or {}
        if item.get("is_orphan"):
            findings.append(finding(
                "error", "diameter_orphan",
                f"Diameter {label} ({shear_studs.number_text(key)} mm) has no related "
                f"rows at all: no bolts, sets, nuts/washers or length rules.",
                "BoltsDiameters", "diameters", {"diameter": key},
            ))
            continue
        missing = [t for t in present if t not in counts and t != "BoltsDiameters"]
        if missing:
            findings.append(finding(
                "warn", "diameter_incomplete",
                f"Diameter {label} ({shear_studs.number_text(key)} mm) has no "
                f"rows in {', '.join(missing)}; Advance Steel may list the size "
                f"but fail to build or length it.",
                "BoltsDiameters", "diameters",
                {"diameter": key, "missing": missing},
            ))
    return findings


# --------------------------------------------------------------------------
# Anchor catalogs
# --------------------------------------------------------------------------

def _anchor_label(row):
    standard = row.get("Standard") or "anchor"
    diameter = shear_studs.number_text(row.get("Diameter"))
    set_name = row.get("SetName")
    parts = [str(standard)]
    if diameter:
        parts.append(f"{diameter} mm")
    if set_name:
        parts.append(f"set {set_name}")
    return " / ".join(parts)


def anchor_findings(names, definitions, nut_rows, tables=None):
    """Name/definition pairing, hardware resolution and thread/length sanity."""
    findings = []
    tables = set(tables or [])
    missing_tables = [t for t in ANCHOR_TABLES if tables and t not in tables]
    if missing_tables:
        findings.append(finding(
            "error", "anchor_tables_missing",
            f"This anchor catalog is missing {', '.join(missing_tables)}.",
            None, "structure",
        ))
        return findings

    names_by_id = {}
    for row in names:
        names_by_id[row.get("ID")] = row
    definitions_by_anchor = defaultdict(list)
    for row in definitions:
        definitions_by_anchor[row.get("AnchorID")].append(row)

    if not names:
        findings.append(finding(
            "error", "no_anchors",
            "AnchorsName is empty; the catalog offers no anchor records.",
            "AnchorsName", "structure",
        ))
    for row in names:
        label = _anchor_label(row)
        anchor_id = row.get("ID")
        diameter = shear_studs.to_float(row.get("Diameter"))
        if diameter is None or diameter <= 0:
            findings.append(finding(
                "error", "anchor_diameter_missing",
                f"Anchor {label} (ID {anchor_id}) has no positive diameter.",
                "AnchorsName", "geometry", {"anchor_id": anchor_id},
            ))
        if not definitions_by_anchor.get(anchor_id):
            findings.append(finding(
                "error", "anchor_without_length",
                f"Anchor {label} (ID {anchor_id}) has no AnchorsDefinition rows, so "
                f"Advance Steel has no length variants to place.",
                "AnchorsDefinition", "structure", {"anchor_id": anchor_id},
            ))
    for row in definitions:
        anchor_id = row.get("AnchorID")
        if anchor_id not in names_by_id:
            findings.append(finding(
                "error", "definition_orphan",
                f"AnchorsDefinition ID {row.get('ID')} points at anchor {anchor_id}, "
                f"which does not exist in AnchorsName.",
                "AnchorsDefinition", "structure", {"anchor_id": anchor_id},
            ))

    for row in names:
        anchor_id = row.get("ID")
        slots = bs.parse_component_slots(row, diameter_suffix="")
        if not slots:
            continue
        components = bs.annotate_components(slots, nut_rows)
        for part in components:
            if part["matched"]:
                continue
            findings.append(finding(
                "error", "unmatched_component",
                f"Anchor {_anchor_label(row)} (ID {anchor_id}) slot DIN{part['slot']} "
                f"({part['din']}) has no matching SetNutsBolts record.",
                "SetNutsBolts", "hardware",
                {"anchor_id": anchor_id, "slot": part["slot"]},
            ))

    for row in definitions:
        length = shear_studs.to_float(row.get("Length"))
        thread = shear_studs.to_float(row.get("ThreadLength"))
        label = f"ID {row.get('ID')}"
        if length is None or length <= 0:
            findings.append(finding(
                "error", "invalid_length",
                f"AnchorsDefinition {label} has no positive Length.",
                "AnchorsDefinition", "geometry", {"definition_id": row.get("ID")},
            ))
        if thread and length and thread > length:
            findings.append(finding(
                "error", "thread_exceeds_length",
                f"AnchorsDefinition {label} has ThreadLength {shear_studs.number_text(thread)} mm "
                f"longer than its Length {shear_studs.number_text(length)} mm.",
                "AnchorsDefinition", "geometry", {"definition_id": row.get("ID")},
            ))
    return findings


# --------------------------------------------------------------------------
# Shear-stud catalogs
# --------------------------------------------------------------------------

STUD_AREA_BY_TABLE = {
    "SetBolts": "hardware",
    "ConnectorDistances": "geometry",
}


def stud_findings(model):
    """Pass through the shear-stud model's own error/warning/note list."""
    findings = []
    for item in model.get("issues", []):
        table = item.get("table")
        findings.append(finding(
            item["severity"], item["code"],
            item["message"],
            table,
            STUD_AREA_BY_TABLE.get(table, "diameters"),
            item.get("context"),
        ))
    if not model.get("groups"):
        findings.append(finding(
            "error", "no_connector_families",
            "No ConnectorRelations or SetBolts stud rows were found.",
            None, "structure",
        ))
    return findings


# --------------------------------------------------------------------------
# Drawing-style exports
# --------------------------------------------------------------------------

def drawing_style_findings(report):
    """Map `drawing_styles.integrity_report` onto findings."""
    findings = []
    for problem in report.get("dangling", []):
        missing = problem.get("missing") or []
        sample = ", ".join(str(v) for v in missing[:5])
        if len(missing) > 5:
            sample += f", … ({len(missing) - 5} more)"
        findings.append(finding(
            "error", "dangling_reference",
            f"{problem.get('table')}.{problem.get('column')} references "
            f"{problem.get('target')} but {len(missing)} key(s) do not exist in "
            f"the export (missing {sample}).",
            problem.get("table"), "integrity",
            {"target": problem.get("target")},
        ))
    for note in report.get("notes", []):
        findings.append(finding(
            "warn", "style_structure", note, "DetailStyle", "integrity",
        ))
    return findings


# --------------------------------------------------------------------------
# Report assembly (read-only)
# --------------------------------------------------------------------------

def _rows(database, table):
    if table not in set(dbcore.list_tables(database)):
        return []
    return dbcore.get_rows(database, table, limit=ROW_LIMIT)


def build_report(database):
    """Collect the checks for this database's detected catalog type."""
    tables = dbcore.list_tables(database)
    catalog_type = dbcore.guess_catalog_type(database)
    table_set = set(tables)
    counts = {t: dbcore.get_row_count(database, t) for t in tables}
    findings = []

    if catalog_type == "bolt":
        findings.extend(bolt_findings(dbcore.get_catalog_diameters(database), table_set))
    elif catalog_type == "anchor":
        names = _rows(database, "AnchorsName")
        definitions = _rows(database, "AnchorsDefinition")
        nut_rows = _rows(database, "SetNutsBolts")
        findings.extend(anchor_findings(
            names=names,
            definitions=definitions,
            nut_rows=nut_rows,
            tables=table_set,
        ))
        for table, rows in (("AnchorsName", names),
                            ("AnchorsDefinition", definitions),
                            ("SetNutsBolts", nut_rows)):
            if len(rows) >= ROW_LIMIT:
                findings.append(finding(
                    "info", "truncated_check",
                    f"{table} has {counts.get(table, 0)} rows; only the first "
                    f"{ROW_LIMIT} were checked.",
                    table, "structure",
                ))
    elif catalog_type == "shear stud":
        findings.extend(stud_findings(shear_studs.get_browser_model(database)))
    elif catalog_type == "drawing style":
        findings.extend(drawing_style_findings(drawing_styles.integrity_report(database)))
    else:
        findings.append(finding(
            "error", "unknown_catalog_type",
            "The database does not match any known catalog shape (bolt, anchor, "
            "shear stud or drawing style export).",
            None, "structure",
        ))

    findings = sort_findings(findings)
    return {
        "database": database,
        "catalog_type": catalog_type,
        "tables": [{"name": t, "rows": counts[t]} for t in tables],
        "findings": findings,
        "summary": summarize(findings),
        "sections": sections(findings),
    }
