# utils/anchor_sets.py
"""Read-only anchor view model for the graphical anchor viewer.

Maps catalog rows (AnchorsName + AnchorsDefinition + matching SetNutsBolts
records) into a normalized, render-ready structure describing the anchor:
rod, thread zone, top hardware (nuts/washers above the concrete surface),
concrete top plane, and the bottom termination (plain end, hex head, or hook).

IMPORTANT — interpretation notes (unverified against a live Advance Steel
install; see AGENTS.md "verified vs assumed"). All assumptions below are
encoded in one place (partition_components / build_anchor_layout) so they can
be corrected once verified, and flagged to the user as notes:
- AnchorsDefinition.Length is treated as the overall rod length; the rod is
  drawn from y = 0 (bottom end) to y = Length.
- The concrete/top surface plane is drawn at Length - TopDistance when
  0 < TopDistance < Length. ThreadLength is drawn from the rod top downward.
- AnchorsName component slots (DINn / Diametern / Materialn / Positionn) link
  to SetNutsBolts records. Slot order is the catalog authoring order; this
  module keeps that order when stacking hardware (it does NOT re-order by the
  Position magnitude, whose meaning is not yet confirmed).
- Components with Position < 0 are stacked at the bottom (embedded) end;
  components with Position >= 0 or unknown sit at the top (thread) end.
- Bottom terminations: HookRadius > 0 -> a schematic J-hook below the rod;
  HeadDiameter > 0 -> a polygonal head at the rod bottom; otherwise the rod
  end is plain.
No SQL is ever written by this module.
"""

from utils import db as dbcore
from utils import bolt_sets as bs

# Geometric fields on AnchorsDefinition that are meaningful but not drawn;
# shown in the geometry summary with these labels.
DISTANCE_FIELDS = [
    ("TopDistance", "Top distance"),
    ("DistanceA", "Distance A"),
    ("DistanceE", "Distance E"),
    ("DistanceF", "Distance F"),
    ("DistanceO", "Distance O"),
    ("DistanceC", "Distance C"),
    ("BottomDistance", "Bottom distance"),
]


def _round4(value):
    return None if value is None else round(float(value), 4)


def classify_termination(def_row: dict) -> dict:
    """What sits at the bottom (embedded) end of the rod."""
    hook = _round4(def_row.get("HookRadius"))
    head_w = _round4(def_row.get("HeadDiameter"))
    head_h = _round4(def_row.get("HeadHeight"))
    if hook and hook > 0:
        return {"kind": "hook", "hook_radius": hook}
    if head_w and head_w > 0:
        return {
            "kind": "head",
            "height": head_h or 0,
            "width": head_w,
            "corners": def_row.get("NumberOfHeadEdges") or 0,
        }
    return {"kind": "plain"}


def collect_distances(def_row: dict) -> list:
    """Present (label, mm) pairs for the geometry summary."""
    out = []
    for col, label in DISTANCE_FIELDS:
        val = def_row.get(col)
        if val is None or float(val) == 0:
            continue
        out.append({"field": col, "label": label, "value_mm": _round4(val)})
    return out


def split_sides(components: list) -> dict:
    """Top vs bottom (embedded) hardware stacks.

    Components with Position < 0 go to the bottom end; all others (including
    unpositioned slots) go to the top end. Catalog slot order is preserved
    within each stack. Returns {"top": [...], "bottom": [...], "notes": [...]}.
    """
    notes = []
    top = []
    bottom = []
    for c in components:
        if c.get("position") is not None and c["position"] < 0:
            bottom.append(c)
        else:
            top.append(c)
    if bottom and top:
        notes.append(
            "Hardware splits across the two ends using signed Position values "
            "(positive/unknown at the top, negative at the embedded end). This "
            "interpretation is unverified; slot order is kept as authored."
        )
    elif bottom and not top:
        notes.append("All components sit at the embedded (bottom) end of the anchor.")
    return {"top": top, "bottom": bottom, "notes": notes}


