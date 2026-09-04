# utils/fabrication.py
"""Printable anchor fabrication detail sheet (issue #2) - first vertical slice.

Produces a normalized, validated "detail sheet" model from an anchor catalog
view (utils/anchor_sets.py) plus user-entered title-block fields. The model is
shared by the browser (dimensioned SVG elevation + fabrication table) and any
later server-side PDF export.

US_Hooked_Anchors field mapping (verified against the checked-in sample)
--------------------------------------------------------------------------
| Detail                    | Source                                        |
| ------------------------- | --------------------------------------------- |
| Standard / family         | AnchorsName.Standard ("US Hooked Anchors")     |
| Diameter                  | AnchorsName.Diameter (mm; imperial nominal)    |
| Material / strength grade | AnchorsName.MaterialKey (e.g. "10.9")          |
| Part name                 | AnchorsDefinition.PartName                     |
| Overall length            | AnchorsDefinition.Length (mm)                  |
| Thread length (top)       | AnchorsDefinition.ThreadLength (mm)            |
| Top projection            | AnchorsDefinition.TopDistance (mm)             |
| Hook geometry             | AnchorsDefinition.HookRadius (mm)              |
| Hook leg / offsets        | AnchorsDefinition.DistanceA/F/E/O/C (reported  |
|                           | with their column label only - NOT drawn)      |
| Weight                    | AnchorsDefinition.Weight (kg)                  |
| Nut/washer hardware       | SetNutsBolts via AnchorsName.DINn/Diametern/   |
|                           | Materialn/Positionn component slots            |
| Hole/installation data    | AnchorsHoleDefinition (NULL in the sample;     |
|                           | shown as absent)                               |

The sheet never estimates a missing fabrication dimension: fields above are
the only ones drawn or printed numerically. If a required value is missing or
conflicting, validation flags it and the sheet is marked DRAFT / INCOMPLETE.

NOTE - like the viewers, the sheet draws hooked anchors as a 90-degree
L-shaped hook: the rod end turns through a quarter-round bend of radius
HookRadius and continues as a horizontal tail whose length is the
AnchorsDefinition.DistanceA value (observed to equal the third token of the
part name, e.g. "Hooked Anchor 1/2x6x1-1/2"). AnchorsDefinition.Length is
treated as the overall rod length. Those conventions are flagged on the
sheet and in anchor_sets.py.
"""

import html
import math
import re

MM_PER_IN = 25.4
INCH_DENOM = 16          # imperial display precision: nearest 1/16 in
EXACT_EPS = 1e-4         # tolerance for "exactly representable as fraction"

# Hard-required geometry (must be present and positive). "geometry" values
# come from the AnchorsDefinition row; diameter comes from AnchorsName.
REQUIRED_FIELDS = {
    "length_mm": "Overall length",
    "diameter": "Diameter",
}

SHEET_SIZES = {
    "letter": {"name": "US Letter", "w": 11.0, "h": 8.5},
    "11x17": {"name": "11 x 17", "w": 17.0, "h": 11.0},
}

# --------------------------------------------------------------------------
# Dimension formatting (tested)
# --------------------------------------------------------------------------

def trim_number(value: float, places: int = 4) -> str:
    """Trim trailing zeros; preserve source precision up to `places`."""
    if value is None:
        return ""
    text = f"{value:.{places}f}"
    text = text.rstrip("0").rstrip(".")
    return text if text not in ("", "-") else "0"


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def inch_fraction(mm_value: float, denom: int = INCH_DENOM) -> dict:
    """Convert mm to a reduced inch fraction (nearest `denom`).

    Returns {"whole": int, "num": int, "den": int, "exact": bool} where
    "exact" is False when the value is not exactly representable at the chosen
    denominator (display with an approximate marker).
    """
    raw = mm_value / MM_PER_IN
    exact_val = raw * denom
    rounded = int(math.floor(exact_val + 0.5))
    whole = rounded // denom
    num = rounded % denom
    if num:
        g = _gcd(num, denom)
        num //= g
        denom //= g
    else:
        denom = 1
    exact = abs(exact_val - rounded) <= EXACT_EPS
    return {"whole": whole, "num": num, "den": denom, "exact": exact}


def fraction_text(fr: dict) -> str:
    parts = []
    if fr["whole"]:
        parts.append(str(fr["whole"]))
    if fr["num"]:
        parts.append(f"{fr['num']}/{fr['den']}")
    return " ".join(parts) if parts else "0"


def format_in(mm_value: float) -> str:
    """Imperial display string with reduced fractions and approx marker."""
    if mm_value is None:
        return "\u2014"
    fr = inch_fraction(mm_value)
    text = fraction_text(fr)
    return f"\u2248 {text}" if not fr["exact"] else text


