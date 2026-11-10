# utils/shear_studs.py
"""Read-only shear-stud (connector) browser model.

Issue #4, first slice: normalize and validate an attached connector catalog
without writing to it. The shape it expects is documented in
`docs/shear-stud-schema.md` and is OBSERVED from the Nelson H4L export only:

- `ConnectorStandard` / `ConnectorMaterial` are the family and grade lookups;
- `ConnectorDiameters` holds the shank diameters (mm `Key`);
- `ConnectorDistances` holds hole/spacing rules per diameter;
- `ConnectorRelations` links one (standard, material, diameter) triple;
- `SetBolts` holds the stud records themselves (reused bolt-shaped table).

Nothing here is verified against a live Advance Steel 2026 install, so the
field semantics stay OBSERVED. In particular `SetBolts.Type` is displayed but
never validated: whether it discriminates connectors from bolts is unconfirmed.

The normalized model is built by pure functions from row dicts so the mapping,
completeness rules and filtering are unit-tested without a database. The SQL
helpers at the bottom only read.
"""

import html
import math
import re
from collections import defaultdict
from urllib.parse import urlencode

from utils import db as dbcore
from utils import fabrication

CONNECTOR_STANDARD = "ConnectorStandard"
CONNECTOR_MATERIAL = "ConnectorMaterial"
CONNECTOR_DIAMETERS = "ConnectorDiameters"
CONNECTOR_DISTANCES = "ConnectorDistances"
CONNECTOR_RELATIONS = "ConnectorRelations"
STUDS = "SetBolts"

REQUIRED_TABLES = (
    CONNECTOR_STANDARD,
    CONNECTOR_MATERIAL,
    CONNECTOR_DIAMETERS,
    CONNECTOR_DISTANCES,
    CONNECTOR_RELATIONS,
    STUDS,
)

# Row limit for the read helpers. Connector catalogs are small (the Nelson
# export has 31 studs); this only guards against a runaway query.
ROW_LIMIT = 5000

