# utils/bolt_profile.py
"""Dimensioned 2D elevation of a bolt-set assembly.

The Three.js viewer answers "what does it look like"; this profile answers
"what are the parts and how big is it". It is drawn from the same layout
numbers the 3D scene uses (build_layout / bolt-set-layout.js), so the picture
can never disagree with the model: the browser posts its current layout and
this module renders it.

Everything is schematic: inches are shown because the viewer displays inches,
the geometry keeps the catalog's millimetre proportions, and nothing here is a
manufacturing drawing.
"""

import html
import math

MM_PER_IN = 25.4

INK = "#212529"
MUTED = "#6c757d"
DIM = "#495057"
GRIP_FILL = "#dff1fb"
GRIP_EDGE = "#38bdf8"

ROLE_FILL = {
    "bolt": "#5c6f83",
    "nut": "#5b6ee1",
    "washer": "#e8a13c",
    "part": "#b48be0",
}

MAX_COMPONENTS = 12


def _esc(value):
    return html.escape("" if value is None else str(value), quote=False)


def _to_float(value, default=None):
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _num_slot(value):
    return f"{value:g}"


def _in(mm):
    """Millimetres as viewer-style inches, trailing zeros trimmed."""
    value = _to_float(mm, 0.0) / MM_PER_IN
    rounded = round(value, 3)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"


def _text(x, y, content, cls="bp-label", anchor="start"):
    return (
        f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">'
        f"{_esc(content)}</text>"
    )


def _line(x1, y1, x2, y2, cls="bp-dim"):
    return (
        f'<line class="{cls}" x1="{x1:.1f}" y1="{y1:.1f}" '
        f'x2="{x2:.1f}" y2="{y2:.1f}"/>'
    )


def _rect(x, y, width, height, cls="bp-part", extra=""):
    return (
        f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" '
        f'width="{max(width, 0.8):.1f}" height="{max(height, 0.8):.1f}" {extra}/>'
    )


def _bracket(x1, x2, y, label):
    tick = 4.0
    return [
        _line(x1, y - tick, x1, y + tick),
        _line(x2, y - tick, x2, y + tick),
        _line(x1, y, x2, y),
        _text((x1 + x2) / 2, y + 14, label, "bp-dim-label", "middle"),
    ]