def format_mm(mm_value: float) -> str:
    return trim_number(mm_value) if mm_value is not None else "\u2014"


def format_dim(mm_value: float, mode: str = "imperial") -> dict:
    """One value formatted for all modes.

    Returns {"metric": "12.7", "imperial": "1/2", "dual": "1/2 in (12.7 mm)",
    "approx": bool} so the same numeric source drives every display mode.
    """
    mm = format_mm(mm_value)
    fr = inch_fraction(mm_value) if mm_value is not None else None
    imp = format_in(mm_value)
    approx = bool(fr and not fr["exact"]) if mm_value is not None else False
    dual = f"{imp} in ({mm} mm)" if mm_value is not None else "\u2014"
    return {"metric": mm, "imperial": imp, "dual": dual, "approx": approx}


def format_dim_text(mm_value: float, mode: str) -> str:
    """Convenience: the label string for the requested sheet mode."""
    d = format_dim(mm_value, mode)
    if mode == "metric":
        return d["metric"]
    if mode == "imperial":
        return d["imperial"]
    return d["dual"]


# --------------------------------------------------------------------------
# Filename + slug helpers (tested)
# --------------------------------------------------------------------------

FAMILY_SLUGS = {
    "US Hooked Anchors": "Hooked-Anchor",
    "US Threaded Anchors": "Threaded-Anchor",
    "US Headed Anchors": "Headed-Anchor",
    "HILTI HY 200 HAS-E": "HAS-E",
}


def family_slug(standard: str) -> str:
    if standard in FAMILY_SLUGS:
        return FAMILY_SLUGS[standard]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", standard or "").strip("-")
    return slug or "Anchor"


def size_slug(length_mm: float, diameter_mm: float) -> str:
    """e.g. 19.05 x 609.6 mm -> '3-4x24' style slug for filenames."""
    d = inch_fraction(diameter_mm)
    l = inch_fraction(length_mm)
    dia = fraction_text(d).replace("/", "-").replace(" ", "-")
    ln = fraction_text(l).replace("/", "-").replace(" ", "-")
    if dia == "0":
        dia = trim_number(diameter_mm)
    if ln == "0":
        ln = trim_number(length_mm)
    return f"{dia}x{ln}"


def sanitize_segment(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or ""))
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return text


def sheet_filename(project: str = "", job: str = "", anchor_mark: str = "",
                   standard: str = "", length_mm: float = None,
                   diameter_mm: float = None, revision: str = "",
                   draft: bool = False) -> str:
    """Meaningful, safe sheet filename, e.g.

    Job-2065_A1_Hooked-Anchor_3-4x24_Rev-0.pdf
    """
    parts = []
    for text in (job, anchor_mark):
        cleaned = sanitize_segment(text)
        if cleaned:
            parts.append(cleaned)
    family = family_slug(standard)
    if family:
        parts.append(family)
    if length_mm is not None and diameter_mm is not None:
        parts.append(size_slug(length_mm, diameter_mm))
    rev = sanitize_segment(revision or "")
    if rev:
        parts.append(f"Rev-{rev}")
    elif not draft:
        parts.append("Rev-0")
    if draft:
        parts.insert(0, "DRAFT")
    base = "_".join(parts) if parts else "Anchor-Detail"
    return f"{base}.pdf"


# --------------------------------------------------------------------------
# Validation (tested)
# --------------------------------------------------------------------------

def validate_sheet(view: dict) -> list:
    """Return a list of {level, code, message} issues.

    Any error-level issue marks the sheet DRAFT / INCOMPLETE.
    """
    issues = []
    if not view or not view.get("ok"):
        return [{"level": "error", "code": "no_record", "message": "Selected anchor record could not be loaded."}]

    geo = view.get("geometry") or {}
    anchor = view.get("anchor") or {}
    for key, label in REQUIRED_FIELDS.items():
        val = geo.get(key) if key in geo else anchor.get(key)
        if val is None or float(val) <= 0:
            issues.append({"level": "error", "code": f"missing_{key}",
                           "message": f"{label} is missing or not positive in the catalog record."})

    length = geo.get("length_mm")
    thread = geo.get("thread_length_mm")
    if thread and length and float(thread) > float(length):
        issues.append({"level": "error", "code": "thread_exceeds_length",
                       "message": "Thread length exceeds the overall anchor length."})

    term = geo.get("termination") or {}
    if term.get("kind") == "hook" and not (term.get("hook_radius") or 0) > 0:
        issues.append({"level": "error", "code": "missing_hook_radius",
                       "message": "Hooked anchor has no positive HookRadius to draw."})

    for part in view.get("components") or []:
        if not part.get("matched"):
            issues.append({"level": "error", "code": "unmatched_component",
                           "message": f"DIN{part.get('slot')} ({part.get('din')}) has no matching "
                                      "SetNutsBolts record."})

    # informational notes travel separately (view.notes), not as issues
    return issues