_TOLERANCE = 1e-6
_METRIC_RUN_NAME = re.compile(r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?:mm)?\s*$", re.IGNORECASE)
_IMPERIAL_RUN_NAME = re.compile(
    r'^\s*(?:(?P<whole>\d+)\s+(?P<num>\d+)\s*/\s*(?P<den>\d+)'
    r'|(?P<fnum>\d+)\s*/\s*(?P<fden>\d+)'
    r'|(?P<only>\d+))\s*(?:in|inch|inches|")\s*$',
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Pure helpers: units, names, formatting
# --------------------------------------------------------------------------

def to_float(value):
    """Best-effort float conversion; returns None for blank/unparseable input."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value):
    number = to_float(value)
    return None if number is None else int(number)


def same_number(left, right):
    """Compare catalog numbers with a small tolerance (floats come from SQL)."""
    if left is None or right is None:
        return left is None and right is None
    return abs(float(left) - float(right)) <= _TOLERANCE


def number_text(value):
    """Millimetre value as it appears in stud names (6.0 -> '6', 12.5 -> '12.5')."""
    number = to_float(value)
    if number is None:
        return ""
    return f"{number:g}"


UNITS = ("mm", "in")


def normalize_units(value):
    """Display units for the browser: 'mm' (default) or 'in'."""
    text = str(value or "").strip().lower()
    return "in" if text in {"in", "inch", "inches", "imperial", '"'} else "mm"


def format_dimension(value_mm, units="mm"):
    """Display-only conversion; catalog values stay stored in millimetres.

    Imperial output reuses the fabrication sheet convention: nearest 1/16 in,
    reduced fraction, `≈` prefix when the millimetre value is not exactly
    representable at that denominator.
    """
    number = to_float(value_mm)
    if number is None:
        return "\u2014"
    if normalize_units(units) == "in":
        return f"{fabrication.format_in(number)} in"
    return f"{number_text(number)} mm"


def expected_stud_name(standard, diameter, length):
    """The observed name convention: '<family> <dia> x <length>' in millimetres."""
    return f"{str(standard or '').strip()} {number_text(diameter)} x {number_text(length)}".strip()


def expected_imperial_stud_name(standard, diameter, length):
    """Imperial stud name convention observed in Nelson H4L-Inch ('Nelson H4L 1/4 x 1 1/8')."""
    d_val = to_float(diameter)
    l_val = to_float(length)
    if d_val is None or l_val is None or d_val <= 0 or l_val <= 0:
        return ""
    d_in = fabrication.format_in(d_val).replace("≈", "").strip()
    l_in = fabrication.format_in(l_val).replace("≈", "").strip()
    std = re.sub(r"-Inch$", "", str(standard or "").strip(), flags=re.IGNORECASE).strip()
    return f"{std} {d_in} x {l_in}".strip()


def parse_metric_run_name(text):
    """Parse a metric diameter display string (' 10.00 mm', '16 mm', '6.0')."""
    if text is None:
        return None
    match = _METRIC_RUN_NAME.match(str(text))
    return float(match.group("value")) if match else None


def parse_imperial_run_name(text):
    """Parse an imperial diameter display string ('   1/4 inch', ' 1 1/4 inch') into mm."""
    if text is None:
        return None
    match = _IMPERIAL_RUN_NAME.match(str(text))
    if not match:
        return None
    if match.group("only") is not None:
        inches = float(match.group("only"))
    elif match.group("fnum") is not None:
        den = int(match.group("fden"))
        if den == 0:
            return None
        inches = int(match.group("fnum")) / den
    else:
        den = int(match.group("den"))
        if den == 0:
            return None
        inches = int(match.group("whole")) + (int(match.group("num")) / den)
    return inches * 25.4


def format_metric_run_name(diameter):
    """Canonical metric display string used when a name has to be generated.

    The samples are not whitespace-consistent (`' 10.00 mm'` next to
    `'   6.00 mm'`), so this produces the dominant form and
    `run_name_issue()` reports existing names that differ instead of
    rewriting them.
    """
    return f" {float(diameter):.2f} mm"


# --------------------------------------------------------------------------
# Pure helpers: issues
# --------------------------------------------------------------------------

def issue(severity, code, message, table, **context):
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "table": table,
        "context": context,
    }


def has_errors(issues):
    return any(i["severity"] == "error" for i in issues)


def run_name_issue(diameter_row):
    """Observation-only note when a stored RunName is not the canonical form."""
    key = to_float(diameter_row.get("Key"))
    run_name = diameter_row.get("RunName")
    if key is None or run_name is None:
        return None
    if str(run_name) == format_metric_run_name(key):
        return None
    parsed = parse_metric_run_name(run_name)
    if parsed is None:
        imp_mm = parse_imperial_run_name(run_name)
        if imp_mm is not None:
            if not same_number(imp_mm, key):
                return issue(
                    "error", "run_name_mismatch",
                    f"ConnectorDiameters.RunName {run_name!r} disagrees with Key {number_text(key)} mm.",
                    CONNECTOR_DIAMETERS, diameter=key, run_name=run_name,
                )
            return None
        return issue(
            "warn", "run_name_unparsed",
            f"ConnectorDiameters.RunName {run_name!r} is not a metric diameter string.",
            CONNECTOR_DIAMETERS, diameter=key, run_name=run_name,
        )
    if not same_number(parsed, key):
        return issue(
            "error", "run_name_mismatch",
            f"ConnectorDiameters.RunName {run_name!r} disagrees with Key {number_text(key)} mm.",
            CONNECTOR_DIAMETERS, diameter=key, run_name=run_name,
        )
    return issue(
        "info", "run_name_format",
        f"ConnectorDiameters.RunName {run_name!r} keeps non-canonical spacing "
        f"(canonical {format_metric_run_name(key)!r}); preserved as authored.",
        CONNECTOR_DIAMETERS, diameter=key, run_name=run_name,
    )


# --------------------------------------------------------------------------
# Pure helpers: normalized stud records
# --------------------------------------------------------------------------

def validate_stud(stud):
    """Issues for one normalized stud record. Never invents missing values."""
    issues = []
    diameter = stud.get("diameter")
    length = stud.get("length")
    head_diameter = stud.get("head_diameter")
    head_height = stud.get("head_height")
    weight = stud.get("weight")

    if diameter is None or diameter <= 0:
        issues.append(issue(
            "error", "invalid_diameter",
            "Stud diameter is missing or not positive.",
            STUDS, length=length,
        ))
    if length is None or length <= 0:
        issues.append(issue(
            "error", "invalid_length",
            "Stud length is missing or not positive.",
            STUDS, diameter=diameter,
        ))
    if head_diameter is not None and diameter and head_diameter <= diameter:
        issues.append(issue(
            "error", "head_not_larger",
            f"Head diameter {number_text(head_diameter)} mm is not larger than the "
            f"shank diameter {number_text(diameter)} mm.",
            STUDS, diameter=diameter, length=length,
        ))
    if head_height is not None and head_height <= 0:
        issues.append(issue(
            "warn", "head_height_missing",
            "Head height is present but not positive.",
            STUDS, diameter=diameter, length=length,
        ))
    if weight is not None and weight <= 0:
        issues.append(issue(
            "info", "weight_missing",
            "Stud weight is zero; mass properties will be empty in Advance Steel.",
            STUDS, diameter=diameter, length=length,
        ))
    elif (
        weight is not None
        and weight > 0
        and diameter is not None
        and diameter > 0
        and length is not None
        and length > 0
    ):
        shank_mass_kg = (math.pi / 4.0) * (diameter ** 2) * length * 7.85e-6
        ratio = weight / shank_mass_kg if shank_mass_kg > 0 else 1.0
        if ratio < 0.03 or ratio > 15.0:
            issues.append(issue(
                "warn", "weight_implausible",
                f"Stud weight {number_text(weight)} kg is outside the plausible "
                f"steel mass range for Ø{number_text(diameter)} × {number_text(length)} mm "
                f"(shank cylinder ≈ {shank_mass_kg:.4f} kg).",
                STUDS, diameter=diameter, length=length, weight=weight,
            ))
    expected = expected_stud_name(stud.get("standard"), diameter, length)
    expected_imp = expected_imperial_stud_name(stud.get("standard"), diameter, length)
    valid_names = {n for n in (expected, expected_imp) if n}
    if stud.get("name") and valid_names and stud["name"] not in valid_names:
        issues.append(issue(
            "warn", "name_mismatch",
            f"Stud name {stud['name']!r} does not follow the observed convention "
            f"({expected!r}).",
            STUDS, diameter=diameter, length=length,
        ))
    elif not stud.get("name"):
        issues.append(issue(
            "warn", "name_missing",
            "Stud has no display name, so Advance Steel cannot list it.",
            STUDS, diameter=diameter, length=length,
        ))
    return issues


def normalize_stud(row):
    """One `SetBolts` stud row -> normalized record with its own issues."""
    stud = {
        "standard": str(row.get("Standard") or "").strip(),
        "material": str(row.get("Material") or "").strip(),
        "diameter": to_float(row.get("Diameter")),
        "length": to_float(row.get("Length")),
        "name": str(row.get("Name") or "").strip(),
        "head_diameter": to_float(row.get("ScrewHeadOuterDiameter")),
        "head_height": to_float(row.get("HeadHeight")),
        "corners": to_int(row.get("NumberOfCorners")),
        "weight": to_float(row.get("Weight")),
        "source": row.get("Source"),
        "owner": row.get("OwnerText"),
        "type": to_int(row.get("Type")),
    }
    if (
        stud["standard"]
        and stud["material"]
        and stud["diameter"] is not None
        and stud["length"] is not None
    ):
        stud["row_token"] = dbcore.make_row_token(
            {
                "Standard": stud["standard"],
                "Material": stud["material"],
                "Diameter": stud["diameter"],
                "Length": stud["length"],
            },
            ["Standard", "Material", "Diameter", "Length"],
        )
    else:
        stud["row_token"] = None
    stud["issues"] = validate_stud(stud)
    stud["has_errors"] = has_errors(stud["issues"])
    return stud


def head_label(stud):
    """Schematic head description; round heads are the observed default."""
    diameter = stud.get("head_diameter")
    if diameter is None:
        return "no head data"
    corners = stud.get("corners")
    if not corners:
        return f"round head Ø{number_text(diameter)} mm"
    return f"{corners}-sided head Ø{number_text(diameter)} mm"


# --------------------------------------------------------------------------
# Pure helpers: grouping and completeness
# --------------------------------------------------------------------------

def _standard_index(rows):
    return {str(r.get("Key") or "").strip(): r for r in rows}


def _diameter_index(rows):
    index = {}
    for row in rows:
        key = to_float(row.get("Key"))
        if key is not None:
            index[round(key, 6)] = row
    return index


def _distance_index(rows):
    index = defaultdict(list)
    for row in rows:
        key = to_float(row.get("Key"))
        if key is not None:
            index[round(key, 6)].append(row)
    return index


def _triple(standard, material, diameter):
    return (str(standard or "").strip(), str(material or "").strip(), round(float(diameter), 6))


def build_groups(standards, materials, diameters, distances, relations, stud_rows):
    """Build per-(standard, material, diameter) groups plus catalog-wide issues.

    `complete` means the documented minimum record set exists: family and grade
    lookup rows, a diameter row, a distance rule, a relation row, and at least
    one stud length. Errors (not warnings) break completeness.
    """
    standards_index = _standard_index(standards)
    materials_index = _standard_index(materials)
    diameters_index = _diameter_index(diameters)
    distances_index = _distance_index(distances)

    relations_by_triple = defaultdict(list)
    for row in relations:
        diameter = to_float(row.get("ConnectorDiameter"))
        if diameter is None:
            continue
        relations_by_triple[_triple(
            row.get("ConnectorStandard"), row.get("ConnectorMaterial"), diameter
        )].append(row)

    studs_by_triple = defaultdict(list)
    duplicate_studs = []
    seen_studs = set()
    seen_names = {}
    duplicate_names = []
    for row in stud_rows:
        diameter = to_float(row.get("Diameter"))
        length = to_float(row.get("Length"))
        if diameter is None:
            continue
        triple = _triple(row.get("Standard"), row.get("Material"), diameter)
        stud = normalize_stud(row)
        studs_by_triple[triple].append(stud)
        key = (triple, None if length is None else round(length, 6))
        if key in seen_studs:
            duplicate_studs.append(key)
        seen_studs.add(key)
        name = stud.get("name")
        if name:
            prev_key = seen_names.get(name)
            if prev_key is not None and prev_key != key and name not in duplicate_names:
                duplicate_names.append(name)
            else:
                seen_names[name] = key

    global_issues = []
    for triple, _ in duplicate_studs:
        standard, material, diameter = triple
        global_issues.append(issue(
            "error", "duplicate_stud",
            f"Duplicate stud row for {standard} / {material} / "
            f"{number_text(diameter)} mm.",
            STUDS, standard=standard, material=material, diameter=diameter,
        ))
    for name in duplicate_names:
        global_issues.append(issue(
            "warn", "duplicate_stud_name",
            f"Stud display name {name!r} is shared by multiple stud records.",
            STUDS, name=name,
        ))

    triples = set(relations_by_triple) | set(studs_by_triple)
    groups = []
    used_diameters = set()
    used_standards = set()
    used_materials = set()

    for triple in sorted(triples, key=lambda t: (t[0], t[1], t[2])):
        standard, material, diameter = triple
        used_diameters.add(round(diameter, 6))
        used_standards.add(standard)
        used_materials.add(material)

        issues = []
        standard_row = standards_index.get(standard)
        material_row = materials_index.get(material)
        diameter_row = diameters_index.get(round(diameter, 6))
        distance_rows = distances_index.get(round(diameter, 6), [])
        relation_rows = relations_by_triple.get(triple, [])

        if standard_row is None:
            issues.append(issue(
                "error", "missing_standard",
                f"No {CONNECTOR_STANDARD} row for family {standard!r}.",
                CONNECTOR_STANDARD, standard=standard,
            ))
        if material_row is None:
            issues.append(issue(
                "error", "missing_material",
                f"No {CONNECTOR_MATERIAL} row for grade {material!r}.",
                CONNECTOR_MATERIAL, material=material,
            ))
        if diameter_row is None:
            issues.append(issue(
                "error", "missing_diameter",
                f"No {CONNECTOR_DIAMETERS} row for {number_text(diameter)} mm.",
                CONNECTOR_DIAMETERS, diameter=diameter,
            ))
        else:
            note = run_name_issue(diameter_row)
            if note:
                issues.append(note)
        if not distance_rows:
            issues.append(issue(
                "error", "missing_distances",
                f"No {CONNECTOR_DISTANCES} (hole/spacing) row for "
                f"{number_text(diameter)} mm.",
                CONNECTOR_DISTANCES, diameter=diameter,
            ))
        else:
            for r in distance_rows:
                along_v = to_float(r.get("along"))
                across_v = to_float(r.get("across"))
                tol_v = to_float(r.get("HoleTolerance"))
                if (
                    (along_v is not None and along_v <= 0)
                    or (across_v is not None and across_v <= 0)
                    or (tol_v is not None and tol_v < 0)
                ):
                    issues.append(issue(
                        "warn", "invalid_distance_rule",
                        f"{CONNECTOR_DISTANCES} rule for {number_text(diameter)} mm "
                        f"has non-positive spacing or negative hole tolerance.",
                        CONNECTOR_DISTANCES, diameter=diameter,
                    ))
                    break
        if not relation_rows:
            issues.append(issue(
                "error", "missing_relation",
                f"No {CONNECTOR_RELATIONS} row linking {standard} / {material} / "
                f"{number_text(diameter)} mm.",
                CONNECTOR_RELATIONS, diameter=diameter,
            ))
        elif len(relation_rows) > 1:
            issues.append(issue(
                "error", "duplicate_relation",
                f"{len(relation_rows)} {CONNECTOR_RELATIONS} rows link {standard} / "
                f"{material} / {number_text(diameter)} mm.",
                CONNECTOR_RELATIONS, diameter=diameter,
            ))

        studs = sorted(
            studs_by_triple.get(triple, []),
            key=lambda s: (s["length"] is None, s["length"] or 0.0),
        )
        lengths = [s["length"] for s in studs if s["length"] is not None]
        if not studs:
            issues.append(issue(
                "error", "no_lengths",
                f"{standard} / {material} / {number_text(diameter)} mm has no "
                f"{STUDS} lengths, so Advance Steel has nothing to list.",
                STUDS, diameter=diameter,
            ))
        else:
            prev_len = None
            prev_wt = None
            for s in studs:
                wt = s.get("weight")
                ln = s.get("length")
                if wt is not None and wt > 0 and ln is not None and ln > 0:
                    if prev_wt is not None and wt < prev_wt - 1e-6:
                        issues.append(issue(
                            "warn", "weight_non_monotonic",
                            f"Stud weights in {standard} / {material} / "
                            f"{number_text(diameter)} mm decrease as length increases "
                            f"({number_text(prev_len)} mm -> {number_text(ln)} mm).",
                            STUDS, diameter=diameter, length=ln,
                        ))
                        break
                    prev_len = ln
                    prev_wt = wt

        groups.append({
            "standard": standard,
            "material": material,
            "diameter": diameter,
            "standard_run_name": (standard_row or {}).get("RunName") or standard,
            "material_run_name": (material_row or {}).get("RunName") or material,
            "material_weight": to_float((material_row or {}).get("weight")),
            "diameter_run_name": (diameter_row or {}).get("RunName"),
            "diameter_display": (diameter_row or {}).get("RunName")
            or format_metric_run_name(diameter),
            "relation_keys": [to_int(r.get("Key")) for r in relation_rows],
            "distances": [
                {
                    "hole_tolerance": to_float(r.get("HoleTolerance")),
                    "along": to_float(r.get("along")),
                    "across": to_float(r.get("across")),
                }
                for r in distance_rows
            ],
            "studs": studs,
            "lengths": lengths,
            "issues": issues,
            "complete": not has_errors(issues) and bool(studs),
            "stud_count": len(studs),
        })

    for row in standards:
        key = str(row.get("Key") or "").strip()
        if key and key not in used_standards:
            global_issues.append(issue(
                "warn", "orphan_standard",
                f"{CONNECTOR_STANDARD} row {key!r} has no relations or studs.",
                CONNECTOR_STANDARD, standard=key,
            ))
    for row in materials:
        key = str(row.get("Key") or "").strip()
        if key and key not in used_materials:
            global_issues.append(issue(
                "warn", "orphan_material",
                f"{CONNECTOR_MATERIAL} row {key!r} has no relations or studs.",
                CONNECTOR_MATERIAL, material=key,
            ))
    for key, row in sorted(diameters_index.items()):
        if key not in used_diameters:
            global_issues.append(issue(
                "warn", "orphan_diameter",
                f"{CONNECTOR_DIAMETERS} row {number_text(key)} mm has no relations "
                f"or studs.",
                CONNECTOR_DIAMETERS, diameter=key,
            ))
    for key in sorted(distances_index):
        if key not in used_diameters:
            global_issues.append(issue(
                "warn", "orphan_distance",
                f"{CONNECTOR_DISTANCES} row for {number_text(key)} mm has no "
                f"relations or studs.",
                CONNECTOR_DISTANCES, diameter=key,
            ))

    return {"groups": groups, "issues": global_issues}


def family_tree(groups):
    """Group flat (standard, material, diameter) groups into family -> grade."""
    families = {}
    order = []
    for group in groups:
        standard = group["standard"]
        if standard not in families:
            families[standard] = {
                "standard": standard,
                "run_name": group["standard_run_name"],
                "materials": {},
                "diameters": [],
                "stud_count": 0,
            }
            order.append(standard)
        family = families[standard]
        material = group["material"]
        if material not in family["materials"]:
            family["materials"][material] = {
                "material": material,
                "run_name": group["material_run_name"],
                "weight": group["material_weight"],
                "diameters": [],
                "stud_count": 0,
            }
        grade = family["materials"][material]
        grade["diameters"].append(group)
        grade["stud_count"] += group["stud_count"]
        family["stud_count"] += group["stud_count"]
        if group["diameter"] is not None and group["diameter"] not in family["diameters"]:
            family["diameters"].append(group["diameter"])

    result = []
    for standard in order:
        family = families[standard]
        family["diameters"].sort()
        family["grades"] = [
            family["materials"][m] for m in sorted(family["materials"])
        ]
        del family["materials"]
        for grade in family["grades"]:
            grade["diameters"].sort(key=lambda g: (g["diameter"] is None, g["diameter"] or 0.0))
        result.append(family)
    return result


def filter_groups(groups, standard=None, material=None, diameter=None, length=None):
    """Apply browser filters. Blank/None filters are ignored.

    Filtering by length keeps only the matching stud rows inside each group, so
    the returned table shows exactly the lengths asked for.
    """
    diameter_value = to_float(diameter)
    length_value = to_float(length)
    filtered = []
    for group in groups:
        if standard and group["standard"] != standard:
            continue
        if material and group["material"] != material:
            continue
        if diameter_value is not None and not same_number(group["diameter"], diameter_value):
            continue
        if length_value is None:
            filtered.append(group)
            continue
        studs = [s for s in group["studs"] if same_number(s["length"], length_value)]
        if not studs:
            continue
        narrowed = dict(group)
        narrowed["studs"] = studs
        narrowed["lengths"] = [s["length"] for s in studs]
        narrowed["stud_count"] = len(studs)
        filtered.append(narrowed)
    return filtered


def collect_issues(groups, global_issues):
    """Flatten issues for display: catalog-wide first, then per group/stud."""
    combined = list(global_issues)
    stud_issues = []
    for group in groups:
        for item in group["issues"]:
            combined.append({**item, "group": group})
        for stud in group["studs"]:
            for item in stud["issues"]:
                stud_issues.append({**item, "group": group, "stud": stud})
    combined.extend(stud_issues)
    rank = {"error": 0, "warn": 1, "info": 2}
    combined.sort(key=lambda i: rank.get(i["severity"], 3))
    return combined


def summarize(groups, issues):
    return {
        "families": len({g["standard"] for g in groups}),
        "materials": len({(g["standard"], g["material"]) for g in groups}),
        "diameters": len({(g["standard"], g["material"], g["diameter"]) for g in groups}),
        "studs": sum(g["stud_count"] for g in groups),
        "lengths": len({s["length"] for g in groups for s in g["studs"] if s["length"] is not None}),
        "complete": sum(1 for g in groups if g["complete"]),
        "errors": sum(1 for i in issues if i["severity"] == "error"),
        "warnings": sum(1 for i in issues if i["severity"] == "warn"),
        "notes": sum(1 for i in issues if i["severity"] == "info"),
    }


def filter_options(groups):
    """Values for the browser filter selects, derived from the model."""
    return {
        "standards": sorted({g["standard"] for g in groups}),
        "materials": sorted({g["material"] for g in groups}),
        "diameters": sorted({g["diameter"] for g in groups if g["diameter"] is not None}),
        "lengths": sorted({s["length"] for g in groups for s in g["studs"] if s["length"] is not None}),
    }


# --------------------------------------------------------------------------
# Per-record stud detail & schematic SVG (D3)
# --------------------------------------------------------------------------

def _esc(value):
    return html.escape("" if value is None else str(value), quote=False)


def stud_svg(stud, group=None, units="mm"):
    """Schematic 2D elevation SVG of one headed shear stud."""
    stud = stud or {}
    group = group or {}
    u = normalize_units(units)
    d = max(to_float(stud.get("diameter")) or 0.0, 0.0)
    l_mm = max(to_float(stud.get("length")) or 0.0, 0.0)
    hd = max(to_float(stud.get("head_diameter")) or (d * 2.0), 0.0)
    hh = max(to_float(stud.get("head_height")) or (d * 0.5), 0.0)
    total = l_mm + hh
    if d <= 0 or l_mm <= 0:
        return (
            '<svg class="stud-svg" viewBox="0 0 540 80" role="img" '
            'aria-label="Shear stud schematic" xmlns="http://www.w3.org/2000/svg">'
            '<text x="12" y="42" fill="#64748b" font-size="12" font-family="system-ui, sans-serif">'
            "Insufficient stud geometry to draw elevation.</text></svg>"
        )

    draw_w = 340.0
    max_h = 90.0
    scale = min(draw_w / max(total, 1.0), max_h / max(hd, d, 1.0))
    head_w_px = max(hh * scale, 10.0)
    head_h_px = max(hd * scale, 18.0)
    shank_w_px = max(l_mm * scale, 24.0)
    shank_h_px = max(d * scale, 8.0)

    x0 = 40.0
    cy = 72.0
    x_neck = x0 + head_w_px
    x_tip = x_neck + shank_w_px

    title = _esc(stud.get("name") or expected_stud_name(stud.get("standard"), d, l_mm))
    dim_shank = _esc(f"length {format_dimension(l_mm, u)}")
    dim_dia = _esc(f"shank Ø {format_dimension(d, u)}")
    dim_head = _esc(
        f"head Ø {format_dimension(stud.get('head_diameter'), u)} × "
        f"{format_dimension(stud.get('head_height'), u)}"
    )
    rules = group.get("distances") or []
    rule_txt = ""
    if rules:
        r0 = rules[0]
        rule_txt = _esc(
            f"hole spacing: along {format_dimension(r0.get('along'), u)} × "
            f"across {format_dimension(r0.get('across'), u)} "
            f"(tol {format_dimension(r0.get('hole_tolerance'), u)})"
        )

    parts = [
        f'<svg class="stud-svg" viewBox="0 0 540 185" role="img" '
        f'aria-label="Shear stud elevation: {title}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;height:auto;max-width:560px;display:block">',
        f'<text x="16" y="20" fill="#1e293b" font-size="12.5" font-weight="700" '
        f'font-family="system-ui, sans-serif">{title}</text>',
        f'<line x1="{x0 - 12:.1f}" y1="{cy:.1f}" x2="{x_tip + 16:.1f}" y2="{cy:.1f}" '
        f'stroke="#94a3b8" stroke-width="1" stroke-dasharray="5,3"/>',
        f'<rect x="{x0:.1f}" y="{cy - head_h_px / 2:.1f}" width="{head_w_px:.1f}" '
        f'height="{head_h_px:.1f}" rx="2" fill="#5c6f83" stroke="#334155" stroke-width="1.2"/>',
        f'<rect x="{x_neck:.1f}" y="{cy - shank_h_px / 2:.1f}" width="{shank_w_px:.1f}" '
        f'height="{shank_h_px:.1f}" fill="#8fa3b8" stroke="#334155" stroke-width="1.2"/>',
        # Shank length dimension bracket
        f'<line x1="{x_neck:.1f}" y1="{cy + head_h_px / 2 + 10:.1f}" '
        f'x2="{x_neck:.1f}" y2="{cy + head_h_px / 2 + 18:.1f}" stroke="#475569" stroke-width="1"/>',
        f'<line x1="{x_tip:.1f}" y1="{cy + head_h_px / 2 + 10:.1f}" '
        f'x2="{x_tip:.1f}" y2="{cy + head_h_px / 2 + 18:.1f}" stroke="#475569" stroke-width="1"/>',
        f'<line x1="{x_neck:.1f}" y1="{cy + head_h_px / 2 + 14:.1f}" '
        f'x2="{x_tip:.1f}" y2="{cy + head_h_px / 2 + 14:.1f}" stroke="#475569" stroke-width="1"/>',
        f'<text x="{(x_neck + x_tip) / 2:.1f}" y="{cy + head_h_px / 2 + 27:.1f}" '
        f'text-anchor="middle" fill="#1e293b" font-size="11" font-weight="600" '
        f'font-family="system-ui, sans-serif">{dim_shank}</text>',
        # Metadata notes
        f'<text x="16" y="148" fill="#334155" font-size="11" '
        f'font-family="system-ui, sans-serif">{dim_dia} · {dim_head}</text>',
    ]
    if rule_txt:
        parts.append(
            f'<text x="16" y="163" fill="#475569" font-size="10.5" '
            f'font-family="system-ui, sans-serif">{rule_txt}</text>'
        )
    parts.append(
        '<text x="16" y="178" fill="#64748b" font-size="9.5" '
        'font-family="system-ui, sans-serif">'
        "Schematic from observed SetBolts + Connector* records; not round-trip verified.</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def stud_detail(database, groups, standard=None, material=None, diameter=None,
                length=None, units="mm"):
    """Build a per-record inspection model with source-table traceability and SVG."""
    u = normalize_units(units)
    dia_val = to_float(diameter)
    len_val = to_float(length)

    matched_group = None
    matched_stud = None
    if len_val is not None:
        for g in groups:
            if standard and g["standard"] != standard:
                continue
            if material and g["material"] != material:
                continue
            if dia_val is not None and not same_number(g["diameter"], dia_val):
                continue
            for s in g["studs"]:
                if same_number(s["length"], len_val):
                    matched_group = g
                    matched_stud = s
                    break
            if matched_stud is not None:
                break

    if matched_stud is None or matched_group is None:
        return None

    stud_row_url = (
        f"/db/{database}/{STUDS}/edit/{matched_stud['row_token']}"
        if matched_stud.get("row_token")
        else f"/db/{database}/{STUDS}?{urlencode({'filter_col': 'Diameter', 'filter_val': matched_stud['diameter']})}"
    )
    std_url = (
        f"/db/{database}/{CONNECTOR_STANDARD}?"
        f"{urlencode({'filter_col': 'Key', 'filter_val': matched_group['standard']})}"
    )
    mat_url = (
        f"/db/{database}/{CONNECTOR_MATERIAL}?"
        f"{urlencode({'filter_col': 'Key', 'filter_val': matched_group['material']})}"
    )
    dia_url = (
        f"/db/{database}/{CONNECTOR_DIAMETERS}?"
        f"{urlencode({'filter_col': 'Key', 'filter_val': matched_group['diameter']})}"
    )
    dist_url = (
        f"/db/{database}/{CONNECTOR_DISTANCES}?"
        f"{urlencode({'filter_col': 'Key', 'filter_val': matched_group['diameter']})}"
    )
    rel_url = (
        f"/db/{database}/{CONNECTOR_RELATIONS}?"
        f"{urlencode({'filter_col': 'ConnectorDiameter', 'filter_val': matched_group['diameter']})}"
    )

    rule = (matched_group.get("distances") or [{}])[0]
    traceability = [
        {
            "label": "Display name",
            "value": matched_stud.get("name") or "—",
            "table": STUDS,
            "column": "Name",
            "url": stud_row_url,
        },
        {
            "label": "Family / standard",
            "value": f"{matched_group['standard']} ({matched_group['standard_run_name']})",
            "table": f"{STUDS} → {CONNECTOR_STANDARD}",
            "column": "Standard / Key",
            "url": std_url,
        },
        {
            "label": "Grade / material",
            "value": f"{matched_group['material']} ({matched_group['material_run_name']})",
            "table": f"{STUDS} → {CONNECTOR_MATERIAL}",
            "column": "Material / Key",
            "url": mat_url,
        },
        {
            "label": "Nominal diameter",
            "value": f"{format_dimension(matched_stud.get('diameter'), u)} (RunName: {matched_group['diameter_display']!r})",
            "table": f"{STUDS} → {CONNECTOR_DIAMETERS}",
            "column": "Diameter / Key",
            "url": dia_url,
        },
        {
            "label": "Overall length",
            "value": format_dimension(matched_stud.get("length"), u),
            "table": STUDS,
            "column": "Length",
            "url": stud_row_url,
        },
        {
            "label": "Head geometry",
            "value": (
                f"{format_dimension(matched_stud.get('head_diameter'), u)} × "
                f"{format_dimension(matched_stud.get('head_height'), u)} "
                f"({'round' if not matched_stud.get('corners') else str(matched_stud.get('corners')) + '-sided'})"
            ),
            "table": STUDS,
            "column": "ScrewHeadOuterDiameter, HeadHeight, NumberOfCorners",
            "url": stud_row_url,
        },
        {
            "label": "Stud weight",
            "value": f"{matched_stud['weight']} kg" if matched_stud.get("weight") is not None else "—",
            "table": STUDS,
            "column": "Weight",
            "url": stud_row_url,
        },
        {
            "label": "Hole / spacing rule",
            "value": (
                f"along {format_dimension(rule.get('along'), u)} × "
                f"across {format_dimension(rule.get('across'), u)} "
                f"(tol {format_dimension(rule.get('hole_tolerance'), u)})"
                if rule else "missing"
            ),
            "table": CONNECTOR_DISTANCES,
            "column": "along, across, HoleTolerance",
            "url": dist_url,
        },
        {
            "label": "Relation key(s)",
            "value": ", ".join(str(k) for k in matched_group.get("relation_keys") or []) or "missing",
            "table": CONNECTOR_RELATIONS,
            "column": "Key (ConnectorStandard, ConnectorMaterial, ConnectorDiameter)",
            "url": rel_url,
        },
        {
            "label": "Source / owner / Type",
            "value": (
                f"Source={matched_stud.get('source') or '—'}, "
                f"OwnerText={matched_stud.get('owner') or '—'}, "
                f"Type={matched_stud.get('type') if matched_stud.get('type') is not None else '—'} (observed)"
            ),
            "table": STUDS,
            "column": "Source, OwnerText, Type",
            "url": stud_row_url,
        },
    ]

    return {
        "stud": matched_stud,
        "group": matched_group,
        "svg": stud_svg(matched_stud, matched_group, units=u),
        "raw_row_url": stud_row_url,
        "traceability": traceability,
        "issues": list(matched_group.get("issues") or []) + list(matched_stud.get("issues") or []),
    }


# --------------------------------------------------------------------------
# Clone proposal (preview only, never applied)
# --------------------------------------------------------------------------

def parse_lengths(text):
    """Split a free-form length list ("20, 25 30;35") into numbers.

    Returns (values, rejected_tokens) so the caller can report bad input
    instead of silently dropping it.
    """
    values = []
    rejected = []
    for token in re.split(r"[,;\s]+", str(text or "").strip()):
        if not token:
            continue
        number = to_float(token)
        if number is None:
            rejected.append(token)
        else:
            values.append(number)
    return values, rejected


def find_group(groups, standard, material, diameter):
    for group in groups:
        if group["standard"] != standard or group["material"] != material:
            continue
        if same_number(group["diameter"], diameter):
            return group
    return None


def next_relation_key(relation_keys):
    """Next integer for ConnectorRelations.Key (identity handling unconfirmed)."""
    numbers = [int(k) for k in relation_keys if k is not None]
    return (max(numbers) + 1) if numbers else 1


def _round4(value):
    return None if value is None else round(float(value), 4)


def plan_clone(groups, relation_keys, diameter_keys, standard, material,
               source_diameter, target_diameter, lengths, scale_geometry=True,
               along=None, across=None, hole_tolerance=None):
    """Propose the rows needed to add one diameter to a stud family.

    PREVIEW ONLY: the result is a set of INSERT-shaped rows plus the issues
    that make them unsafe to apply. Nothing here writes SQL and nothing claims
    the rows are correct — the connector schema is still unverified, and every
    scaled value is a starting estimate.
    """
    issues = []
    source = find_group(groups, standard, material, to_float(source_diameter))
    target = to_float(target_diameter)
    length_values, rejected = parse_lengths(lengths) if isinstance(lengths, str) else (
        [n for n in (to_float(v) for v in (lengths or [])) if n is not None],
        [],
    )

    for token in rejected:
        issues.append(issue(
            "error", "bad_length", f"Length {token!r} is not a number.",
            STUDS, diameter=target,
        ))
    if source is None:
        issues.append(issue(
            "error", "source_missing",
            f"No stud row matches {standard} / {material} / "
            f"{number_text(source_diameter)} mm.",
            STUDS, diameter=source_diameter,
        ))
    elif not source["complete"]:
        issues.append(issue(
            "error", "source_incomplete",
            "The source group is not complete, so it cannot be used as a template.",
            STUDS, diameter=source["diameter"],
        ))
    if target is None or target <= 0:
        issues.append(issue(
            "error", "bad_target", "Target diameter must be a positive number.",
            CONNECTOR_DIAMETERS,
        ))
    if not length_values:
        issues.append(issue(
            "error", "no_lengths", "Enter at least one stud length to create.",
            STUDS, diameter=target,
        ))
    for value in sorted({v for v in length_values if v <= 0}):
        issues.append(issue(
            "error", "bad_length", f"Length {number_text(value)} mm must be positive.",
            STUDS, diameter=target,
        ))
    duplicates = sorted({v for v in length_values if length_values.count(v) > 1})
    for value in duplicates:
        issues.append(issue(
            "error", "duplicate_length",
            f"Length {number_text(value)} mm appears more than once.",
            STUDS, diameter=target,
        ))

    existing_group = find_group(groups, standard, material, target) if target else None
    if existing_group is not None:
        issues.append(issue(
            "error", "group_exists",
            f"{standard} / {material} / {number_text(target)} mm already exists in "
            f"this catalog; edit it instead of cloning over it.",
            STUDS, diameter=target,
        ))
    if target and any(same_number(key, target) for key in diameter_keys or []):
        issues.append(issue(
            "error", "diameter_exists",
            f"{CONNECTOR_DIAMETERS} already has a row for {number_text(target)} mm.",
            CONNECTOR_DIAMETERS, diameter=target,
        ))
    existing_lengths = [s["length"] for s in (existing_group or {}).get("studs", [])
                        if s["length"] is not None]
    for value in length_values:
        if any(same_number(existing_length, value) for existing_length in existing_lengths):
            issues.append(issue(
                "error", "length_exists",
                f"{STUDS} already has a {number_text(target)} x "
                f"{number_text(value)} stud.",
                STUDS, diameter=target, length=value,
            ))

    existing_names = {
        s["name"] for g in groups for s in g["studs"] if s.get("name")
    }
    for value in length_values:
        name = expected_stud_name(standard, target, value)
        if name in existing_names:
            issues.append(issue(
                "error", "name_exists",
                f"A stud named {name!r} already exists.",
                STUDS, diameter=target, length=value,
            ))

    factor = None
    if source and target and source["diameter"]:
        factor = target / source["diameter"]
    scaled = bool(scale_geometry and factor)

    source_studs = (source or {}).get("studs") or []
    template = source_studs[0] if source_studs else {}
    source_head = template.get("head_diameter")
    source_head_height = template.get("head_height")
    head = _round4(source_head * factor) if scaled and source_head is not None else source_head
    head_height = (
        _round4(source_head_height * factor)
        if scaled and source_head_height is not None else source_head_height
    )

    rule = ((source or {}).get("distances") or [{}])[0]
    tolerance_value = to_float(hole_tolerance)
    if tolerance_value is None:
        tolerance_value = rule.get("hole_tolerance")
    along_value = to_float(along)
    if along_value is None and rule.get("along") is not None:
        along_value = _round4(rule["along"] * factor) if scaled else rule["along"]
    across_value = to_float(across)
    if across_value is None and rule.get("across") is not None:
        across_value = _round4(rule["across"] * factor) if scaled else rule["across"]

    if scaled:
        issues.append(issue(
            "info", "scaled_estimate",
            f"Head geometry and hole rules are scaled by {number_text(factor)}x "
            f"({number_text(source['diameter'])} -> {number_text(target)} mm). "
            "Treat every scaled value as a starting estimate and check it against "
            "manufacturer or governing-standard data.",
            STUDS, diameter=target,
        ))
    if target is not None and along_value is not None and along_value <= target:
        issues.append(issue(
            "warn", "tight_spacing",
            f"Along-hole spacing {number_text(along_value)} mm is not larger than "
            f"the {number_text(target)} mm stud diameter.",
            CONNECTOR_DISTANCES, diameter=target,
        ))

    studs = []
    if target is not None and length_values:
        for value in sorted(set(length_values)):
            if value <= 0:
                continue
            source_length_stud = next(
                (s for s in source_studs if same_number(s["length"], value)), None
            )
            weight = None
            if source_length_stud is not None and source_length_stud.get("weight") is not None:
                weight = _round4(
                    source_length_stud["weight"] * (factor ** 2) if scaled
                    else source_length_stud["weight"]
                )
            row = {
                "Standard": standard,
                "Material": material,
                "Diameter": target,
                "Length": value,
                "ScrewHeadOuterDiameter": head,
                "HeadHeight": head_height,
                "NumberOfCorners": template.get("corners"),
                "Name": expected_stud_name(standard, target, value),
                "Weight": weight,
                "OwnerText": template.get("owner"),
                "Source": template.get("source") or standard,
                "Type": template.get("type"),
            }
            studs.append(row)
            if weight is None:
                issues.append(issue(
                    "info", "weight_unknown",
                    f"No source stud of {number_text(value)} mm exists at "
                    f"{number_text(source['diameter'] if source else None)} mm, so the "
                    f"new weight is left empty.",
                    STUDS, diameter=target, length=value,
                ))
            for item in normalize_stud(row)["issues"]:
                if item["code"] == "weight_missing":
                    continue
                issues.append(item)

    tables = []
    if target is not None and source is not None:
        tables = [
            {
                "table": CONNECTOR_DIAMETERS,
                "rows": [{
                    "Key": target,
                    "RunName": format_metric_run_name(target),
                    "Description": None,
                }],
                "note": "Key is a millimetre float and the table's primary key.",
            },
            {
                "table": CONNECTOR_DISTANCES,
                "rows": [{
                    "Key": target,
                    "HoleTolerance": _round4(tolerance_value) if tolerance_value is not None else 0.0,
                    "along": _round4(along_value),
                    "across": _round4(across_value),
                    "Description": None,
                }],
                "note": "Hole/spacing rule; the rule table is mirrored from BoltsDistances.",
            },
            {
                "table": CONNECTOR_RELATIONS,
                "rows": [{
                    "Key": next_relation_key(relation_keys),
                    "ConnectorStandard": standard,
                    "ConnectorMaterial": material,
                    "ConnectorDiameter": target,
                }],
                "note": "Key is not an identity column in the export; the next free "
                        "integer is proposed and must be confirmed before applying.",
            },
            {
                "table": STUDS,
                "rows": studs,
                "note": "One row per requested length; weight is only filled when a "
                        "source stud of the same length exists.",
            },
        ]

    return {
        "status": "preview",
        "ok": not has_errors(issues),
        "issues": issues,
        "scale_factor": _round4(factor) if factor else None,
        "scale_geometry": scaled,
        "source": {
            "standard": standard,
            "material": material,
            "diameter": (source or {}).get("diameter", to_float(source_diameter)),
            "lengths": (source or {}).get("lengths", []),
        },
        "target": {
            "standard": standard,
            "material": material,
            "diameter": target,
            "run_name": format_metric_run_name(target) if target is not None else None,
            "lengths": sorted(set(length_values)),
        },
        "tables": tables,
        "summary": {
            "tables": len(tables),
            "rows": sum(len(t["rows"]) for t in tables),
            "errors": sum(1 for i in issues if i["severity"] == "error"),
            "warnings": sum(1 for i in issues if i["severity"] == "warn"),
            "notes": sum(1 for i in issues if i["severity"] == "info"),
        },
    }


# --------------------------------------------------------------------------
# SQL gathering (read-only)
# --------------------------------------------------------------------------

def _rows(database, table):
    if table not in set(dbcore.list_tables(database)):
        return []
    return dbcore.get_rows(database, table, limit=ROW_LIMIT)


def get_browser_model(database):
    """Read the connector tables and return the normalized browser model."""
    tables = set(dbcore.list_tables(database))
    missing = [t for t in REQUIRED_TABLES if t not in tables]
    if missing:
        raise ValueError(
            f"Not a shear-stud (connector) catalog: missing table(s) {', '.join(missing)}."
        )
    diameter_rows = _rows(database, CONNECTOR_DIAMETERS)
    relation_rows = _rows(database, CONNECTOR_RELATIONS)
    built = build_groups(
        standards=_rows(database, CONNECTOR_STANDARD),
        materials=_rows(database, CONNECTOR_MATERIAL),
        diameters=diameter_rows,
        distances=_rows(database, CONNECTOR_DISTANCES),
        relations=relation_rows,
        stud_rows=_rows(database, STUDS),
    )
    groups = built["groups"]
    issues = collect_issues(groups, built["issues"])
    return {
        "groups": groups,
        "families": family_tree(groups),
        "issues": issues,
        "global_issues": built["issues"],
        "summary": summarize(groups, issues),
        "options": filter_options(groups),
        "diameter_keys": sorted(_diameter_index(diameter_rows)),
        "relation_keys": [to_int(r.get("Key")) for r in relation_rows],
    }


def apply_clone(database, standard, material, source_diameter, target_diameter,
                lengths, scale_geometry=True, along=None, across=None,
                hole_tolerance=None):
    """Apply a verified shear-stud diameter clone in one SQL transaction (D1).

    Re-reads the catalog and re-runs `plan_clone()` on the server before opening
    a transaction, so browser parameters are never trusted directly. Inserts into
    `ConnectorDiameters`, `ConnectorDistances`, `ConnectorRelations`, and
    `SetBolts` in parent-before-child order and rolls back on any error.
    """
    model = get_browser_model(database)
    plan = plan_clone(
        model["groups"],
        model["relation_keys"],
        model["diameter_keys"],
        standard=standard,
        material=material,
        source_diameter=source_diameter,
        target_diameter=target_diameter,
        lengths=lengths,
        scale_geometry=scale_geometry,
        along=along,
        across=across,
        hole_tolerance=hole_tolerance,
    )
    if not plan["ok"]:
        err_msgs = [i["message"] for i in plan["issues"] if i["severity"] == "error"]
        raise ValueError(
            "Clone plan has blocking errors: " + "; ".join(err_msgs or ["invalid clone parameters"])
        )

    tables_by_name = {t["table"]: t["rows"] for t in plan["tables"]}
    inserted = {
        CONNECTOR_DIAMETERS: 0,
        CONNECTOR_DISTANCES: 0,
        CONNECTOR_RELATIONS: 0,
        STUDS: 0,
    }

    conn = dbcore._open_connection(database)
    try:
        cur = conn.cursor()
        for row in tables_by_name.get(CONNECTOR_DIAMETERS, []):
            cur.execute(
                "INSERT INTO [ConnectorDiameters] ([Key], [RunName], [Description]) "
                "VALUES (%s, %s, %s)",
                (row["Key"], row["RunName"], row.get("Description")),
            )
            inserted[CONNECTOR_DIAMETERS] += 1

        for row in tables_by_name.get(CONNECTOR_DISTANCES, []):
            cur.execute(
                "INSERT INTO [ConnectorDistances] "
                "([Key], [HoleTolerance], [along], [across], [Description]) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    row["Key"],
                    row["HoleTolerance"],
                    row.get("along"),
                    row.get("across"),
                    row.get("Description"),
                ),
            )
            inserted[CONNECTOR_DISTANCES] += 1

        for row in tables_by_name.get(CONNECTOR_RELATIONS, []):
            cur.execute(
                "INSERT INTO [ConnectorRelations] "
                "([Key], [ConnectorStandard], [ConnectorMaterial], [ConnectorDiameter]) "
                "VALUES (%s, %s, %s, %s)",
                (
                    row["Key"],
                    row["ConnectorStandard"],
                    row["ConnectorMaterial"],
                    row["ConnectorDiameter"],
                ),
            )
            inserted[CONNECTOR_RELATIONS] += 1

        for row in tables_by_name.get(STUDS, []):
            cur.execute(
                "INSERT INTO [SetBolts] "
                "([Standard], [Material], [Diameter], [Length], "
                "[ScrewHeadOuterDiameter], [HeadHeight], [NumberOfCorners], "
                "[Name], [Weight], [OwnerText], [Source], [Type]) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    row["Standard"],
                    row["Material"],
                    row["Diameter"],
                    row["Length"],
                    row.get("ScrewHeadOuterDiameter"),
                    row.get("HeadHeight"),
                    row.get("NumberOfCorners"),
                    row.get("Name"),
                    row.get("Weight"),
                    row.get("OwnerText"),
                    row.get("Source"),
                    row.get("Type"),
                ),
            )
            inserted[STUDS] += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "status": "applied",
        "ok": True,
        "plan": plan,
        "inserted": inserted,
        "total_inserted": sum(inserted.values()),
    }
