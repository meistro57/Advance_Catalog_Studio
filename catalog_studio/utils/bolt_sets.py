# utils/bolt_sets.py
"""Read-only bolt-set view model for the graphical bolt-set viewer (issue #1,
Phase 1).

Maps raw catalog rows (SetOfBolts assembly recipe + matching SetBolts and
SetNutsBolts records) into a normalized, render-ready structure describing the
physical hardware stack: bolt, washers, nut, and the schematic clamped-material
(grip) zone between them.

IMPORTANT — Position-field interpretation
-----------------------------------------
The meaning of SetOfBolts.Position1..Position6 is NOT yet verified against a
live Advance Steel installation. The interpretation below is derived from the
checked-in sample catalogs (A325TC_mark, Grade5) and is deliberately encoded in
one place (partition_components / order_components) so it can be corrected once
verified. Do not use these positions to WRITE back to a catalog until the
mapping is confirmed (see issue #1, "Investigation required").

Observed so far in the sample data:
- SetNutsBolts.Type is a reliable component classifier: 1 = nut, 2 = washer.
- In SetOfBolts rows, Position values are signed layer counts: components on
  the nut (thread) end are negative (-1 adjacent to the clamped material,
  -2 = the nut on top of that washer), while an extra under-head washer is
  positive (+1, sitting directly on the head side of the material).
- A325TC_mark Mu2S (nut + 2 washers) reads: DIN1=A563 nut (Position -2),
  DIN2=F436 washer (-1), DIN3=F436 washer (+1). Single-washer sets read
  nut(-2) + washer(-1).
- Some rows are not consistent with that sign convention (Grade5 MuS at
  10.0 mm has HEX nut Position +1 and Flat washer +2). When signs do not split
  the components into two sides, this module falls back to component-type
  ordering (nut outermost at the thread end, washers beneath it) and flags the
  row.

Bolt length is the under-head shank length; the head is drawn below the shank.
The schematic grip thickness is the shank length minus the head-side hardware
stack and the nut-side hardware stack. If that is not positive the set cannot
physically assemble on the chosen bolt length and a warning is emitted.
"""

import json

from utils import db as dbcore

# Component columns repeat DIN/Diameter/Material/Position over 6 slots.
# In the bolt SetOfBolts schema the per-slot diameter column is
# "Diameter{i} (mm)" (space + parentheses); anchors use "Diameter{i}".
SLOT_COUNT = 6
EMPTY_SLOT_VALUES = (None, "", "-")


def parse_component_slots(row: dict, diameter_suffix: str = " (mm)") -> list:
    """Extract the populated DIN1..DIN6 component slots from a SetOfBolts row.

    Returns a list of slot dicts in slot order (1..6). Slots whose DIN is
    blank or '-' are skipped, as are slots whose DIN is set but diameter is
    missing.
    """
    slots = []
    for i in range(1, SLOT_COUNT + 1):
        din = row.get(f"DIN{i}")
        if din in EMPTY_SLOT_VALUES:
            continue
        diameter = row.get(f"Diameter{i}{diameter_suffix}")
        material = row.get(f"Material{i}")
        position = row.get(f"Position{i}")
        if diameter is None:
            continue
        slots.append({
            "slot": i,
            "din": din,
            "diameter": _as_float(diameter),
            "material": material if material not in EMPTY_SLOT_VALUES else None,
            "position": _as_float(position),
        })
    return slots


def match_setnut(slot: dict, nut_rows: list) -> dict:
    """Find the SetNutsBolts record for a component slot.

    Matching is exact on (Standard, Material, Diameter). If that fails and
    exactly one record matches (Standard, Diameter), it is used and flagged
    with material_mismatch. Returns None when no unique match exists.
    """
    dia = slot["diameter"]
    if dia is None or dia <= 0:
        return None
    exact = [
        r for r in nut_rows
        if r.get("Standard") == slot["din"]
        and _as_float(r.get("Diameter")) == dia
        and r.get("Material") == slot["material"]
    ]
    if len(exact) == 1:
        return {"record": exact[0]}
    if len(exact) > 1:
        return None  # ambiguous even on exact key: treat as unmatched
    loose = [
        r for r in nut_rows
        if r.get("Standard") == slot["din"]
        and _as_float(r.get("Diameter")) == dia
    ]
    if len(loose) == 1:
        return {"record": loose[0], "material_mismatch": True}
    return None