# --------------------------------------------------------------------------
# Sheet context assembly
# --------------------------------------------------------------------------

def hardware_schedule(view: dict) -> list:
    """Fabrication-table rows for nut/washer hardware with quantities.

    Rows are lettered A, B, ... in drawing order (top stack first, then the
    embedded-end stack) so the elevation can reference them.
    """
    rows = []
    counts = {}
    order = []
    for part in view.get("components") or []:
        key = (part.get("din"), part.get("material"), part.get("diameter"))
        if key not in counts:
            counts[key] = 0
            order.append((part, key))
        counts[key] += 1
    for idx, (part, key) in enumerate(order):
        count = counts[key]
        rows.append({
            "letter": chr(ord("A") + idx),
            "end": "top" if part.get("side") == "top" else "embedded",
            "description": part.get("name") or part.get("din") or "",
            "standard": part.get("din"),
            "material": part.get("material"),
            "diameter_mm": part.get("diameter"),
            "qty": count,
            "matched": bool(part.get("matched")),
        })
    return rows


def provenance(database: str, view: dict, as_version=None) -> dict:
    sel = view.get("selection") or {}
    return {
        "database": database,
        "anchor_id": sel.get("anchor_id"),
        "def_id": sel.get("def_id"),
        "source": f"AnchorsName.ID={sel.get('anchor_id')}, "
                  f"AnchorsDefinition.ID={sel.get('def_id')}",
        "as_version": as_version,
    }


# --------------------------------------------------------------------------
# Dimensioned SVG elevation (monochrome, print-safe)
# --------------------------------------------------------------------------

def _esc(text):
    return html.escape(str(text), quote=True)


def _px(scale, mm):
    return round(mm * scale, 2)