def _wrap_label(text, limit):
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def profile_svg(view):
    """SVG elevation for a bolt_set_view() payload (also accepts a draft)."""
    view = view or {}
    bolt = view.get("bolt") or {}
    components = [c for c in (view.get("components") or []) if isinstance(c, dict)][:MAX_COMPONENTS]
    grip = view.get("grip") or {}

    length = max(_to_float(bolt.get("length"), 0.0) or 0.0, 0.0)
    head_h = max(_to_float(bolt.get("head_height"), 0.0) or 0.0, 0.0)
    head_w = max(_to_float(bolt.get("head_width"), 0.0) or 0.0, 0.0)
    diameter = max(_to_float(bolt.get("diameter"), 0.0) or 0.0, 0.0)

    total = length + head_h
    if total <= 0:
        return (
            '<svg class="bp-svg" viewBox="0 0 680 90" role="img" aria-label="Assembly profile" '
            'xmlns="http://www.w3.org/2000/svg">'
            + _text(8, 30, "No bolt record for this selection, so there is no profile to draw.", "bp-note")
            + "</svg>"
        )

    widths = [head_w or diameter * 2, diameter or 1.0]
    for c in components:
        widths.append(max(_to_float(c.get("width"), 0.0) or 0.0, _to_float(c.get("diameter"), 0.0) or 0.0))
    grip_w_mm = max(widths) * 1.15
    widths.append(grip_w_mm)
    tallest = max(max(widths), 1.0)

    left = 34.0
    draw_w = 600.0
    scale = draw_w / total
    scale = min(scale, 140.0 / tallest)
    axis_y = 24.0 + (tallest * scale) / 2 + 16

    parts = []
    drawn_w = total * scale
    x_head0 = left + max((draw_w - drawn_w) / 2, 0.0)
    x_face = x_head0 + head_h * scale
    x_tip = x_face + length * scale
    if bolt.get("name"):
        parts.append(_text(left, 14, _wrap_label(bolt.get("name"), 60), "bp-label"))

    parts.append(_line(x_head0 - 12, axis_y, x_tip + 20, axis_y, "bp-center"))

    if head_h > 0 and head_w > 0:
        hh = head_w * scale
        parts.append(_rect(x_head0, axis_y - hh / 2, head_h * scale, hh, "bp-head"))
        parts.append(_text(x_head0 + (head_h * scale) / 2, axis_y + 3.5, "head", "bp-inside", "middle"))

    shank_h = max((diameter or 1.0) * scale, 2.0)
    parts.append(_rect(x_face, axis_y - shank_h / 2, max(length * scale, 1.0), shank_h, "bp-shank"))

    grip_bottom = _to_float(grip.get("bottom"), 0.0) or 0.0
    grip_thickness = max(_to_float(grip.get("thickness"), 0.0) or 0.0, 0.0)
    if grip_thickness > 0:
        gx0 = x_face + grip_bottom * scale
        gx1 = x_face + (grip_bottom + grip_thickness) * scale
        gh = grip_w_mm * scale
        parts.append(_rect(gx0, axis_y - gh / 2, gx1 - gx0, gh, "bp-grip"))
        parts.append(_text((gx0 + gx1) / 2, axis_y + gh / 2 + 12, "clamped material", "bp-note", "middle"))

    unmatched_index = 0
    for i, c in enumerate(components):
        bottom = _to_float(c.get("stack_bottom"))
        top = _to_float(c.get("stack_top"))
        if bottom is None or top is None or top <= bottom:
            continue
        cx0 = x_face + bottom * scale
        cx1 = x_face + top * scale
        width_mm = max(_to_float(c.get("width"), 0.0) or 0.0, _to_float(c.get("diameter"), 0.0) or 0.0)
        ch = max(width_mm * scale, 3.0)
        role = str(c.get("role") or "part")
        matched = c.get("matched") is not False
        fill = ROLE_FILL.get(role, ROLE_FILL["part"])
        if matched:
            extra = f'fill="{fill}"'
            cls = "bp-part"
        else:
            unmatched_index += 1
            cls = "bp-part bp-unmatched"
            extra = f'fill="url(#bp-hatch-{unmatched_index})"'
            parts.append(
                f'<defs><pattern id="bp-hatch-{unmatched_index}" width="6" height="6" '
                f'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
                f'<rect width="6" height="6" fill="#fde8e8"/>'
                f'<line x1="0" y1="0" x2="0" y2="6" stroke="#e05d5d" stroke-width="1.6"/>'
                f"</pattern></defs>"
            )
        parts.append(_rect(cx0, axis_y - ch / 2, cx1 - cx0, ch, cls, extra))

        balloon_x = (cx0 + cx1) / 2
        row = i % 2
        balloon_y = axis_y - max(ch, shank_h) / 2 - 22 - row * 17
        parts.append(_line(balloon_x, balloon_y + 7, balloon_x, axis_y - ch / 2, "bp-leader"))
        parts.append(f'<circle class="bp-balloon" cx="{balloon_x:.1f}" cy="{balloon_y:.1f}" r="7.5"/>')
        parts.append(_text(balloon_x, balloon_y + 3.4, str(i + 1), "bp-balloon-text", "middle"))

    head_px = max(head_w * scale, 6.0)
    dim_y = axis_y + max(grip_w_mm * scale, head_px) / 2 + 26
    parts += _bracket(x_head0, x_tip, dim_y, f"overall {_in(total)} in")
    parts += _bracket(x_face, x_tip, dim_y + 22, f"shank under head {_in(length)} in")
    if grip_thickness > 0:
        gx0 = x_face + grip_bottom * scale
        gx1 = x_face + (grip_bottom + grip_thickness) * scale
        parts += _bracket(gx0, gx1, dim_y + 44, f"grip {_in(grip_thickness)} in")

    head_note = f"head {_in(head_w)} in across flats \u00d7 {_in(head_h)} in high"
    parts.append(_text(left, dim_y + 84, head_note, "bp-note"))
    parts.append(_text(left, dim_y + 98, f"shank \u2300 {_in(diameter)} in", "bp-note"))

    legend_top = dim_y + 120
    legend = []
    for i, c in enumerate(components):
        role = str(c.get("role") or "part")
        slot = _to_float(c.get("slot"))
        slot_txt = str(int(slot)) if slot is not None and slot == int(slot) else ("" if slot is None else _num_slot(slot))
        entry = (
            f"{i + 1}. DIN{slot_txt} · {role} · "
            f"{_wrap_label(c.get('standard') or c.get('din') or '?', 18)}"
        )
        height_mm = _to_float(c.get("height"))
        entry += f" · h {_in(height_mm)} in" if height_mm else " · no height"
        if c.get("matched") is False:
            entry += " · UNMATCHED"
        if c.get("schematic_height"):
            entry += " · schematic thickness"
        legend.append(entry)

    rows = max(1, math.ceil(len(legend) / 2))
    for i, entry in enumerate(legend):
        column = i // rows
        row = i % rows
        parts.append(_text(left + column * 300, legend_top + row * 14, entry, "bp-legend"))
    note_y = legend_top + rows * 14 + 10
    parts.append(
        _text(
            left,
            note_y,
            "Schematic from catalog records and shown in inches; not a manufacturing drawing. "
            "Side split from the Position sign is unverified.",
            "bp-note",
        )
    )
    height = note_y + 14

    return (
        f'<svg class="bp-svg" viewBox="0 0 680 {height:.0f}" role="img" '
        f'aria-label="Dimensioned assembly profile" xmlns="http://www.w3.org/2000/svg">'
        + "".join(parts)
        + "</svg>"
    )