def component_role(record: dict) -> str:
    """Classify a SetNutsBolts record: 'nut', 'washer', or 'part' (unknown)."""
    if record is None:
        return "part"
    rtype = record.get("Type")
    if rtype == 1:
        return "nut"
    if rtype == 2:
        return "washer"
    corners = record.get("NumberOfCorners") or 0
    return "nut" if corners and corners >= 5 else "washer"


def annotate_components(slots: list, nut_rows: list) -> list:
    """Merge slot info with its matched SetNutsBolts record (if any)."""
    components = []
    for slot in slots:
        match = match_setnut(slot, nut_rows)
        record = match["record"] if match else None
        components.append({
            **slot,
            "matched": match is not None,
            "material_mismatch": bool(match and match.get("material_mismatch")),
            "role": component_role(record),
            "name": record.get("Name") if record else None,
            "height": _as_float(record.get("Height")) if record else None,
            "width": _as_float(record.get("OutsideDiameter")) if record else None,
            "corners": record.get("NumberOfCorners") if record else None,
            "weight": _as_float(record.get("Weight")) if record else None,
            "item_number": record.get("ItemNumber") if record else None,
            "source_table": "SetNutsBolts" if record else None,
        })
    return components


def partition_components(components: list) -> dict:
    """Split ordered components into head-side and nut-side stacks.

    Returns {"head_side": [...], "nut_side": [...], "notes": [...]} where each
    list is ordered bottom-to-top along the bolt (head at the bottom). See the
    module docstring for the unverified Position interpretation.
    """
    notes = []
    signed = [c for c in components if c.get("position") is not None and c["position"] != 0]
    has_neg = any(c["position"] < 0 for c in signed)
    has_pos = any(c["position"] > 0 for c in signed)

    def role_rank(c):
        return {"washer": 0, "part": 1, "nut": 2}[c["role"]]

    if has_neg and has_pos:
        head_side = sorted(
            (c for c in components if c.get("position", 0) > 0),
            key=lambda c: c["position"],
        )
        nut_side = sorted(
            (c for c in components if c.get("position", 0) < 0),
            key=lambda c: (role_rank(c), -c["position"]),
        )
        notes.append(
            "Split into head-side and nut-side stacks using signed Position "
            "values (unverified interpretation, see bolt_sets.py)."
        )
    else:
        # Single stack on the nut end, ordered by component type so the nut is
        # outermost and washers sit against the clamped material.
        signed_key = (lambda c: -c["position"]) if signed else (lambda c: c["slot"])
        nut_side = sorted(components, key=lambda c: (role_rank(c), signed_key(c)))
        head_side = []
        if components:
            notes.append(
                "Position fields do not separate head-side and nut-side "
                "components for this row; arranged by component type "
                "(nut outermost). Verify against a live catalog."
            )
    return {"head_side": head_side, "nut_side": nut_side, "notes": notes}


def _component_height(component: dict) -> tuple:
    """(height_mm, schematic_flag). Schematic fallbacks used only when the
    catalog record has no height."""
    if component["height"] is not None and component["height"] > 0:
        return component["height"], False
    dia = component.get("diameter") or 0
    fallback = max(dia * 0.8, 1.0) if component["role"] == "nut" else max(dia * 0.25, 0.5)
    return fallback, True