def generate_elevation_svg(view: dict, mode: str = "imperial", draw_h: int = 500) -> str:
    """Build a dimensioned anchor elevation as inline SVG.

    All numbers come from the validated view model (anchor_sets.py). The
    geometry is drawn from AnchorsDefinition.Length/ThreadLength/TopDistance/
    HookRadius and AnchorsName.Diameter; hardware boxes come from matched
    SetNutsBolts heights. Coordinates are computed here so the layout math can
    be unit-tested and no dimension is ever invented in the template.
    """
    geo = view["geometry"]
    L = float(geo.get("length_mm") or 0)
    dia = float(view["anchor"].get("diameter") or 0)
    rod_r = max(dia / 2, 0.1)
    term = geo.get("termination") or {"kind": "plain"}
    head_h = float(term.get("height") or 0) if term.get("kind") == "head" else 0.0
    hook_r = float(term.get("hook_radius") or 0) if term.get("kind") == "hook" else 0.0
    hook_leg = 0.0
    if hook_r:
        for d in geo.get("distances") or []:
            if d.get("field") == "DistanceA":
                hook_leg = float(d.get("value_mm") or 0)
                break
    # vertical extent of the drawn content (mm)
    if hook_r:
        # L-hook: quarter-round bend dips one radius below the rod end.
        ymin_mm = -(hook_r + rod_r)
    elif head_h:
        ymin_mm = 0.0  # head sits at the very bottom
    else:
        ymin_mm = -rod_r  # small clearance below a plain end
    ymax_mm = L

    # horizontal half-extent (mm)
    comp_half = 0.0
    for part in view.get("components") or []:
        w = float(part.get("width") or part.get("diameter") or 0)
        comp_half = max(comp_half, w / 2 if w else (dia * 1.1))
    hook_reach = (hook_r + hook_leg + rod_r) if hook_r else 0.0
    half_w = max(rod_r * 1.2, comp_half, hook_reach)
    conc_half = half_w * 1.9 if view.get("concrete_y") is not None else half_w

    scale = min(max((draw_h - 150) / max((ymax_mm - ymin_mm) or 1, 1), 0.8), 5.0)

    margin_top = 30
    margin_left = 46
    x_center = margin_left + half_w * scale + 10
    label_gap = 16  # px between dimension line and its text

    def px_y(y_mm):
        # y grows upward in the drawing; svg y grows downward.
        return margin_top + (ymax_mm - y_mm) * scale

    def px_x(x_mm):
        return x_center + x_mm * scale

    out = []
    add = out.append
    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(x_center + half_w * scale + 340)} {int(draw_h)}" '
        f'width="100%" role="img" aria-label="Anchor fabrication detail">')

    # ---- centreline ------------------------------------------------------
    y_cl_top = margin_top - 14
    y_cl_bot = px_y(ymin_mm) + 18
    add(f'<line x1="{x_center}" y1="{y_cl_top}" x2="{x_center}" y2="{y_cl_bot}" '
        f'stroke="#94a3b8" stroke-width="0.8" stroke-dasharray="5 4"/>')

    # ---- concrete plane --------------------------------------------------
    conc_y = view.get("concrete_y")
    if conc_y is not None and 0 < float(conc_y) < L:
        y = px_y(conc_y)
        add(f'<line x1="{px_x(-conc_half)}" y1="{y}" x2="{px_x(conc_half)}" y2="{y}" '
            f'stroke="#64748b" stroke-width="1.6" stroke-dasharray="10 3 2 3"/>')
        add(f'<text x="{px_x(-conc_half)}" y="{y - 5}" font-size="9" fill="#64748b" '
            f'text-anchor="start">concrete / top surface</text>')

    # ---- rod (rect between rod bottom and tip) ----------------------------
    rod_bot_mm = head_h
    add(f'<rect x="{px_x(-rod_r)}" y="{px_y(L)}" width="{rod_r * 2 * scale}" '
        f'height="{(L - rod_bot_mm) * scale}" fill="#f4f6f8" stroke="#1e293b" stroke-width="1.4"/>')

    # ---- thread zone (top) ------------------------------------------------
    t_top = L
    t_bot = max(float(view.get("thread", {}).get("bottom") or 0), rod_bot_mm)
    if t_top - t_bot > 0.5:
        add(f'<rect x="{px_x(-rod_r * 0.92)}" y="{px_y(t_top)}" width="{rod_r * 1.84 * scale}" '
            f'height="{(t_top - t_bot) * scale}" fill="none" stroke="#1e293b" stroke-width="0.6" '
            f'stroke-dasharray="2 2"/>')
        # thread hatch: short ticks across the zone
        ticks = min(90, max(2, int((t_top - t_bot) / max(dia * 0.35, 1.0))))
        for i in range(1, ticks + 1):
            y_mm = t_top - (t_top - t_bot) * i / (ticks + 1)
            add(f'<line x1="{px_x(-rod_r * 1.12)}" y1="{px_y(y_mm)}" x2="{px_x(rod_r * 1.12)}" '
                f'y2="{px_y(y_mm)}" stroke="#94a3b8" stroke-width="0.5"/>')

    # ---- bottom termination ------------------------------------------------
    if term.get("kind") == "head":
        hw = float(term.get("width") or dia * 2.2)
        add(f'<rect x="{px_x(-hw / 2)}" y="{px_y(head_h)}" width="{hw * scale}" '
            f'height="{head_h * scale}" fill="#dbe2ea" stroke="#1e293b" stroke-width="1.4"/>')
    elif term.get("kind") == "hook" and hook_r > 0:
        # L-hook: quarter-round bend (radius R) turning down-to-right from the
        # rod end, then a horizontal tail of length hook_leg (DistanceA).
        R = hook_r
        pts = [(0.0, 0.0)]
        for k in range(0, 21):
            theta = math.pi + (math.pi / 2) * k / 20  # pi -> 3pi/2
            pts.append((R * (1 + math.cos(theta)), R * math.sin(theta)))
        tip_x = R + hook_leg
        pts.append((tip_x, -R))
        path = " ".join(
            f"L {px_x(x)} {px_y(y)}" if i else f"M {px_x(x)} {px_y(y)}"
            for i, (x, y) in enumerate(pts)
        )
        add(f'<path d="{path}" fill="none" stroke="#1e293b" '
            f'stroke-width="{rod_r * 2 * scale}" stroke-linecap="round"/>')

    # ---- hardware parts (outlined boxes) -----------------------------------
    for part in view.get("components") or []:
        w = float(part.get("width") or part.get("diameter") or 0)
        half = (w / 2) if w else dia * 1.1
        y_bot = float(part["stack_bottom"])
        y_top = float(part["stack_top"])
        add(f'<rect x="{px_x(-half)}" y="{px_y(y_top)}" width="{half * 2 * scale}" '
            f'height="{(y_top - y_bot) * scale}" fill="#f4f6f8" stroke="#1e293b" stroke-width="1.3"/>')

    # letter labels (A, B, ...) matching the fabrication table
    slot_to_letter = {}
    for row in hardware_schedule(view):
        for part in view.get("components") or []:
            if part["slot"] in slot_to_letter:
                continue
            if (row["standard"], row["material"], row["diameter_mm"]) == \
               (part.get("din"), part.get("material"), part.get("diameter")):
                slot_to_letter[part["slot"]] = row["letter"]
                break
    for part in view.get("components") or []:
        letter = slot_to_letter.get(part["slot"])
        if not letter:
            continue
        mid = (float(part["stack_bottom"]) + float(part["stack_top"])) / 2
        w = float(part.get("width") or part.get("diameter") or 0)
        half = (w / 2) if w else dia * 1.1
        lx = px_x(half) + 8
        add(f'<text x="{lx}" y="{px_y(mid) + 4}" font-size="12" font-weight="bold" '
            f'fill="#1e293b" text-anchor="start">{letter}</text>')

    # ---- dimension lines (right side) --------------------------------------
    def dim_line(y1_mm, y2_mm, text, x_off=0):
        x = x_center + half_w * scale + 26 + x_off
        y1, y2 = px_y(y1_mm), px_y(y2_mm)
        add(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="#1e293b" stroke-width="0.9"/>')
        for yy in (y1, y2):
            add(f'<line x1="{x - 5}" y1="{yy}" x2="{x + 5}" y2="{yy}" stroke="#1e293b" stroke-width="0.9"/>')
        add(f'<text x="{x + label_gap}" y="{(y1 + y2) / 2 + 3}" font-size="11" '
            f'fill="#1e293b" text-anchor="start">{_esc(text)}</text>')
        return x

    dim_text = lambda mm: format_dim_text(mm, mode)
    add(f'<line x1="{x_center}" y1="{px_y(L)}" x2="{x_center + half_w * scale + 6}" '
        f'y2="{px_y(L)}" stroke="#94a3b8" stroke-width="0.7"/>')  # leader to rod tip

    x1 = dim_line(0, L, f"L = {dim_text(L)}")
    if t_top - t_bot > 0.5:
        dim_line(t_bot, t_top, f"thread = {dim_text(t_top - t_bot)}", x_off=26)
    if conc_y is not None and 0 < float(conc_y) < L:
        dim_line(float(conc_y), L, f"top projection = {dim_text(L - float(conc_y))}", x_off=52)
    # hook labels: bend radius near the bend, leg length under the tail
    if hook_r > 0:
        hy = px_y(-hook_r * 0.75)
        add(f'<text x="{px_x(hook_r * 0.5)}" y="{hy + 3}" font-size="11" fill="#1e293b" '
            f'text-anchor="middle">hook R = {dim_text(hook_r)}</text>')
        if hook_leg > 0:
            ly = px_y(-hook_r - rod_r - 4)
            add(f'<line x1="{px_x(hook_r)}" y1="{ly}" x2="{px_x(hook_r + hook_leg)}" y2="{ly}" '
                f'stroke="#1e293b" stroke-width="0.9"/>')
            add(f'<text x="{px_x(hook_r + hook_leg / 2)}" y="{ly + 3}" font-size="11" '
                f'fill="#1e293b" text-anchor="middle">leg A = {dim_text(hook_leg)}</text>')

    # diameter callout under the rod
    d_y = px_y(ymin_mm) + 22
    add(f'<line x1="{px_x(-rod_r)}" y1="{d_y}" x2="{px_x(rod_r)}" y2="{d_y}" '
        f'stroke="#1e293b" stroke-width="0.9"/>')
    add(f'<line x1="{px_x(-rod_r)}" y1="{d_y - 4}" x2="{px_x(-rod_r)}" y2="{d_y + 4}" stroke="#1e293b" stroke-width="0.9"/>')
    add(f'<line x1="{px_x(rod_r)}" y1="{d_y - 4}" x2="{px_x(rod_r)}" y2="{d_y + 4}" stroke="#1e293b" stroke-width="0.9"/>')
    add(f'<text x="{x_center}" y="{d_y + 16}" font-size="11" fill="#1e293b" text-anchor="middle">'
        f'&#8960; {dim_text(dia)}</text>')

    # approximated/mode note under the drawing
    note = ("Dimensions in mm" if mode == "metric"
            else "Dimensions in inches (fractions shown)" if mode == "imperial"
            else "Dimensions dual: inches (mm)")
    add(f'<text x="{x_center}" y="{d_y + 34}" font-size="9" fill="#64748b" text-anchor="middle">{_esc(note)}</text>')
    add(f'<text x="{x_center}" y="{d_y + 48}" font-size="9" fill="#64748b" text-anchor="middle">'
        '&#8800; marks approximate converted values</text>')

    add("</svg>")
    return "".join(out)