def sanitize_layout(payload):
    """Whitelist the layout fields the browser may send to profile_svg().

    The sketch endpoint is read-only drawing, but the payload still comes from
    the network: keep only known keys, drop garbage numbers, clamp lengths.
    """
    payload = payload if isinstance(payload, dict) else {}
    bolt = payload.get("bolt") if isinstance(payload.get("bolt"), dict) else {}
    grip = payload.get("grip") if isinstance(payload.get("grip"), dict) else {}
    components = payload.get("components") if isinstance(payload.get("components"), list) else []

    def number(source, key, limit=1e6):
        value = _to_float(source.get(key))
        if value is None:
            return None
        return max(min(value, limit), -limit)

    clean_bolt = {
        "length": number(bolt, "length"),
        "head_height": number(bolt, "head_height"),
        "head_width": number(bolt, "head_width"),
        "diameter": number(bolt, "diameter"),
        "name": str(bolt.get("name") or "")[:64],
    }
    clean_grip = {
        "bottom": number(grip, "bottom"),
        "thickness": number(grip, "thickness"),
    }
    clean_components = []
    for item in components[:MAX_COMPONENTS]:
        if not isinstance(item, dict):
            continue
        clean_components.append({
            "slot": number(item, "slot", 99),
            "role": str(item.get("role") or "part")[:16],
            "standard": str(item.get("standard") or item.get("din") or "")[:32],
            "height": number(item, "height"),
            "width": number(item, "width"),
            "diameter": number(item, "diameter"),
            "stack_bottom": number(item, "stack_bottom"),
            "stack_top": number(item, "stack_top"),
            "matched": bool(item.get("matched", True)),
            "schematic_height": bool(item.get("schematic_height", False)),
        })
    return {"bolt": clean_bolt, "grip": clean_grip, "components": clean_components}