def build_anchor_layout(geometry: dict, top: list, bottom: list, bottom_start: float = 0.0) -> dict:
    """Place rod, thread zone, concrete plane, and hardware stacks.

    geometry must contain length (overall rod mm), thread_length, top_distance.
    Rod spans y in [0, length]. bottom_start offsets the bottom (embedded)
    hardware stack so it clears the bottom termination (e.g. a cast-in head).
    Returns:
    {"parts": [{...comp, side, layer, stack_bottom, stack_top}],
     "thread": {"top": y, "bottom": y},
     "concrete_y": y | None,
     "warnings": [{code, severity, values}]}
    """
    length = float(geometry["length"] or 0)
    thread_length = float(geometry.get("thread_length") or 0)
    top_distance = float(geometry.get("top_distance") or 0)
    warnings = []
    parts = []

    thread_top = length
    thread_bottom = length - thread_length
    if thread_length > length:
        warnings.append({
            "code": "thread_exceeds_length",
            "severity": "warning",
            "values": {"length_mm": length, "thread_mm": thread_length},
        })
        thread_bottom = 0.0

    concrete_y = None
    if 0 < top_distance < length:
        concrete_y = length - top_distance

    def place_side(side_components, start_from_tip):
        placed = []
        cursor = length if start_from_tip else bottom_start
        for c in side_components:
            height, schematic = bs.component_height_with_flag(c)
            if start_from_tip:
                cursor -= height
                bottom = cursor
            else:
                bottom = cursor
            placed.append((c, bottom, bottom + height, schematic))
            cursor = bottom + height if not start_from_tip else cursor
        return placed

    top_placed = place_side(top, start_from_tip=True)
    bottom_placed = place_side(bottom, start_from_tip=False)

    for layer, (c, bottom, top_y, schematic) in enumerate(bottom_placed):
        parts.append({**c, "side": "bottom", "layer": layer,
                      "stack_bottom": _round4(bottom), "stack_top": _round4(top_y),
                      "schematic_height": schematic})
    for layer, (c, bottom, top_y, schematic) in enumerate(reversed(top_placed)):
        # top parts are placed tip-downwards; assign layers bottom->top so
        # index 0 is the part closest to the concrete surface.
        parts.append({**c, "side": "top", "layer": layer,
                      "stack_bottom": _round4(bottom), "stack_top": _round4(top_y),
                      "schematic_height": schematic})

    if top_placed and concrete_y is not None:
        stack_bottom = min(b for _, b, _, _ in top_placed)
        if stack_bottom < concrete_y - 1.0:
            warnings.append({
                "code": "stack_below_concrete",
                "severity": "warning",
                "values": {"stack_mm": round(concrete_y - stack_bottom, 2)},
            })

    return {
        "parts": parts,
        "thread": {"top": _round4(thread_top), "bottom": _round4(max(thread_bottom, 0))},
        "concrete_y": _round4(concrete_y),
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# SQL-backed assembly of the full view model
# --------------------------------------------------------------------------

def get_anchor_options(database: str) -> list:
    """AnchorsName rows as selectable options (Standard/Material/Diameter/Set)."""
    conn, cur = dbcore.connect(database)
    cur.execute("""
        SELECT an.ID, an.Standard, an.MaterialKey, an.Diameter, an.SetName,
               an.NumItems, an.Explodable,
               (SELECT COUNT(*) FROM [AnchorsDefinition] d WHERE d.AnchorID = an.ID) AS def_count
        FROM [AnchorsName] an
        ORDER BY an.Standard, an.Diameter, an.SetName, an.ID
    """)
    rows = cur.fetchall()
    conn.close()
    options = []
    for r in rows:
        options.append({
            "anchor_id": r["ID"],
            "standard": r["Standard"],
            "material": r["MaterialKey"],
            "diameter": _round4(r["Diameter"]),
            "set_name": r["SetName"],
            "num_items": r["NumItems"],
            "def_count": r["def_count"],
        })
    return options


def get_anchor_lengths(database: str, anchor_id: int) -> list:
    """AnchorsDefinition rows (length variants) for one AnchorsName row."""
    conn, cur = dbcore.connect(database)
    cur.execute("""
        SELECT ID, Length, PartName, Weight FROM [AnchorsDefinition]
        WHERE AnchorID = %s ORDER BY Length
    """, (int(anchor_id),))
    rows = cur.fetchall()
    conn.close()
    return [{
        "def_id": r["ID"],
        "length_mm": _round4(r["Length"]),
        "part_name": r["PartName"],
        "weight": None if r["Weight"] is None else round(r["Weight"], 5),
    } for r in rows]


def _fetch_anchor_name(database: str, anchor_id: int) -> dict:
    conn, cur = dbcore.connect(database)
    cur.execute("SELECT * FROM [AnchorsName] WHERE ID = %s", (int(anchor_id),))
    row = cur.fetchone()
    conn.close()
    return row or {}


def _fetch_anchor_def(database: str, def_id: int) -> dict:
    conn, cur = dbcore.connect(database)
    cur.execute("SELECT * FROM [AnchorsDefinition] WHERE ID = %s", (int(def_id),))
    row = cur.fetchone()
    conn.close()
    return row or {}


def _fetch_nut_rows(database: str) -> list:
    conn, cur = dbcore.connect(database)
    cur.execute("SELECT * FROM [SetNutsBolts]")
    rows = cur.fetchall()
    conn.close()
    return rows


def anchor_view(database: str, anchor_id: int, def_id: int) -> dict:
    """Assemble the full read-only anchor view model for one selection."""
    tables = set(dbcore.list_tables(database))
    if "AnchorsName" not in tables or "AnchorsDefinition" not in tables:
        return {"ok": False, "error": "Database is not an anchor catalog (no AnchorsName/AnchorsDefinition)."}

    name = _fetch_anchor_name(database, anchor_id)
    if not name:
        return {"ok": False, "error": "No AnchorsName row matches that selection."}
    def_row = _fetch_anchor_def(database, def_id)
    if not def_row:
        return {"ok": False, "error": "No AnchorsDefinition row matches that length."}

    slots = bs.parse_component_slots(name, diameter_suffix="")
    nut_rows = _fetch_nut_rows(database)
    components = bs.annotate_components(slots, nut_rows)
    sides = split_sides(components)

    geometry = {
        "length": _round4(def_row.get("Length")),
        "thread_length": _round4(def_row.get("ThreadLength")),
        "top_distance": _round4(def_row.get("TopDistance")),
    }
    termination = classify_termination(def_row)
    bottom_start = termination["height"] if termination["kind"] == "head" else 0.0
    layout = build_anchor_layout(geometry, sides["top"], sides["bottom"], bottom_start=bottom_start)

    distances = collect_distances(def_row)

    warnings = []
    for part in layout["parts"]:
        if not part["matched"]:
            warnings.append({
                "code": "unmatched_component",
                "severity": "danger" if part["role"] != "part" else "warning",
                "values": {
                    "slot": part["slot"], "standard": part["din"],
                    "diameter_mm": part["diameter"],
                },
            })
    if any(p["schematic_height"] for p in layout["parts"]):
        warnings.append({
            "code": "schematic_height",
            "severity": "warning",
            "values": {},
        })
    warnings.extend(layout["warnings"])

    return {
        "ok": True,
        "database": database,
        "selection": {
            "anchor_id": anchor_id,
            "def_id": def_id,
            "standard": name.get("Standard"),
            "material": name.get("MaterialKey"),
            "diameter": _round4(name.get("Diameter")),
            "set_name": name.get("SetName"),
            "part_name": def_row.get("PartName"),
            "length": _round4(def_row.get("Length")),
        },
        "anchor": {
            "source": "AnchorsName",
            "standard": name.get("Standard"),
            "material": name.get("MaterialKey"),
            "diameter": _round4(name.get("Diameter")),
            "set_name": name.get("SetName"),
            "num_items": name.get("NumItems"),
            "explodable": bool(name.get("Explodable")),
            "class_id": name.get("ClassID"),
            "name": def_row.get("PartName"),
            "weight": None if def_row.get("Weight") is None else round(def_row.get("Weight"), 5),
        },
        "geometry": {
            "length_mm": geometry["length"],
            "thread_length_mm": geometry["thread_length"],
            "top_distance_mm": geometry["top_distance"],
            "termination": termination,
            "distances": distances,
        },
        "thread": layout["thread"],
        "concrete_y": layout["concrete_y"],
        "components": layout["parts"],
        "notes": [
            "Thread zone drawn from the rod top downward for the recorded ThreadLength.",
            "Concrete/surface plane drawn at Length minus TopDistance (when the value fits inside the rod).",
            "Bottom termination drawn from AnchorsDefinition (head/hook) fields.",
        ] + sides["notes"],
        "warnings": warnings,
    }