def build_layout(bolt: dict, partition: dict, grip_override: float = None) -> dict:
    """Place head-side and nut-side components on the bolt shank.

    bolt must contain {"length": under-head shank mm, "head_height": mm}.
    Shank spans y in [0, length]; the head occupies [-head_height, 0].
    Components are given stack_bottom/stack_top in that frame, plus a "side"
    tag ("head" | "nut") and a "layer" index (0 = adjacent to the clamped
    material on that side).

    The schematic grip zone spans between the top of the head-side stack and
    the bottom of the nut-side stack. By default (grip_override=None) it is
    whatever shank length remains after the two hardware stacks - the nut
    stack is anchored with its top at the shank end (nut at the thread tip).
    With grip_override set, the requested clamped-material thickness is used
    but is reduced (with a warning) when the hardware stacks plus the request
    do not fit in the shank length.

    The Javascript module static/js/bolt-set-layout.js mirrors this function
    so Phase 2 draft previews can update client-side without a server round
    trip; keep the two in sync.
    """
    length = bolt["length"]
    head_height = bolt["head_height"]

    parts = []
    warnings = []

    head_used = 0.0
    for layer, c in enumerate(partition["head_side"]):
        height, schematic = _component_height(c)
        bottom = head_used
        parts.append({
            **c,
            "side": "head",
            "layer": layer,
            "stack_bottom": round(bottom, 4),
            "stack_top": round(bottom + height, 4),
            "schematic_height": schematic,
        })
        head_used = bottom + height

    nut_total = sum(_component_height(c)[0] for c in partition["nut_side"])

    if grip_override is not None and grip_override >= 0:
        # Nut stack stays anchored at the shank end (top flush with the tip).
        requested = grip_override
        available = length - head_used - nut_total
        if requested > available + 1e-9:
            warnings.append({
                "severity": "warning",
                "code": "grip_limited",
                "message": (
                    f"Requested clamped-material thickness {round(requested, 2)} mm "
                    f"does not fit on the {round(length, 2)} mm bolt "
                    f"(hardware stacks take {round(head_used + nut_total, 2)} mm); "
                    f"reduced to {round(max(available, 0), 2)} mm."
                ),
            })
            requested = max(available, 0.0)
        nut_bottom = head_used + requested
    else:
        nut_bottom = length - nut_total

    cursor = nut_bottom
    for layer, c in enumerate(partition["nut_side"]):
        height, schematic = _component_height(c)
        bottom = cursor
        parts.append({
            **c,
            "side": "nut",
            "layer": layer,
            "stack_bottom": round(bottom, 4),
            "stack_top": round(bottom + height, 4),
            "schematic_height": schematic,
        })
        cursor = bottom + height

    grip_bottom = head_used
    grip_top = nut_bottom
    grip_thickness = grip_top - grip_bottom
    if grip_thickness <= 0:
        warnings.append({
            "severity": "danger",
            "code": "impossible_stack",
            "message": (
                f"Hardware stack (head-side {round(head_used, 2)} mm + "
                f"nut-side {round(nut_total, 2)} mm) exceeds the {round(length, 2)} mm "
                f"bolt length; this set cannot assemble on this length."
            ),
        })
        grip_thickness = max(grip_thickness, 0.0)

    return {
        "parts": parts,
        "head_used": round(head_used, 4),
        "nut_used": round(nut_total, 4),
        "grip": {
            "bottom": round(grip_bottom, 4),
            "top": round(grip_top, 4),
            "thickness": round(grip_thickness, 4),
        },
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# SQL-backed assembly of the full view model
# --------------------------------------------------------------------------

def _as_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round4(value):
    return None if value is None else round(value, 4)


def _fetch_nut_rows(database: str) -> list:
    conn, cur = dbcore.connect(database)
    cur.execute("SELECT * FROM [SetNutsBolts]")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_bolt_combos(database: str) -> list:
    """Distinct (Standard, [Set], Material, Diameter) assemblies from SetOfBolts."""
    conn, cur = dbcore.connect(database)
    cur.execute("""
        SELECT DISTINCT Standard, [Set], Material, Diameter
        FROM [SetOfBolts]
        ORDER BY Standard, Diameter, [Set]
    """)
    rows = cur.fetchall()
    conn.close()
    combos = []
    for r in rows:
        item = {
            "standard": r["Standard"],
            "set": r["Set"],
            "material": r["Material"],
            "diameter": _round4(r["Diameter"]),
        }
        if item not in combos:
            combos.append(item)
    return combos


def get_bolt_lengths(database: str, standard: str, material: str, diameter: float) -> list:
    """Available bolt lengths (mm) for one standard/material/diameter."""
    conn, cur = dbcore.connect(database)
    cur.execute("""
        SELECT [Length] FROM [SetBolts]
        WHERE Standard = %s AND Material = %s AND Diameter = %s
        ORDER BY [Length]
    """, (standard, material, float(diameter)))
    lengths = [round(r["Length"], 4) for r in cur.fetchall()]
    conn.close()
    return lengths


def _fetch_bolt(database: str, standard: str, material: str, diameter: float, length: float) -> dict:
    conn, cur = dbcore.connect(database)
    cur.execute("""
        SELECT TOP 1 * FROM [SetBolts]
        WHERE Standard = %s AND Material = %s AND Diameter = %s AND [Length] = %s
    """, (standard, material, float(diameter), float(length)))
    row = cur.fetchone()
    conn.close()
    return row


def _fetch_set_rows(database: str, standard: str, set_name: str, material: str, diameter: float) -> list:
    conn, cur = dbcore.connect(database)
    cur.execute("""
        SELECT * FROM [SetOfBolts]
        WHERE Standard = %s AND [Set] = %s AND Material = %s AND Diameter = %s
    """, (standard, set_name, material, float(diameter)))
    rows = cur.fetchall()
    conn.close()
    return rows


def _fetch_screw_rules(database: str, standard: str, set_name: str, material: str, diameter: float) -> list:
    """Normalized grip bands from ScrewNew for the exact combo, falling back to
    any rule rows for the diameter."""
    conn, cur = dbcore.connect(database)
    cur.execute("""
        SELECT * FROM [ScrewNew]
        WHERE Standard = %s AND [Set] = %s AND Material = %s AND Diameter = %s
    """, (standard, set_name, material, float(diameter)))
    rows = cur.fetchall()
    if not rows:
        cur.execute("SELECT * FROM [ScrewNew] WHERE Diameter = %s", (float(diameter),))
        rows = cur.fetchall()
    conn.close()
    return normalize_screw_rules(rows)


def normalize_screw_rules(rows: list) -> list:
    """Flatten ScrewNew rows into a list of grip bands.

    ScrewNew stores up to 7 bands per row, each with GripLengthMin/Max and the
    auto-calculated ScrewLengthBase/Delta for that band. Empty bands (all
    zeros / NULLs) are dropped.
    """
    rules = []
    for row in rows:
        for band in range(1, 8):
            gmin = _as_float(row.get(f"GripLengthMin{band}"))
            gmax = _as_float(row.get(f"GripLengthMax{band}"))
            base = _as_float(row.get(f"ScrewLengthBase{band}"))
            delta = _as_float(row.get(f"ScrewLengthDelta{band}"))
            if gmin is None and gmax is None:
                continue
            if (gmin or 0) == 0 and (gmax or 0) == 0 and (base or 0) == 0:
                continue
            rules.append({
                "standard": row.get("Standard"),
                "set": row.get("Set"),
                "material": row.get("Material"),
                "grip_min": _round4(gmin),
                "grip_max": _round4(gmax),
                "base_length": _round4(base),
                "length_delta": _round4(delta),
            })
    return rules


def _fetch_diameter_lookup(database: str, diameter: float) -> dict:
    conn, cur = dbcore.connect(database)
    cur.execute("SELECT [Key], RunName, Description FROM [BoltsDiameters] WHERE [Key] = %s", (float(diameter),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {}
    return {"key": _round4(row["Key"]), "run_name": row.get("RunName"), "description": row.get("Description")}


def normalize_catalog_parts(nut_rows: list) -> list:
    """Deduplicated, render-ready list of every SetNutsBolts record.

    Candidates are keyed by (Standard, Material, Diameter) - that triple is
    the SetNutsBolts primary key for Phase 3 write-backs. Sorted by Standard,
    then Name, for stable dropdown ordering.
    """
    seen = {}
    for r in nut_rows:
        key = (r.get("Standard"), r.get("Material"), _round4(r.get("Diameter")))
        if key in seen:
            continue
        seen[key] = {
            "standard": r.get("Standard"),
            "material": r.get("Material"),
            "diameter": _round4(r.get("Diameter")),
            "type": r.get("Type"),
            "role": component_role(r),
            "name": r.get("Name"),
            "height": _round4(r.get("Height")),
            "width": _round4(r.get("OutsideDiameter")),
            "corners": r.get("NumberOfCorners"),
            "weight": None if r.get("Weight") is None else round(r.get("Weight"), 5),
            "item_number": r.get("ItemNumber"),
        }
    return sorted(seen.values(), key=lambda p: (p["standard"] or "", p["name"] or ""))


def bolt_set_view(database: str, standard: str, set_name: str, material: str,
                  diameter: float, length: float) -> dict:
    """Assemble the full read-only view model for one bolt-set selection.

    Pure mapping logic lives in the functions above so it can be unit-tested
    without a database; this function only gathers rows and delegates.
    """
    tables = set(dbcore.list_tables(database))
    if "SetOfBolts" not in tables or "SetBolts" not in tables:
        return {"ok": False, "error": "Database is not a bolt catalog (no SetOfBolts/SetBolts)."}

    set_rows = _fetch_set_rows(database, standard, set_name, material, diameter)
    if not set_rows:
        return {"ok": False, "error": "No SetOfBolts assembly row matches that selection."}
    # Prefer the row describing the most components.
    set_row = max(set_rows, key=lambda r: sum(
        1 for i in range(1, SLOT_COUNT + 1)
        if r.get(f"DIN{i}") not in EMPTY_SLOT_VALUES
    ))

    slots = parse_component_slots(set_row)
    nut_rows = _fetch_nut_rows(database)
    components = annotate_components(slots, nut_rows)
    catalog_parts = normalize_catalog_parts(nut_rows)
    partition = partition_components(components)

    lengths = get_bolt_lengths(database, standard, material, diameter)

    bolt_row = _fetch_bolt(database, standard, material, diameter, length)
    warnings = []
    bolt = None
    if not bolt_row:
        warnings.append({
            "severity": "warning",
            "code": "no_bolt_length",
            "message": f"No SetBolts record found for length {round(length, 4)} mm; "
                       f"available lengths for this diameter: {len(lengths)}.",
        })
        bolt_row = {}

    head_corners_recorded = bolt_row.get("NumberOfCorners")
    head_corners = head_corners_recorded if (head_corners_recorded or 0) >= 3 else 6
    corners_assumed = (head_corners_recorded or 0) < 3
    if corners_assumed:
        warnings.append({
            "severity": "info",
            "code": "head_corners_assumed",
            "message": "Bolt head corner count not recorded in SetBolts; rendered as "
                       "hexagonal (6 sides) for the schematic.",
        })

    bolt = {
        "source_table": "SetBolts",
        "diameter": _round4(bolt_row.get("Diameter")),
        "length": _round4(bolt_row.get("Length")),
        "head_width": _round4(bolt_row.get("ScrewHeadOuterDiameter")),
        "head_height": _round4(bolt_row.get("HeadHeight")),
        "head_corners": head_corners,
        "head_corners_recorded": head_corners_recorded,
        "head_corners_assumed": corners_assumed,
        "name": bolt_row.get("Name"),
        "material": bolt_row.get("Material"),
        "standard": bolt_row.get("Standard"),
        "weight": _round4(bolt_row.get("Weight")),
        "owner_text": bolt_row.get("OwnerText"),
    }

    layout = build_layout(
        {"length": bolt["length"] or 0.0, "head_height": bolt["head_height"] or 0.0},
        partition,
    )

    # Schematic-height warnings and unmatched-component warnings.
    for part in layout["parts"]:
        if part["schematic_height"]:
            warnings.append({
                "severity": "warning",
                "code": "schematic_height",
                "message": f"Slot {part['slot']} ({part['din']}) has no height in "
                           f"SetNutsBolts; a schematic thickness was used for display.",
            })
        if not part["matched"]:
            extra = " (material differs from the assembly row)" if part["material_mismatch"] else ""
            warnings.append({
                "severity": "danger" if part["role"] != "part" else "warning",
                "code": "unmatched_component",
                "message": f"Slot {part['slot']}: no unique SetNutsBolts record for "
                           f"Standard '{part['din']}'{extra}, diameter "
                           f"{part['diameter']} mm. Component shown without dimensions.",
            })
    warnings.extend(layout["warnings"])

    screw_rules = _fetch_screw_rules(database, standard, set_name, material, diameter)
    active_band = None
    if layout["grip"]["thickness"] > 0:
        for band in screw_rules:
            if (band["grip_min"] is None or layout["grip"]["thickness"] >= band["grip_min"]) and \
               (band["grip_max"] is None or layout["grip"]["thickness"] <= band["grip_max"]):
                active_band = band
                break

    return {
        "ok": True,
        "database": database,
        "selection": {
            "standard": standard,
            "set": set_name,
            "material": material,
            "diameter": _round4(diameter),
            "length": _round4(length),
        },
        "catalog_diameter": _fetch_diameter_lookup(database, diameter),
        "catalog_parts": catalog_parts,
        "bolt": bolt,
        "assembly_notes": partition["notes"],
        "grip": layout["grip"],
        "components": layout["parts"],
        "screw_rules": screw_rules,
        "active_screw_band": active_band,
        "available_lengths": lengths,
        "warnings": warnings,
    }
