# utils/dxf_compare.py
"""Compare two DXF exports of the same detail and explain the hand edits.

This is Phase 1 of issue #15: the read-only half. Given the same detail
exported twice (once as the drawing style generated it, once after it was
hand-edited) and optionally the style export that produced it, the module
reports what changed on the sheet and which style setting could reproduce it,
or why no style setting can.

What is compared:

* what was added, removed, moved or changed;
* whether each entity came from Advance Steel or from hand editing;
* each dimension edit as an intent: which feature it lands on, which way it
  runs, which side, and whether it is a chain or a single dimension;
* the style surface that owns that kind of change (dimension strategy,
  representation rules, label strategy, title, scale, view arrangement);
* existing style requests that already describe the same intent, so a change
  can reuse a request instead of adding one.

What is deliberately ignored: text content (part marks, m-numbers), dimension
values, and anything that is not a drawing style setting. Text height, arrow
sizes, dimension text style and layer colours belong to the drawing defaults
or the DWG prototype, so they are reported as "not a style change".

All Advance Steel readings are marked with a basis. Layer role, origin and
feature names are inferred from geometry and layer names, never from a guessed
Advance Steel enum label. The module is read-only: it parses uploaded text and
returns a dictionary. Phase 2 (apply to a copy and regenerate) stays blocked
until verification A4 (and a real pair under A7) in
``docs/verification-log.md`` passes.
"""

import math
import re
from collections import Counter, defaultdict

from utils import dim_explain, style_usage

MAX_DXF_BYTES = 64 * 1024 * 1024

# Layer prefixes Advance Steel uses for its own drawing entities. A layer
# outside this set that is not 0/empty is treated as hand editing. This is an
# inference, not a verified list; the report names the rule and the raw layer.
AS_LAYER_PREFIXES = ("AS_", "AS-", "ADVANCE", "ASTOR")
NATIVE_PROXY_TYPES = {"ACAD_PROXY_ENTITY", "ACAD_PROXY_OBJECT"}

DIMENSION_TYPES = {"DIMENSION", "ARC_DIMENSION", "RADIAL_DIMENSION",
                   "DIAMETRIC_DIMENSION", "ORDINATE_DIMENSION", "ALIGNED_DIMENSION"}
TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF", "MLEADER", "LEADER", "TOLERANCE"}
CONTOUR_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE",
                 "SPLINE", "3DFACE", "SOLID"}
HATCH_TYPES = {"HATCH"}

DIM_SUBTYPES = {
    0: "rotated, horizontal or vertical",
    1: "aligned",
    2: "angular",
    3: "diameter",
    4: "radius",
    5: "angular (three point)",
    6: "ordinate",
}

UNIT_NAMES = {
    0: None, 1: "inches", 2: "feet", 3: "miles", 4: "millimetres",
    5: "centimetres", 6: "metres", 7: "kilometres", 8: "microinches",
    9: "mils", 10: "yards", 11: "angstroms", 12: "nanometres",
    13: "microns", 14: "decimetres", 15: "decametres", 16: "hectometres",
    17: "gigametres", 18: "astronomical units", 19: "light years",
    20: "parsecs",
}

# Layer name tokens, checked in this order. The role then refines the entity
# type: a LINE on a CENTER layer is an axis, a HATCH on a HATCH layer is a
# hatch, a TEXT on a TITLE layer is title text.
LAYER_ROLE_HINTS = (
    ("dimension", ("DIM", "DIMS", "DIMENSION", "DIMENSIONS")),
    ("axis", ("CENTER", "CENTRE", "CENTERS", "CENTRES", "AXIS", "AXES")),
    ("hatch", ("HATCH", "HATCHES", "FILL", "SHADE")),
    ("title", ("TITLE", "FRAME", "BORDER", "SHEET")),
    ("label", ("TEXT", "LABEL", "MARK", "ANNO", "ANNOTATION", "TAG", "NOTE")),
    ("contour", ("CONTOUR", "VISIBLE", "OUTLINE", "PROFILE", "OBJECT",
                 "HIDDEN", "DASHED")),
)

ANGLE_TOLERANCE = 2.0


class DxfError(ValueError):
    """The uploaded file cannot be read as an ASCII DXF."""


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def _decode(source):
    if isinstance(source, bytes):
        if source.startswith(b"AutoCAD Binary DXF"):
            raise DxfError("This is a binary DXF. Export an ASCII DXF and try again.")
        return source.decode("utf-8", errors="replace")
    if not isinstance(source, str):
        raise DxfError("The DXF content must be text or bytes.")
    if source.startswith("AutoCAD Binary DXF"):
        raise DxfError("This is a binary DXF. Export an ASCII DXF and try again.")
    return source


def _pairs(text):
    """Read DXF group-code/value pairs. The value is kept intact."""
    lines = text.splitlines()
    if len(lines) < 2:
        raise DxfError("The file is too short to be a DXF.")
    pairs = []
    index = 0
    while index + 1 < len(lines):
        raw_code = lines[index].strip()
        if not raw_code:
            index += 1
            continue
        try:
            code = int(raw_code)
        except ValueError as exc:
            raise DxfError(
                f"Group code {raw_code!r} is not a number near line {index + 1}."
            ) from exc
        pairs.append((code, lines[index + 1]))
        index += 2
    if not pairs:
        raise DxfError("The file contains no DXF group codes.")
    return pairs


def _sections(pairs):
    index = 0
    while index < len(pairs):
        code, value = pairs[index]
        if code == 0 and value.strip().upper() == "SECTION":
            name = ""
            if index + 1 < len(pairs) and pairs[index + 1][0] == 2:
                name = pairs[index + 1][1].strip().upper()
                index += 2
            else:
                index += 1
            body = []
            while index < len(pairs) and not (
                    pairs[index][0] == 0 and pairs[index][1].strip().upper() == "ENDSEC"):
                body.append(pairs[index])
                index += 1
            yield name, body
        index += 1


def _first_text(fields, code):
    for group, value in fields:
        if group == code:
            return value.strip()
    return None


def _first_int(fields, code, default=None):
    for group, value in fields:
        if group == code:
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return default
    return default


def _first_num(fields, code, default=None):
    for group, value in fields:
        if group == code:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default
    return default


def _parse_header(body):
    variables = {}
    current = None
    for code, value in body:
        if code == 9:
            current = value.strip().upper()
            variables.setdefault(current, [])
        elif current is not None:
            variables[current].append((code, value))

    def number(name, code, default=None):
        for group, value in variables.get(name, ()):
            if group == code:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return default
        return default

    def text(name, code):
        for group, value in variables.get(name, ()):
            if group == code:
                return value.strip()
        return None

    units_code = number("$INSUNITS", 70)
    units_code = int(units_code) if units_code is not None else None
    measurement = number("$MEASUREMENT", 70)
    extents = {}
    for axis, code in (("x", 10), ("y", 20)):
        low = number("$EXTMIN", code)
        high = number("$EXTMAX", code)
        if low is not None and high is not None:
            extents[axis] = (low, high)
    return {
        "acadver": text("$ACADVER", 1),
        "units_code": units_code,
        "units_name": UNIT_NAMES.get(units_code),
        "measurement": int(measurement) if measurement is not None else None,
        "dimscale": number("$DIMSCALE", 40),
        "extents": extents,
    }


def _parse_tables(body):
    layers = {}
    dimstyles = {}
    index = 0
    while index < len(body):
        if body[index][0] != 0 or body[index][1].strip().upper() != "TABLE":
            index += 1
            continue
        name = ""
        if index + 1 < len(body) and body[index + 1][0] == 2:
            name = body[index + 1][1].strip().upper()
        index += 2
        records = []
        while index < len(body) and not (
                body[index][0] == 0 and body[index][1].strip().upper() == "ENDTAB"):
            if body[index][0] == 0:
                record_type = body[index][1].strip().upper()
                index += 1
                record = []
                while index < len(body) and body[index][0] != 0:
                    record.append(body[index])
                    index += 1
                records.append((record_type, record))
            else:
                index += 1
        index += 1
        if name == "LAYER":
            for record_type, record in records:
                if record_type != "LAYER":
                    continue
                layer_name = _first_text(record, 2)
                if not layer_name:
                    continue
                layers[layer_name.upper()] = {
                    "name": layer_name,
                    "color": _first_int(record, 62),
                    "linetype": _first_text(record, 6),
                    "flags": _first_int(record, 70),
                }
        elif name == "DIMSTYLE":
            for record_type, record in records:
                if record_type != "DIMSTYLE":
                    continue
                style_name = _first_text(record, 2)
                if not style_name:
                    continue
                dimstyles[style_name.upper()] = {
                    "name": style_name,
                    "arrow_size": _first_num(record, 41),
                    "text_height": _first_num(record, 140),
                    "extension_offset": _first_num(record, 43),
                    "extension_beyond": _first_num(record, 44),
                    "gap": _first_num(record, 147),
                    "scale": _first_num(record, 40),
                }
    return layers, dimstyles


def _parse_blocks(body):
    names = []
    index = 0
    while index < len(body):
        if body[index][0] == 0 and body[index][1].strip().upper() == "BLOCK":
            index += 1
            record = []
            while index < len(body) and body[index][0] != 0:
                record.append(body[index])
                index += 1
            name = _first_text(record, 2) or _first_text(record, 3)
            if name:
                names.append(name)
        else:
            index += 1
    return names


def _parse_entity_records(body):
    records = []
    index = 0
    while index < len(body):
        if body[index][0] == 0:
            entity_type = body[index][1].strip().upper()
            index += 1
            fields = []
            while index < len(body) and body[index][0] != 0:
                fields.append(body[index])
                index += 1
            records.append((entity_type, fields))
        else:
            index += 1
    return records


def _merge_polylines(records):
    merged = []
    current = None
    for entity_type, fields in records:
        if entity_type == "POLYLINE":
            current = {"type": "POLYLINE", "fields": fields, "vertices": []}
            merged.append(current)
        elif entity_type == "VERTEX":
            if current is not None:
                point = _xy_point(fields, 10, 20)
                if point:
                    current["vertices"].append(point)
        elif entity_type == "SEQEND":
            current = None
        else:
            if entity_type in {"ATTRIB", "ATTDEF"}:
                # attributes belong to the preceding INSERT; keep them visible
                # as labels instead of dropping their text silently.
                merged.append({"type": entity_type, "fields": fields})
                continue
            current = None
            merged.append({"type": entity_type, "fields": fields})
    return merged


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _xy_point(fields, x_code=10, y_code=20):
    x = _first_num(fields, x_code)
    y = _first_num(fields, y_code)
    if x is None or y is None:
        return None
    return [x, y]


def _xy_sequence(fields, stop_at=None):
    points = []
    x = None
    for code, value in fields:
        if stop_at is not None and code == stop_at:
            break
        if code == 10:
            x = _num(value)
        elif code == 20 and x is not None:
            y = _num(value)
            if y is not None:
                points.append([x, y])
            x = None
    return points


def _lwpoly_points(fields):
    points = []
    x = None
    for code, value in fields:
        if code == 10:
            x = _num(value)
        elif code == 20 and x is not None:
            y = _num(value)
            if y is not None:
                points.append([x, y])
            x = None
        elif code not in (40, 41, 42, 90, 70):
            x = None
    return points


def _bbox(points):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {"min": [min(xs), min(ys)], "max": [max(xs), max(ys)]}


def _bbox_center(bbox):
    if not bbox:
        return None
    return [(bbox["min"][0] + bbox["max"][0]) / 2.0,
            (bbox["min"][1] + bbox["max"][1]) / 2.0]


def _union_bbox(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return {
        "min": [min(b["min"][0] for b in boxes), min(b["min"][1] for b in boxes)],
        "max": [max(b["max"][0] for b in boxes), max(b["max"][1] for b in boxes)],
    }


def _segments_from_points(points, closed=False):
    segments = []
    for first, second in zip(points, points[1:]):
        segments.append((first, second))
    if closed and len(points) > 2:
        segments.append((points[-1], points[0]))
    return segments


def _segments_length(segments):
    total = 0.0
    for (x1, y1), (x2, y2) in segments:
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def _angle_bucket(angle):
    angle = angle % 180.0
    if angle < ANGLE_TOLERANCE or angle > 180.0 - ANGLE_TOLERANCE:
        return "horizontal", angle
    if abs(angle - 90.0) < ANGLE_TOLERANCE:
        return "vertical", angle
    return "sloped", angle


def _orientation_from_angle(angle, basis="geometry"):
    if angle is None:
        return {"bucket": "unknown", "degrees": None, "slope": None, "basis": basis}
    bucket, normalised = _angle_bucket(angle)
    slope = None
    if bucket == "sloped":
        slope = "ascending" if normalised < 90.0 else "descending"
    return {"bucket": bucket, "degrees": round(normalised, 2), "slope": slope,
            "basis": basis}


def _dominant_segment(segments):
    best = None
    length = 0.0
    for first, second in segments:
        size = math.hypot(second[0] - first[0], second[1] - first[1])
        if size > length:
            length = size
            best = (first, second)
    return best


def _orientation_from_points(points, closed=False):
    segment = _dominant_segment(_segments_from_points(points, closed))
    if not segment:
        return {"bucket": "unknown", "degrees": None, "slope": None,
                "basis": "geometry"}
    angle = math.degrees(math.atan2(segment[1][1] - segment[0][1],
                                    segment[1][0] - segment[0][0]))
    return _orientation_from_angle(angle)


def _sample_arc(center, radius, start_deg, end_deg, steps=32):
    sweep = (end_deg - start_deg) % 360.0
    if sweep == 0.0:
        sweep = 360.0
    points = []
    for step in range(steps + 1):
        angle = math.radians(start_deg + sweep * step / steps)
        points.append([center[0] + radius * math.cos(angle),
                       center[1] + radius * math.sin(angle)])
    return points


def _sample_ellipse(center, major, ratio, start=0.0, end=2.0 * math.pi):
    rx = math.hypot(major[0], major[1])
    ry = rx * (ratio if ratio is not None else 1.0)
    rotation = math.atan2(major[1], major[0])
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    points = []
    steps = 48
    for step in range(steps + 1):
        angle = start + (end - start) * step / steps
        x = rx * math.cos(angle)
        y = ry * math.sin(angle)
        points.append([center[0] + x * cos_r - y * sin_r,
                       center[1] + x * sin_r + y * cos_r])
    return points


def _perimeter(points, closed=False):
    return _segments_length(_segments_from_points(points, closed))


def _build_entity(entity_type, fields, vertices=None):
    entity = {
        "type": entity_type,
        "layer": (_first_text(fields, 8) or "0"),
        "linetype": _first_text(fields, 6),
        "handle": _first_text(fields, 5),
        "color": _first_int(fields, 62),
        "block": _first_text(fields, 2) if entity_type in {"INSERT", "DIMENSION"} else None,
        "dimstyle": _first_text(fields, 3) if entity_type in DIMENSION_TYPES else None,
        "subtype": _first_int(fields, 70) if entity_type in DIMENSION_TYPES else None,
        "text": None,
        "height": None,
        "rotation": None,
        "pattern": None,
        "xdata_apps": [v.strip() for c, v in fields if c == 1001],
        "points": [],
        "segments": [],
        "bbox": None,
        "anchor": None,
        "landing": [],
        "span": None,
        "length": None,
        "orientation": {"bucket": "unknown", "degrees": None, "slope": None,
                        "basis": "geometry"},
        "closed": False,
    }
    if entity_type in DIMENSION_TYPES and entity["subtype"] is not None:
        entity["subtype"] &= 15

    if entity_type == "LINE":
        first = _xy_point(fields, 10, 20)
        second = _xy_point(fields, 11, 21)
        entity["points"] = [p for p in (first, second) if p]
        if first and second:
            entity["segments"] = [(first, second)]
    elif entity_type == "LWPOLYLINE":
        points = _lwpoly_points(fields)
        closed = bool((_first_int(fields, 70, 0) or 0) & 1)
        entity["points"] = points
        entity["closed"] = closed
        entity["segments"] = _segments_from_points(points, closed)
    elif entity_type == "POLYLINE":
        points = list(vertices or [])
        closed = bool((_first_int(fields, 70, 0) or 0) & 1)
        entity["points"] = points
        entity["closed"] = closed
        entity["segments"] = _segments_from_points(points, closed)
    elif entity_type == "CIRCLE":
        center = _xy_point(fields, 10, 20)
        radius = _first_num(fields, 40)
        if center and radius:
            entity["points"] = _sample_arc(center, radius, 0.0, 360.0, steps=32)
            entity["segments"] = _segments_from_points(entity["points"], True)
            entity["bbox"] = {"min": [center[0] - radius, center[1] - radius],
                              "max": [center[0] + radius, center[1] + radius]}
            entity["anchor"] = center
            entity["orientation"] = {"bucket": "round", "degrees": None,
                                     "slope": None, "basis": "geometry"}
            entity["length"] = 2.0 * math.pi * radius
            entity["closed"] = True
    elif entity_type == "ARC":
        center = _xy_point(fields, 10, 20)
        radius = _first_num(fields, 40)
        start = _first_num(fields, 50, 0.0)
        end = _first_num(fields, 51, 0.0)
        if center and radius:
            entity["points"] = _sample_arc(center, radius, start, end)
            entity["segments"] = _segments_from_points(entity["points"])
            sweep = (end - start) % 360.0 or 360.0
            entity["length"] = math.radians(sweep) * radius
    elif entity_type == "ELLIPSE":
        center = _xy_point(fields, 10, 20)
        major = _xy_point(fields, 11, 21)
        ratio = _first_num(fields, 40, 1.0)
        start = _first_num(fields, 41, 0.0)
        end = _first_num(fields, 42, 2.0 * math.pi)
        if center and major:
            entity["points"] = _sample_ellipse(center, major, ratio, start, end)
            entity["segments"] = _segments_from_points(entity["points"])
            entity["length"] = _perimeter(entity["points"])
    elif entity_type == "INSERT":
        entity["anchor"] = _xy_point(fields, 10, 20)
        entity["points"] = [entity["anchor"]] if entity["anchor"] else []
        entity["rotation"] = _first_num(fields, 50, 0.0)
    elif entity_type in DIMENSION_TYPES:
        definition = _xy_point(fields, 10, 20)
        first = _xy_point(fields, 13, 23)
        second = _xy_point(fields, 14, 24)
        entity["points"] = [p for p in (definition, first, second) if p]
        entity["landing"] = [p for p in (first, second) if p]
        entity["anchor"] = definition or (_bbox_center(_bbox(entity["landing"]))
                                          if entity["landing"] else None)
        if first and second:
            entity["span"] = math.hypot(second[0] - first[0], second[1] - first[1])
            angle = math.degrees(math.atan2(second[1] - first[1],
                                            second[0] - first[0]))
            entity["orientation"] = _orientation_from_angle(angle)
        else:
            rotation = _first_num(fields, 50)
            entity["orientation"] = _orientation_from_angle(rotation)
    elif entity_type in {"TEXT", "ATTRIB", "ATTDEF"}:
        entity["text"] = _first_text(fields, 1)
        entity["height"] = _first_num(fields, 40)
        entity["rotation"] = _first_num(fields, 50, 0.0)
        anchor = _xy_point(fields, 11, 21) or _xy_point(fields, 10, 20)
        entity["anchor"] = anchor
        entity["points"] = [anchor] if anchor else []
        entity["orientation"] = _orientation_from_angle(entity["rotation"])
    elif entity_type in {"MTEXT", "MLEADER"}:
        entity["text"] = "".join(v for c, v in fields if c in (1, 3)).strip() or None
        entity["height"] = _first_num(fields, 40)
        entity["rotation"] = _first_num(fields, 50, 0.0)
        anchor = _xy_point(fields, 10, 20)
        entity["anchor"] = anchor
        entity["points"] = [anchor] if anchor else []
        entity["orientation"] = _orientation_from_angle(entity["rotation"])
    elif entity_type == "HATCH":
        entity["pattern"] = _first_text(fields, 2)
        entity["points"] = _xy_sequence(fields, stop_at=98)
        entity["segments"] = _segments_from_points(entity["points"], True)
    elif entity_type == "LEADER":
        entity["points"] = _xy_sequence(fields)
        entity["anchor"] = entity["points"][0] if entity["points"] else None
        entity["segments"] = _segments_from_points(entity["points"])
        entity["orientation"] = _orientation_from_points(entity["points"])
    elif entity_type in {"SOLID", "3DFACE"}:
        entity["points"] = [p for p in (
            _xy_point(fields, 10, 20), _xy_point(fields, 11, 21),
            _xy_point(fields, 12, 22), _xy_point(fields, 13, 23)) if p]
        entity["segments"] = _segments_from_points(entity["points"], True)
    elif entity_type == "SPLINE":
        entity["points"] = _xy_sequence(fields)
        entity["segments"] = _segments_from_points(entity["points"])
    elif entity_type == "POINT":
        entity["anchor"] = _xy_point(fields, 10, 20)
        entity["points"] = [entity["anchor"]] if entity["anchor"] else []
    else:
        entity["points"] = _xy_sequence(fields)
        entity["segments"] = _segments_from_points(entity["points"])

    if entity["bbox"] is None:
        entity["bbox"] = _bbox(entity["points"])
    if entity["anchor"] is None and entity["bbox"]:
        entity["anchor"] = _bbox_center(entity["bbox"])
    if entity["length"] is None and entity["segments"]:
        entity["length"] = _segments_length(entity["segments"])
    if entity["orientation"]["bucket"] == "unknown" and entity["segments"]:
        entity["orientation"] = _orientation_from_points(entity["points"],
                                                        entity["closed"])
    return entity


def _layer_role(layer):
    tokens = [t for t in re.split(r"[^A-Z0-9]+", str(layer or "").upper()) if t]
    for role, keys in LAYER_ROLE_HINTS:
        for key in keys:
            if any(token == key or token.startswith(key) for token in tokens):
                return role
    return None


def _type_kind(entity_type):
    if entity_type in DIMENSION_TYPES:
        return "dimension"
    if entity_type in TEXT_TYPES:
        return "label"
    if entity_type in HATCH_TYPES:
        return "hatch"
    if entity_type in CONTOUR_TYPES:
        return "contour"
    return "other"


def _classify(entity):
    role = _layer_role(entity["layer"])
    kind = _type_kind(entity["type"])
    kind_basis = "entity type"
    if kind == "contour" and role == "axis":
        kind, kind_basis = "axis", "layer name"
    elif kind == "contour" and role == "hatch":
        kind, kind_basis = "hatch", "layer name"
    elif kind == "label" and role == "title":
        kind, kind_basis = "title", "layer name"
    elif kind == "contour" and role == "title":
        kind, kind_basis = "frame", "layer name"
    elif role == "dimension" and kind in {"contour", "label"}:
        # An exploded AS dimension: the geometry/text sits on a dimension layer
        # instead of being a DIMENSION entity. It is still a dimension-strategy
        # edit, not a representation-rule edit.
        kind, kind_basis = "dimension geometry", "layer name"
    elif kind == "other" and role == "title":
        kind, kind_basis = "frame", "layer name"
    elif kind == "other" and role:
        kind, kind_basis = role, "layer name"

    block = (entity.get("block") or "").upper()
    if kind != "title" and any(word in block for word in ("TITLE", "FRAME", "BORDER", "SHEET")):
        kind, kind_basis = "title", "block name"

    layer = str(entity["layer"] or "").upper()
    xdata = entity.get("xdata_apps") or []
    if any(_as_xdata_app(name) for name in xdata):
        origin, origin_basis = "generated", "AS XDATA"
    elif any(layer.startswith(prefix) for prefix in AS_LAYER_PREFIXES):
        origin, origin_basis = "generated", "AS layer prefix"
    elif entity["type"] in NATIVE_PROXY_TYPES:
        origin, origin_basis = "generated", "proxy entity"
    elif layer in {"", "0"}:
        origin, origin_basis = "unknown", "no AS marker on layer 0"
    elif entity["type"] in DIMENSION_TYPES | TEXT_TYPES:
        origin, origin_basis = "hand", "plain AutoCAD object on a non-AS layer"
    else:
        origin, origin_basis = "hand", "non-AS layer"
    return kind, kind_basis, origin, origin_basis


def _as_xdata_app(name):
    text = str(name or "").strip().upper()
    return text.startswith(("AS_", "AS-", "AS ", "ASTOR", "ADVANCE", "ACADAS"))


def read_dxf(source):
    """Parse an ASCII DXF into entities with kind and origin classifications."""
    text = _decode(source)
    pairs = _pairs(text)
    header = {}
    layers = {}
    dimstyles = {}
    blocks = []
    entities = []
    found = set()
    for name, body in _sections(pairs):
        found.add(name)
        if name == "HEADER":
            header = _parse_header(body)
        elif name == "TABLES":
            layers, dimstyles = _parse_tables(body)
        elif name == "BLOCKS":
            blocks = _parse_blocks(body)
        elif name == "ENTITIES":
            for record in _merge_polylines(_parse_entity_records(body)):
                entity = _build_entity(record["type"], record["fields"],
                                       record.get("vertices"))
                (entity["kind"], entity["kind_basis"],
                 entity["origin"], entity["origin_basis"]) = _classify(entity)
                entities.append(entity)

    warnings = []
    if "ENTITIES" not in found:
        warnings.append("The file has no ENTITIES section.")
    if not entities:
        warnings.append("No drawing entities were found in the file.")
    units_name = header.get("units_name")
    if header.get("units_code") in (None, 0):
        warnings.append(
            "The header does not state drawing units ($INSUNITS is missing or 0); "
            "distances are reported in drawing units.")
    counts = {
        "by_kind": dict(Counter(e["kind"] for e in entities)),
        "by_origin": dict(Counter(e["origin"] for e in entities)),
        "by_layer": dict(Counter(e["layer"] for e in entities)),
    }
    return {
        "acadver": header.get("acadver"),
        "units": {
            "code": header.get("units_code"),
            "name": units_name,
            "metric": (True if header.get("measurement") == 1 else
                       False if header.get("measurement") == 0 else None),
        },
        "layers": layers,
        "dimstyles": dimstyles,
        "blocks": blocks,
        "entities": entities,
        "bounds": _union_bbox([e["bbox"] for e in entities]),
        "counts": counts,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _clean(value, digits=3):
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return round(value, digits)
    if isinstance(value, (list, tuple)):
        return [_clean(item, digits) for item in value]
    if isinstance(value, dict):
        return {key: _clean(item, digits) for key, item in value.items()}
    return value


def _distance(first, second):
    return math.hypot(second[0] - first[0], second[1] - first[1])


def _bucket(entity):
    return (entity.get("orientation") or {}).get("bucket") or "unknown"


def _ratio_close(first, second, tolerance):
    if not first or not second:
        return True
    return abs(first - second) / max(abs(first), abs(second)) <= tolerance


def _span_ratio(before, after):
    if not before.get("span") or not after.get("span"):
        return None
    return after["span"] / before["span"]


def _diagonal(bounds):
    if not bounds:
        return 0.0
    return math.hypot(bounds["max"][0] - bounds["min"][0],
                      bounds["max"][1] - bounds["min"][1])


def _median(values):
    values = sorted(values)
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2.0


def _norm_color(value):
    return None if value in (None, 256) else value


def _norm_linetype(value):
    text = str(value or "").strip().upper()
    return None if text in {"", "BYLAYER"} else text


def _entity_id(entity):
    if entity.get("handle"):
        return entity["handle"]
    anchor = entity.get("anchor")
    if anchor:
        return f"{entity['type']}@{anchor[0]:.1f},{anchor[1]:.1f}"
    return entity["type"]


def _entity_ref(entity, include_span=False):
    ref = {
        "id": _entity_id(entity),
        "handle": entity.get("handle"),
        "type": entity["type"],
        "layer": entity["layer"],
        "kind": entity["kind"],
        "kind_basis": entity["kind_basis"],
        "origin": entity["origin"],
        "origin_basis": entity["origin_basis"],
        "anchor": _clean(entity.get("anchor")),
        "bbox": _clean(entity.get("bbox")),
        "landing": _clean(entity.get("landing") or []),
        "orientation": _clean(entity.get("orientation") or {}),
        "length": _clean(entity.get("length")),
        "linetype": entity.get("linetype"),
        "pattern": entity.get("pattern"),
        "dimstyle": entity.get("dimstyle"),
        "subtype": entity.get("subtype"),
        "subtype_text": DIM_SUBTYPES.get(entity.get("subtype"))
        if entity.get("kind") in {"dimension", "dimension geometry"} else None,
        "height": _clean(entity.get("height")),
        "block": entity.get("block"),
    }
    if include_span:
        ref["span"] = _clean(entity.get("span"))
    return ref


def _model_units(document):
    name = (document.get("units") or {}).get("name")
    return name or "drawing units"


def _fmt_length(value, document):
    if value is None:
        return None
    units = _model_units(document)
    if units == "inches":
        return f"{value:.2f} in"
    if units == "feet":
        return f"{value:.2f} ft"
    return f"{value:.1f} {units}"


# --------------------------------------------------------------------------
# Reference frame: what "above", "outside" and "the main part" mean
# --------------------------------------------------------------------------


def reference_frame(document, tolerance):
    """Bounds and main direction of the generated outline in ``document``."""
    entities = [e for e in document["entities"]
                if e["bbox"] and e["kind"] in {"contour", "axis"}
                and e["origin"] == "generated"]
    source = "generated outline"
    if not entities:
        entities = [e for e in document["entities"]
                    if e["bbox"] and e["kind"] in {"contour", "axis"}]
        source = "outline (no AS layer/XData marker was found)"
    bounds = _union_bbox([e["bbox"] for e in entities]) or document.get("bounds")
    segments = []
    for entity in entities:
        for first, second in entity["segments"]:
            segments.append({"a": first, "b": second, "entity": _entity_ref(entity)})
    dominant = _dominant_segment(
        [(s["a"], s["b"]) for s in segments]) if segments else None
    axis = None
    if dominant:
        angle = math.degrees(math.atan2(dominant[1][1] - dominant[0][1],
                                        dominant[1][0] - dominant[0][0]))
        axis = {
            "degrees": round(angle % 180.0, 2),
            "unit": [round(math.cos(math.radians(angle)), 6),
                     round(math.sin(math.radians(angle)), 6)],
            "basis": "longest generated contour segment",
        }
        axis["normal"] = [-axis["unit"][1], axis["unit"][0]]
    return {
        "bounds": bounds,
        "centroid": _bbox_center(bounds),
        "axis": axis,
        "segments": segments,
        "source": source,
        "tolerance": tolerance,
    }


def _point_segment_distance(point, first, second):
    px, py = point
    ax, ay = first
    bx, by = second
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _nearest_segment(point, frame, limit):
    best = None
    for segment in frame["segments"]:
        distance = _point_segment_distance(point, segment["a"], segment["b"])
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, segment)
    return best


def _is_extreme(point, orientation, frame, tolerance):
    bounds = frame.get("bounds")
    if not bounds:
        return False
    bucket = (orientation or {}).get("bucket")
    if bucket == "horizontal":
        return (abs(point[0] - bounds["min"][0]) <= tolerance
                or abs(point[0] - bounds["max"][0]) <= tolerance)
    if bucket == "vertical":
        return (abs(point[1] - bounds["min"][1]) <= tolerance
                or abs(point[1] - bounds["max"][1]) <= tolerance)
    axis = frame.get("axis")
    if not axis:
        return False
    projections = []
    for segment in frame["segments"]:
        for corner in (segment["a"], segment["b"]):
            projections.append(corner[0] * axis["unit"][0] + corner[1] * axis["unit"][1])
    if not projections:
        return False
    projection = point[0] * axis["unit"][0] + point[1] * axis["unit"][1]
    return (abs(projection - min(projections)) <= tolerance
            or abs(projection - max(projections)) <= tolerance)


def _feature_label(segment, point, orientation, frame, tolerance):
    entity = segment["entity"]
    if entity["kind"] == "axis":
        return f"a system line (centerline) on layer {entity['layer']}"
    if _is_extreme(point, orientation, frame, tolerance):
        return "the assembly extreme"
    origin = "generated " if entity["origin"] == "generated" else ""
    return f"a {origin}contour on layer {entity['layer']}"


def _landing_features(ref, frame, tolerance):
    landing = ref.get("landing") or []
    if not landing and ref.get("anchor"):
        landing = [ref["anchor"]]
    radius = max(frame["tolerance"] * 8.0, _diagonal(frame.get("bounds")) * 0.02, 1e-6)
    labels = []
    nearby = True
    for point in landing:
        hit = _nearest_segment(point, frame, radius)
        if not hit:
            nearby = False
            continue
        labels.append(_feature_label(hit[1], point, ref.get("orientation"),
                                     frame, tolerance))
    unique = []
    for label in labels:
        if label not in unique:
            unique.append(label)
    return {"labels": unique, "nearby": nearby,
            "basis": "geometry (nearest generated line) against the before file"}


def _side_and_offset(ref, frame, existing, tolerance, exclude=None):
    """Which side of the view/chain a dimension or label sits on."""
    if exclude:
        existing = [point for point in existing
                    if _distance(point, exclude) > tolerance]
    anchor = ref.get("anchor")
    bounds = frame.get("bounds")
    orientation = ref.get("orientation") or {}
    bucket = orientation.get("bucket")
    if not anchor or not bounds:
        return {"text": "in the drawing", "offset": None, "reference": None,
                "basis": "no reference outline"}

    def same_side(value, edge, positive):
        return [item for item in existing
                if (item[1] > edge + tolerance if positive
                    else item[1] < edge - tolerance)]

    if bucket == "horizontal":
        if anchor[1] > bounds["max"][1] + tolerance:
            side = "above the view"
            peers = same_side(anchor, bounds["max"][1], True)
            edge_distance = anchor[1] - bounds["max"][1]
        elif anchor[1] < bounds["min"][1] - tolerance:
            side = "below the view"
            peers = same_side(anchor, bounds["min"][1], False)
            edge_distance = bounds["min"][1] - anchor[1]
        else:
            return {"text": "inside the view", "offset": None, "reference": None,
                    "basis": "view bounds"}
        nearest = min((abs(anchor[1] - peer[1]) for peer in peers), default=None)
        if nearest is not None:
            return {"text": side, "offset": nearest,
                    "reference": "the nearest existing chain",
                    "basis": "view bounds and the before file's chains"}
        return {"text": side, "offset": edge_distance, "reference": "the view edge",
                "basis": "view bounds"}

    if bucket == "vertical":
        if anchor[0] > bounds["max"][0] + tolerance:
            side = "right of the view"
            peers = same_side(anchor, bounds["max"][0], True)
            edge_distance = anchor[0] - bounds["max"][0]
        elif anchor[0] < bounds["min"][0] - tolerance:
            side = "left of the view"
            peers = same_side(anchor, bounds["min"][0], False)
            edge_distance = bounds["min"][0] - anchor[0]
        else:
            return {"text": "inside the view", "offset": None, "reference": None,
                    "basis": "view bounds"}
        nearest = min((abs(anchor[0] - peer[0]) for peer in peers), default=None)
        if nearest is not None:
            return {"text": side, "offset": nearest,
                    "reference": "the nearest existing chain",
                    "basis": "view bounds and the before file's chains"}
        return {"text": side, "offset": edge_distance, "reference": "the view edge",
                "basis": "view bounds"}

    axis = frame.get("axis")
    centroid = frame.get("centroid")
    if bucket == "sloped" and axis and centroid:
        offset_vector = [anchor[0] - centroid[0], anchor[1] - centroid[1]]
        projected = (offset_vector[0] * axis["normal"][0]
                     + offset_vector[1] * axis["normal"][1])
        positive = projected >= 0
        if axis["normal"][1] >= 0:
            side = "above the sloped main part" if positive else "below the sloped main part"
        else:
            side = "below the sloped main part" if positive else "above the sloped main part"
        peers = []
        for peer in existing:
            vector = [peer[0] - centroid[0], peer[1] - centroid[1]]
            peer_projection = (vector[0] * axis["normal"][0]
                               + vector[1] * axis["normal"][1])
            if (peer_projection >= 0) == positive:
                peers.append(abs(projected - peer_projection))
        nearest = min(peers, default=None)
        if nearest is not None:
            return {"text": side, "offset": nearest,
                    "reference": "the nearest existing chain",
                    "basis": "main-part axis and the before file's chains"}
        return {"text": side, "offset": abs(projected),
                "reference": "the main part", "basis": "main-part axis"}

    return {"text": "inside the view", "offset": None, "reference": None,
            "basis": "view bounds"}


def _direction_text(orientation, frame):
    orientation = orientation or {}
    bucket = orientation.get("bucket")
    if bucket == "horizontal":
        return "runs horizontally", "geometry"
    if bucket == "vertical":
        return "runs vertically", "geometry"
    if bucket == "round":
        return "has no direction (round)", "geometry"
    degrees = orientation.get("degrees")
    if degrees is None:
        return "direction not set", "raw"
    axis = frame.get("axis")
    if axis:
        difference = min(abs(degrees - axis["degrees"]),
                         abs(degrees - axis["degrees"] + 180.0),
                         abs(degrees - axis["degrees"] - 180.0))
        if difference <= ANGLE_TOLERANCE:
            return "runs along the main part", "geometry (main-part axis)"
        if abs(difference - 90.0) <= ANGLE_TOLERANCE:
            return "runs square to the main part", "geometry (main-part axis)"
    return f"runs at {degrees:.0f} degrees across the view", "geometry"


def _offset_phrase(side, document, tolerance):
    offset = side.get("offset")
    if offset is None or offset <= tolerance * 1.5:
        return ""
    distance = _fmt_length(offset, document)
    reference = side.get("reference") or "the view"
    return f", {distance} clear of {reference}"


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------


def _cell(point, size):
    return (math.floor(point[0] / size), math.floor(point[1] / size))


def _neighbour_cells(point, size):
    key = _cell(point, size)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            yield (key[0] + dx, key[1] + dy)


def _compatible(before, after, strict):
    if before["kind"] != after["kind"] or before["origin"] != after["origin"]:
        return False
    if before["kind"] == "dimension":
        if (before.get("subtype") or 0) != (after.get("subtype") or 0):
            return False
        if _bucket(before) != _bucket(after):
            return False
        ratio = _span_ratio(before, after)
        if ratio is not None:
            if strict and not 0.9 <= ratio <= 1.1:
                return False
            if not strict and not 0.5 <= ratio <= 2.0:
                return False
    elif before["kind"] == "label":
        if strict:
            if not _ratio_close(before.get("height"), after.get("height"), 0.1):
                return False
            if _bucket(before) != _bucket(after):
                return False
    elif before["kind"] == "hatch":
        if strict and before.get("pattern") != after.get("pattern"):
            return False
    elif strict and before["kind"] in {"contour", "axis"}:
        if _bucket(before) != _bucket(after):
            return False
        if not _ratio_close(before.get("length"), after.get("length"), 0.1):
            return False
    return True


def _match_pass(before, after, used, radius, strict, after_used=None):
    if radius <= 0:
        return []
    size = max(radius / 2.0, 1e-6)
    grid = defaultdict(list)
    for index, entity in enumerate(before):
        if index in used or not entity.get("anchor"):
            continue
        grid[_cell(entity["anchor"], size)].append(index)
    pairs = []
    taken = set(used)
    skip_after = after_used or set()
    for after_index, entity in enumerate(after):
        if after_index in skip_after or not entity.get("anchor"):
            continue
        best = None
        for key in _neighbour_cells(entity["anchor"], size):
            for before_index in grid.get(key, ()):
                if before_index in taken:
                    continue
                candidate = before[before_index]
                if not _compatible(candidate, entity, strict):
                    continue
                distance = _distance(candidate["anchor"], entity["anchor"])
                if distance <= radius and (best is None or distance < best[0]):
                    best = (distance, before_index)
        if best:
            taken.add(best[1])
            pairs.append((best[1], after_index, best[0]))
    return pairs


def _pair_changes(before, after):
    changes = []

    def add(field, old, new, style_owned):
        changes.append({"field": field, "from": _clean(old), "to": _clean(new),
                        "style_owned": style_owned})

    if _norm_linetype(before.get("linetype")) != _norm_linetype(after.get("linetype")):
        add("linetype", before.get("linetype"), after.get("linetype"), True)
    if before.get("layer") != after.get("layer"):
        add("layer", before.get("layer"), after.get("layer"), True)
    if _norm_color(before.get("color")) != _norm_color(after.get("color")):
        add("colour", _norm_color(before.get("color")),
            _norm_color(after.get("color")), False)
    if before.get("kind") == "dimension" and before.get("dimstyle") != after.get("dimstyle"):
        add("dimension style", before.get("dimstyle"), after.get("dimstyle"), False)
    if before.get("kind") in {"label", "title"}:
        if not _ratio_close(before.get("height"), after.get("height"), 0.02):
            add("text height", before.get("height"), after.get("height"), False)
        if (before.get("rotation") is not None and after.get("rotation") is not None
                and abs(before["rotation"] - after["rotation"]) > 0.5):
            add("rotation", before.get("rotation"), after.get("rotation"), True)
    if before.get("kind") == "hatch" and before.get("pattern") != after.get("pattern"):
        add("hatch pattern", before.get("pattern"), after.get("pattern"), True)
    if _bucket(before) != _bucket(after):
        add("orientation", _bucket(before), _bucket(after), True)
    if before.get("kind") not in {"dimension", "label", "title"}:
        if not _ratio_close(before.get("length"), after.get("length"), 0.02):
            add("length", before.get("length"), after.get("length"), True)
    if before.get("kind") == "other" and before.get("block") != after.get("block"):
        add("block", before.get("block"), after.get("block"), None)
    return changes


def _contour_bounds(document):
    return _union_bbox([e["bbox"] for e in document["entities"]
                        if e["kind"] in {"contour", "axis"} and e["bbox"]])


def _normalise_after(after, factor, before_center, after_center):
    """Map the after geometry back to the before scale for comparison."""
    if not factor or abs(factor - 1.0) < 1e-9:
        return after["entities"]
    if not before_center or not after_center:
        return after["entities"]

    def transform(point):
        if not point:
            return point
        return [before_center[0] + (point[0] - after_center[0]) / factor,
                before_center[1] + (point[1] - after_center[1]) / factor]

    normalised = []
    for entity in after["entities"]:
        copy = dict(entity)
        copy["points"] = [transform(p) for p in entity["points"]]
        copy["landing"] = [transform(p) for p in entity["landing"]]
        copy["anchor"] = transform(entity["anchor"])
        if entity["bbox"]:
            first = transform(entity["bbox"]["min"])
            second = transform(entity["bbox"]["max"])
            copy["bbox"] = {
                "min": [min(first[0], second[0]), min(first[1], second[1])],
                "max": [max(first[0], second[0]), max(first[1], second[1])],
            }
        copy["segments"] = [(transform(first), transform(second))
                            for first, second in entity["segments"]]
        if entity.get("length"):
            copy["length"] = entity["length"] / factor
        if entity.get("span"):
            copy["span"] = entity["span"] / factor
        if entity.get("height"):
            copy["height"] = entity["height"] / factor
        normalised.append(copy)
    return normalised


def diff_documents(before, after, tolerance=None, scale_factor=None):
    """Pair entities and return unchanged, changed, moved, added and removed."""
    diagonal = (_diagonal(_contour_bounds(before))
                or _diagonal(_contour_bounds(after))
                or _diagonal(before.get("bounds"))
                or _diagonal(after.get("bounds")) or 0.0)
    if tolerance is None:
        tolerance = max(diagonal * 0.005, 1e-6)
    move_radius = max(diagonal * 0.25, tolerance * 20.0)
    before_entities = before["entities"]
    before_center = _bbox_center(_contour_bounds(before) or before.get("bounds"))
    after_center = _bbox_center(_contour_bounds(after) or after.get("bounds"))
    after_entities = _normalise_after(after, scale_factor, before_center, after_center)

    first_pass = _match_pass(before_entities, after_entities, set(), tolerance, False)
    matched_before = {pair[0] for pair in first_pass}
    matched_after = {pair[1] for pair in first_pass}
    second_pass = _match_pass(before_entities, after_entities, matched_before,
                              move_radius, True, after_used=matched_after)
    matched_before |= {pair[0] for pair in second_pass}
    matched_after |= {pair[1] for pair in second_pass}

    unchanged = []
    changed = []
    moved = []
    for before_index, after_index, distance in first_pass:
        changes = _pair_changes(before_entities[before_index],
                                after_entities[after_index])
        pair = {
            "distance": _clean(distance),
            "before": _entity_ref(before_entities[before_index]),
            "after": _entity_ref(after_entities[after_index]),
            "changes": changes,
        }
        if changes:
            changed.append(pair)
        else:
            unchanged.append(pair)
    for before_index, after_index, distance in second_pass:
        changes = _pair_changes(before_entities[before_index],
                                after_entities[after_index])
        moved.append({
            "distance": _clean(distance),
            "before": _entity_ref(before_entities[before_index]),
            "after": _entity_ref(after_entities[after_index]),
            "changes": changes,
        })

    added = [_entity_ref(entity) for index, entity in enumerate(after_entities)
             if index not in matched_after]
    removed = [_entity_ref(entity) for index, entity in enumerate(before_entities)
               if index not in matched_before]
    return {
        "tolerance": _clean(tolerance),
        "move_radius": _clean(move_radius),
        "unchanged": len(unchanged),
        "changed": changed,
        "moved": moved,
        "added": added,
        "removed": removed,
        "counts": {
            "unchanged": len(unchanged),
            "changed": len(changed),
            "moved": len(moved),
            "added": len(added),
            "removed": len(removed),
        },
    }


# --------------------------------------------------------------------------
# Group raw entities into edits a person can read
# --------------------------------------------------------------------------


def _dimension_anchors(document):
    return [e["anchor"] for e in document["entities"]
            if e["kind"] == "dimension" and e.get("anchor")]


def _group_key(entry, side, bucket_size):
    ref = entry["ref"]
    action = entry["action"]
    offset = side.get("offset") or 0.0
    if ref["kind"] == "dimension":
        return (action, "dimension", ref["origin"], _bucket(ref), side.get("text"),
                round(offset / max(bucket_size, 1e-6)))
    if ref["kind"] in {"label", "title"}:
        height = ref.get("height") or 0.0
        return (action, ref["kind"], ref["origin"], side.get("text"),
                round(height, 1))
    return (action, ref["kind"], ref["origin"], ref["layer"], _bucket(ref))


def _change_summary(changes):
    parts = []
    for change in changes:
        old = "none" if change["from"] in (None, "") else change["from"]
        new = "none" if change["to"] in (None, "") else change["to"]
        parts.append(f"{change['field']} {old} -> {new}")
    return "; ".join(parts)


def _verb(action):
    return {"added": "Added", "removed": "Removed", "moved": "Moved",
            "changed": "Changed"}.get(action, action.title())


def _origin_phrase(origin):
    return {"generated": "Advance Steel", "hand": "hand-made",
            "unknown": "unclassified"}.get(origin, origin)


def _intent_for_group(group, frame, before_doc, tolerance):
    refs = [item["ref"] for item in group["items"]]
    first = refs[0]
    action = group["action"]
    origin = first["origin"]
    kind = first["kind"]
    verb = _verb(action)
    origin_phrase = _origin_phrase(origin)
    notes = []

    if kind == "dimension":
        direction, direction_basis = _direction_text(first["orientation"], frame)
        side = group["side"]
        count = len(refs)
        if count > 1:
            what = f"dimension chain of {count} segments"
        else:
            what = "single dimension"
        features = []
        nearby = False
        for ref in refs:
            found = _landing_features(ref, frame, tolerance)
            nearby = nearby or found["nearby"]
            for label in found["labels"]:
                if label not in features:
                    features.append(label)
        if features:
            feature_text = "landing on " + " and ".join(features)
        elif nearby:
            feature_text = "landing on the generated geometry"
        else:
            feature_text = "with no generated geometry at its landing points"
            notes.append("No generated line was close enough to name a feature; "
                         "the DXF does not carry the model object that was dimensioned.")
        summary = (
            f"{verb} {origin_phrase} {what} {side.get('text')}, {direction}"
            f"{_offset_phrase(side, before_doc, tolerance)}, {feature_text}."
        )
        return {
            "summary": summary,
            "direction": {"text": direction, "basis": direction_basis},
            "side": side,
            "feature": {"labels": features, "basis": "geometry"},
            "dimension_subtype": first.get("subtype_text"),
            "what": what,
            "count": count,
            "basis_notes": notes,
        }

    if kind in {"label", "title"}:
        side = group["side"]
        count = len(refs)
        height = first.get("height")
        height_text = f" at {_fmt_length(height, before_doc)} text height" if height else ""
        what = "title text" if kind == "title" else "label"
        if count > 1:
            what = f"{count} {what}s"
        summary = (f"{verb} {origin_phrase} {what} {side.get('text')}"
                   f"{height_text}; the text content and value are ignored.")
        return {
            "summary": summary,
            "direction": {"text": "", "basis": "not compared for text"},
            "side": side,
            "feature": {"labels": [], "basis": "not compared for text"},
            "what": what,
            "count": count,
            "basis_notes": notes,
        }

    if kind in {"contour", "axis", "hatch", "frame", "dimension geometry",
                "other"}:
        orientation = _direction_text(first["orientation"], frame)[0]
        layers = sorted({ref["layer"] for ref in refs})
        layer_text = ", ".join(layers)
        changes = _change_summary(group["changes"])
        text = f"{verb} {origin_phrase} {kind} on layer {layer_text}"
        if orientation not in {"direction not set", "has no direction (round)"}:
            text += f", {orientation}"
        if changes:
            text += f": {changes}"
        return {
            "summary": text + ".",
            "direction": {"text": orientation, "basis": "geometry"},
            "side": group["side"],
            "feature": {"labels": [], "basis": "layer name and geometry"},
            "what": kind,
            "count": len(refs),
            "basis_notes": notes,
        }

    return {
        "summary": f"{verb} {origin_phrase} entity on layer {first['layer']}.",
        "direction": {"text": "", "basis": "not classified"},
        "side": group["side"],
        "feature": {"labels": [], "basis": "not classified"},
        "what": kind,
        "count": len(refs),
        "basis_notes": notes,
    }


def group_edits(diff, frame, before_doc, tolerance):
    """Collapse entity-level changes into readable, grouped edits."""
    entries = []
    for action in ("added", "removed", "moved", "changed"):
        for pair in diff.get(action, []):
            if action in {"moved", "changed"}:
                ref = pair["after"] if action == "moved" else pair["after"]
                changes = pair["changes"]
            else:
                ref = pair
                changes = []
            exclude = None
            if action in {"moved", "changed"}:
                exclude = pair["before"].get("anchor")
            elif action == "removed":
                exclude = ref.get("anchor")
            side = _side_and_offset(ref, frame, _dimension_anchors(before_doc),
                                    tolerance, exclude=exclude)
            entries.append({"action": action, "ref": ref, "changes": changes,
                            "side": side})

    bucket_size = max(tolerance * 4.0,
                      _diagonal(frame.get("bounds")) * 0.01, 1e-6)
    groups = {}
    order = []
    for entry in entries:
        key = _group_key(entry, entry["side"], bucket_size)
        if key not in groups:
            groups[key] = {"action": entry["action"], "items": [], "changes": [],
                           "side": entry["side"]}
            order.append(key)
        groups[key]["items"].append(entry)
        for change in entry["changes"]:
            if change not in groups[key]["changes"]:
                groups[key]["changes"].append(change)

    edits = []
    for number, key in enumerate(order, start=1):
        group = groups[key]
        first = group["items"][0]["ref"]
        intent = _intent_for_group(group, frame, before_doc, tolerance)
        evidence = []
        for item in group["items"][:25]:
            evidence.append(_entity_ref(item["ref"]))
        edits.append({
            "id": number,
            "action": group["action"],
            "kind": first["kind"],
            "origin": first["origin"],
            "count": len(group["items"]),
            "layers": sorted({item["ref"]["layer"] for item in group["items"]}),
            "changes": group["changes"],
            "side": group["side"],
            "intent": intent,
            "evidence": evidence,
            "evidence_truncated": len(group["items"]) > 25,
        })
    return edits


def _ref_span(ref):
    landing = ref.get("landing") or []
    if len(landing) >= 2:
        return _distance(landing[0], landing[1])
    return None


def _pair_replacements(edits, move_radius):
    """Mark a hand dimension drawn over a removed AS dimension as a redraw."""
    removed = [e for e in edits if e["action"] == "removed"
               and e["kind"] == "dimension" and e["origin"] == "generated"]
    added = [e for e in edits if e["action"] == "added"
             and e["kind"] == "dimension" and e["origin"] == "hand"]
    for new in added:
        new_refs = [item for item in new["evidence"]]
        for old in removed:
            if not old["evidence"] or not new_refs:
                continue
            old_ref = old["evidence"][0]
            new_ref = new_refs[0]
            if _bucket(old_ref) != _bucket(new_ref):
                continue
            old_span = _ref_span(old_ref)
            new_span = _ref_span(new_ref)
            if not old_span or not new_span:
                continue
            if not _ratio_close(old_span, new_span, 0.2):
                continue
            anchors = [ref["anchor"] for ref in old["evidence"] if ref.get("anchor")]
            nearest = min((_distance(anchor, new_ref["anchor"]) for anchor in anchors),
                          default=None)
            if nearest is not None and nearest <= move_radius:
                new["replaces"] = old["id"]
                old["replaced_by"] = new["id"]
    return edits


# --------------------------------------------------------------------------
# Scale change
# --------------------------------------------------------------------------


def _lengths_by_layer(document):
    totals = defaultdict(float)
    counts = Counter()
    for entity in document["entities"]:
        if entity["kind"] in {"contour", "axis"} and entity.get("length"):
            totals[entity["layer"]] += entity["length"]
            counts[entity["layer"]] += 1
    return totals, counts


def detect_scale_change(before, after, tolerance, style_views=None):
    """Detect a uniform size change from contour length totals per layer."""
    if (before.get("units") or {}).get("name") != (after.get("units") or {}).get("name"):
        return {"changed": None, "factor": None,
                "reason": "The two files declare different drawing units, so a size "
                          "change cannot be compared.",
                "basis": "header $INSUNITS"}
    before_totals, before_counts = _lengths_by_layer(before)
    after_totals, _ = _lengths_by_layer(after)
    ratios = {}
    for layer, total in before_totals.items():
        if layer not in after_totals:
            continue
        if total <= tolerance or before_counts[layer] < 2:
            continue
        ratios[layer] = after_totals[layer] / total
    factor = _median(ratios.values())
    consistent = 0.0
    if factor and ratios:
        consistent = sum(1 for ratio in ratios.values()
                         if abs(ratio - factor) <= 0.05) / len(ratios)
    before_diagonal = _diagonal(_contour_bounds(before))
    after_diagonal = _diagonal(_contour_bounds(after))
    bounds_ratio = (after_diagonal / before_diagonal
                    if before_diagonal and after_diagonal else None)
    changed = bool(
        factor and abs(factor - 1.0) > 0.02 and consistent >= 0.75
        and (len(ratios) >= 2
             or (len(ratios) == 1 and bounds_ratio
                 and abs(bounds_ratio - factor) <= 0.02)))
    result = {
        "changed": changed,
        "factor": _clean(factor) if changed else None,
        "layers_compared": len(ratios),
        "consistent": round(consistent, 3),
        "bounds_ratio": _clean(bounds_ratio),
        "basis": "contour length totals per layer",
        "note": (
            "A uniform size change is consistent with a view-scale change. The "
            "drawing itself does not store the print scale, so this reading is "
            "assumed until checked against the style export. The edit diff is "
            "normalised to the before scale so the scale change does not appear "
            "as a move of every entity."
            if changed else
            "Contour length totals did not change uniformly, so no scale change "
            "was seen. A scale change made only in paper space cannot be detected "
            "from model-space geometry."),
    }
    if changed and style_views:
        proposals = []
        for view in style_views:
            old = view.get("scale")
            if not old:
                continue
            new = old * factor
            proposals.append({
                "style": view.get("style"),
                "view": view.get("view"),
                "old_scale": old,
                "old_label": view.get("scale_label"),
                "new_scale": _clean(new),
                "new_label": f"1:{1.0 / new:.4g}" if new else None,
                "basis": "assumed (new = old x geometry factor)",
            })
        result["proposals"] = proposals
    return result


# --------------------------------------------------------------------------
# Style index and matching
# --------------------------------------------------------------------------


def _row_name(row):
    for key in ("RunName", "Name", "Title", "Description"):
        value = (row or {}).get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


QUERY_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "has", "have",
    "view", "layer", "chain", "single", "dimension", "added", "removed",
    "moved", "changed", "hand", "made", "generated", "advance", "steel",
    "segments", "runs", "running", "landing", "clear", "nearest", "existing",
    "inside", "above", "below", "left", "right", "horizontal", "vertical",
    "extreme", "extremes", "assembly", "overall", "centerline", "center",
    "centre", "system", "hole", "holes", "contour", "sloped",
}


def _tokens(text, filtered=True):
    words = {word for word in re.findall(r"[a-z0-9]+", str(text or "").lower())
             if len(word) >= 3}
    return words - QUERY_STOPWORDS if filtered else words


def _entry_from_explanation(name, view, style_name, explanation, row, linear):
    placement = " ".join(p.get("text", "") for p in explanation.get("placement") or [])
    points = " ".join(p.get("sentence", "") for p in explanation.get("points") or [])
    direction = (explanation.get("direction") or {}).get("text") or ""
    text = " ".join(part for part in (
        name, explanation.get("summary"), direction, placement, points,
        (explanation.get("dim_type") or {}).get("text")) if part)
    return {
        "style": style_name,
        "view": view,
        "name": name,
        "summary": explanation.get("summary"),
        "direction": direction,
        "placement": [p.get("text", "") for p in explanation.get("placement") or []],
        "points": [p.get("sentence", "") for p in explanation.get("points") or []],
        "point_rules": [
            {
                "key": point.get("key"),
                "name": point.get("display_name") or point.get("name"),
                "sentence": point.get("sentence"),
                "reference": bool(point.get("reference")),
            }
            for point in explanation.get("points") or []
        ],
        "type": (explanation.get("dim_type") or {}).get("value"),
        "type_text": (explanation.get("dim_type") or {}).get("text"),
        "table": "DetViewDimStrategyItems",
        "row": row or {},
        "linear": linear or {},
        "entry": explanation,
        "tokens": _tokens(text, filtered=False),
    }


def flatten_dimension_requests(style_model):
    """Index the dimension requests in one style model for intent matching."""
    entries = []
    for master in (style_model or {}).get("masters") or []:
        style = master.get("style") or {}
        style_name = _row_name(style.get("row")) or "style"
        for request in style.get("requests") or []:
            if request.get("missing"):
                continue
            view = (request.get("short_name")
                    or _row_name(request.get("row")) or "view")
            for dim in request.get("dims") or []:
                explanation = dim.get("explain") or {}
                if not explanation or explanation.get("missing"):
                    continue
                linear = (dim.get("linear") or {}).get("row") or {}
                name = explanation.get("name") or _row_name(linear) or "dimension request"
                entries.append(_entry_from_explanation(
                    name, view, style_name, explanation,
                    dim.get("row") or {}, linear))
    return entries


def load_request_library(database):
    """Index every dimension request in a drawing-style export, not only the
    ones the selected style currently uses."""
    from utils import db as dbcore

    try:
        tables = set(dbcore.list_tables(database))
    except Exception:
        return []
    if "DetViewDimRequestLinear" not in tables:
        return []

    def rows(table):
        if table not in tables:
            return []
        try:
            return dbcore.get_rows(database, table, limit=5000)
        except Exception:
            return []

    def label_map(table, display="RunName"):
        return {row.get("Key"): row.get(display) for row in rows(table)}

    qset_names = label_map("DetObjQualifierSet")
    group_names = label_map("DetViewDimRequestLinearGroup")
    points = {row.get("Key"): row for row in rows("DetViewDimPointSelection")}
    entries = []
    for linear in rows("DetViewDimRequestLinear"):
        point_rows = []
        try:
            count = int(float(linear.get("Number of Points") or 0))
        except (TypeError, ValueError):
            count = 0
        count = max(0, min(count, 15))
        for index in range(1, count + 1):
            point_rows.append(points.get(linear.get(f"Point{index}")))
        explanation = dim_explain.explain_request(
            linear, point_rows, qset_names, order=None, item=None,
            group_names=group_names)
        entries.append(_entry_from_explanation(
            explanation.get("name") or _row_name(linear) or "dimension request",
            "(request library)", None, explanation, {}, linear))
    return entries


def search_requests(index, intent, limit=3):
    """Rank existing requests against one edit's intent."""
    direction = (intent.get("direction") or {}).get("text", "").lower()
    side_text = (intent.get("side") or {}).get("text", "").lower()
    features = " ".join((intent.get("feature") or {}).get("labels") or []).lower()
    query = _tokens(" ".join((
        direction, side_text, features,
        (intent.get("side") or {}).get("reference") or "",
        intent.get("what") or "")))
    ranked = []
    for entry in index or []:
        score = 0
        entry_tokens = entry.get("tokens") or set()
        for token in query:
            if token in entry_tokens:
                score += 1
        entry_direction = (entry.get("direction") or "").lower()
        if "horizontal" in direction and re.search(r"\bx\b", entry_direction):
            score += 4
        if "vertical" in direction and re.search(r"\by\b", entry_direction):
            score += 4
        if "along the main part" in direction and "main part" in entry_tokens:
            score += 3
        entry_placement = " ".join(entry.get("placement") or []).lower()
        for word in ("above", "below", "left", "right"):
            if word in side_text and word in entry_placement:
                score += 3
        for word in ("extreme", "assembly", "overall", "centerline", "center",
                     "system", "hole", "contour"):
            if word in features and word in entry_tokens:
                score += 2
        if "chain" in str(intent.get("what") or "").lower() and entry.get("type") == 2:
            score += 2
        if score:
            ranked.append({
                "score": score,
                "style": entry.get("style"),
                "view": entry.get("view"),
                "name": entry.get("name"),
                "summary": entry.get("summary"),
                "direction": entry.get("direction"),
                "type": entry.get("type"),
                "type_text": entry.get("type_text"),
                "row": entry.get("row"),
                "linear": entry.get("linear"),
            })
    ranked.sort(key=lambda row: (-row["score"], str(row.get("name") or "")))
    seen = set()
    unique = []
    for row in ranked:
        # The same library request can be reached both through the style and
        # through the export-wide library index; keep one entry.
        key = ((row.get("linear") or {}).get("Key"), row.get("name"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
        if len(unique) >= limit:
            break
    return unique


def search_point_rules(index, intent, limit=3):
    """Rank existing point-selection rules against one edit's intent."""
    direction = (intent.get("direction") or {}).get("text", "").lower()
    side_text = (intent.get("side") or {}).get("text", "").lower()
    features = " ".join((intent.get("feature") or {}).get("labels") or []).lower()
    query = _tokens(" ".join((direction, side_text, features)))
    ranked = []
    seen = set()
    for entry in index or []:
        for point in entry.get("point_rules") or []:
            text = f"{point.get('name') or ''} {point.get('sentence') or ''}"
            tokens = _tokens(text, filtered=False)
            score = sum(1 for token in query if token in tokens)
            for word in ("extreme", "extremes", "assembly", "overall", "centerline",
                         "center", "centre", "system", "hole", "holes", "contour"):
                if word in features and word in tokens:
                    score += 2
            for word in ("above", "below", "left", "right"):
                if word in side_text and word in tokens:
                    score += 1
            if point.get("reference"):
                score -= 1
            if score <= 0:
                continue
            key = (point.get("sentence"), point.get("name"),
                   entry.get("style"), entry.get("view"))
            if key in seen:
                continue
            seen.add(key)
            ranked.append({
                "score": score,
                "style": entry.get("style"),
                "view": entry.get("view"),
                "name": point.get("name"),
                "sentence": point.get("sentence"),
                "reference": point.get("reference"),
            })
    ranked.sort(key=lambda row: (-row["score"], str(row.get("sentence") or "")))
    return ranked[:limit]


STYLE_SOURCES = {
    "dimension": {
        "category": "dimension strategy",
        "tables": ["DetViewDimStrategyItems", "DetViewDimRequestLinear",
                   "DetViewDimPointSelection"],
        "fields": ["Type", "Direction", "Point1..15", "ArrangeAbove",
                   "ArrangeGlobally", "OneChainPerObjectInPoints1"],
        "basis": "schema (docs/drawing-style-schema.md)",
        "note": "A chain is a dimension-strategy item plus a request and its point "
                "rules. The drawing shows the result, not which object set or "
                "direction number produced it.",
    },
    "label": {
        "category": "label strategy",
        "tables": ["DetObjReprMapItems", "DetObjAnnotationStrategy",
                   "DetAnnotationType", "DetArrangerStrategy"],
        "fields": ["AnnotationStrategy", "AnnotationType.Content",
                   "ArrangerStrategy"],
        "basis": "schema (docs/drawing-style-schema.md)",
        "note": "Label content is ignored here. Pick the label formula and "
                "arranger in the DSM; the DXF does not name them.",
    },
    "title": {
        "category": "title",
        "tables": ["DetailStyle"],
        "fields": ["TitleFormat", "CutViewTitleFormat", "TitlePosition"],
        "basis": "schema (docs/drawing-style-schema.md)",
        "note": "Title content is a formula; the DXF text is ignored. TitlePosition "
                "is an AS enum whose labels are not in the export.",
    },
    "contour": {
        "category": "representation rules",
        "tables": ["DetObjReprMapItems", "DetObjAppearance", "Linetypes"],
        "fields": ["ObjQualifier", "Appearance", "LineType", "GeometricRestrictions"],
        "basis": "schema (docs/drawing-style-schema.md)",
        "note": "Which object set and geometric restriction produced this contour is "
                "not recoverable from the DXF, so the rule itself must be chosen in "
                "the DSM.",
    },
    "axis": {
        "category": "representation rules",
        "tables": ["DetObjReprMapItems", "DetObjAppearance", "Linetypes"],
        "fields": ["ObjQualifier", "LineType"],
        "basis": "schema (docs/drawing-style-schema.md)",
        "note": "A centerline is an object-set/representation choice, not a drawing "
                "default.",
    },
    "hatch": {
        "category": "representation rules",
        "tables": ["DetObjReprMapItems", "DetObjAppearance", "DetHatchSettings"],
        "fields": ["Appearance", "HatchVisible", "HatchHidden"],
        "basis": "schema (docs/drawing-style-schema.md)",
        "note": "The hatch preset is in the appearance library; the DXF only shows "
                "the pattern that was drawn.",
    },
    "other": None,
    "frame": None,
}

STYLE_SOURCES["dimension geometry"] = {
    **STYLE_SOURCES["dimension"],
    "note": "The DXF carries this dimension as plain lines or text rather than a "
            "DIMENSION entity, but the style source is still the view's dimension "
            "strategy.",
}

NON_STYLE_FIELDS = {
    "text height": "Text height belongs to the drawing defaults or the DWG "
                   "prototype, not the style export.",
    "colour": "Entity and layer colours come from the drawing defaults or the "
              "prototype, not the style export.",
    "dimension style": "The AutoCAD dimension style (arrow size, text style, "
                       "extension offsets) is a drawing default, not a style setting.",
}

STYLE_NOTES = {
    "dimension": "The style controls the chain's side and clearance through its "
                 "arrangement switches; an arbitrary offset may still need a manual "
                 "move in the drawing.",
    "dimension geometry": "The style controls the chain's side and clearance "
                          "through its arrangement switches; an arbitrary offset "
                          "may still need a manual move in the drawing.",
    "label": "A manual label move is not stored as a coordinate; the style can only "
             "place labels through its arranger strategy.",
    "contour": "A representation rule can change how an object is drawn, but the "
               "DXF does not say which rule created it.",
}


def _usage_for(style_graph, row, cache):
    if not style_graph or not row:
        return None
    table = "DetViewDimStrategyItems"
    columns = (style_graph.get("pk_by_table") or {}).get(table) or []
    if not columns:
        return None
    values = [row.get(column) for column in columns]
    key = (table, tuple(values))
    if key in cache:
        return cache[key]
    try:
        report = style_usage.usage(
            style_graph.get("rows_by_table") or {},
            style_graph.get("pk_by_table") or {},
            table, values,
            tables_present=style_graph.get("tables_present"))
    except Exception as exc:  # read-only diagnostics must never break the report
        report = {"ok": False, "error": str(exc), "styles": []}
    cache[key] = report
    return report


def map_edit(edit, request_index=None, style_graph=None, usage_cache=None):
    """Map one grouped edit to the style surface that owns it."""
    kind = edit["kind"]
    source = STYLE_SOURCES.get(kind)
    aspects = []
    for change in edit.get("changes") or []:
        if not change.get("style_owned") and change["field"] in NON_STYLE_FIELDS:
            aspects.append({"aspect": change["field"],
                            "reason": NON_STYLE_FIELDS[change["field"]],
                            "basis": "assumed (not a style table)"})
    style_changes = [c for c in edit.get("changes") or [] if c.get("style_owned")]
    non_style_only = bool(edit.get("changes")) and not style_changes

    result = {
        "category": source["category"] if source else "not mapped",
        "tables": source["tables"] if source else [],
        "fields": source["fields"] if source else [],
        "basis": source["basis"] if source else "none",
        "can_style": None if source is None else True,
        "reason": None,
        "note": None,
        "matches": [],
        "point_matches": [],
        "shared": [],
        "suggestion": None,
        "not_style": aspects,
        "replaces": edit.get("replaces"),
        "replaced_by": edit.get("replaced_by"),
    }
    if kind == "frame":
        aspects.append({
            "aspect": "title frame",
            "reason": "The title frame, border and sheet furniture belong to the "
                      "DWG prototype, not the style export.",
            "basis": "assumed (issue #15 design note)",
        })
        result["can_style"] = False
        result["category"] = "drawing defaults"
        result["reason"] = aspects[-1]["reason"]
    if source:
        result["note"] = source["note"]
        if kind in STYLE_NOTES:
            result["note"] = f"{result['note']} {STYLE_NOTES[kind]}"
    elif kind != "frame":
        result["reason"] = "This entity kind does not map to a known style surface."
    if non_style_only:
        result["can_style"] = False
        result["reason"] = " ".join(aspect["reason"] for aspect in aspects)
        result["category"] = "drawing defaults"

    if kind in {"dimension", "dimension geometry"} and request_index:
        result["matches"] = search_requests(request_index, edit["intent"])
        if result["matches"]:
            cache = usage_cache if usage_cache is not None else {}
            for match in result["matches"][:2]:
                usage = _usage_for(style_graph, match.get("row"), cache)
                if usage and usage.get("styles"):
                    match["shared_with"] = [
                        {"name": style.get("name"), "key": style.get("key")}
                        for style in usage["styles"]
                    ]
                    if len(usage["styles"]) > 1:
                        result["shared"].append({
                            "name": match.get("name"),
                            "view": match.get("view"),
                            "styles": match["shared_with"],
                        })
        for match in result["matches"]:
            match.pop("row", None)
            match.pop("linear", None)
        result["point_matches"] = search_point_rules(request_index, edit["intent"])
        if not result["matches"]:
            result["note"] = (
                f"{result['note']} No existing request in the loaded export "
                "describes this intent, so the plan would add a new request.")
    elif kind in {"dimension", "dimension geometry"}:
        result["note"] = (
            f"{result['note']} Attach the style export to see which existing "
            "requests could be reused.")
    if edit.get("replaces"):
        result["note"] = (
            f"{result['note']} This hand-made chain appears to replace the removed "
            "generated chain, so treat it as an edit of the existing request.")
    if edit.get("replaced_by"):
        result["note"] = (
            f"{result['note']} A hand-made chain was drawn over this generated one; "
            "the removal is probably part of that redraw.")
    result["suggestion"] = _suggestion(edit, result)
    return result


def _suggestion(edit, mapped):
    """One sentence naming the style change that would reproduce the edit."""
    kind = edit["kind"]
    action = edit["action"]
    matches = mapped.get("matches") or []
    points = mapped.get("point_matches") or []
    if kind == "frame":
        return ("Edit the DWG prototype or drawing template; the frame and border are "
                "not part of the style export.")
    if mapped.get("can_style") is False:
        return "This aspect is a drawing default and has no style setting."
    if kind in {"dimension", "dimension geometry"}:
        if edit.get("replaced_by"):
            return ("The removed chain was redrawn by hand. Keep the request and "
                    "change its arrangement only if the redraw moved the chain.")
        if edit.get("replaces"):
            return ("Edit the existing request that produced the removed chain so it "
                    "draws the new chain instead of adding a second request.")
        if action == "removed":
            return ("Stop drawing this chain: remove its request from the strategy, "
                    "or change its point rules so it finds nothing.")
        if matches:
            top = matches[0]
            verb = "Edit" if action in {"changed", "moved"} else "Reuse"
            text = (f"{verb} the existing request '{top.get('name')}' in view "
                    f"'{top.get('view')}' (match score {top.get('score')}).")
            if action == "added":
                text += (" If it is already in this view's strategy, change its "
                         "point rules or arrangement instead of adding a second "
                         "request.")
            if points:
                text += f" Point rule: {points[0].get('sentence') or points[0].get('name')}."
            return text
        return ("Add a new request with this direction, side and point rules; no "
                "existing request in the loaded export matches.")
    if kind in {"label", "title"}:
        if kind == "title":
            return ("Change DetailStyle.TitleFormat or TitlePosition. The text content "
                    "is a formula and is ignored here; TitlePosition is an AS enum.")
        return ("Change the label strategy or arranger for this object set. The text "
                "content is a formula and is ignored here.")
    if kind in {"contour", "axis", "hatch"}:
        return ("Find the representation rule for this object set and change its "
                "appearance or linetype. The DXF does not name the rule, so the "
                "object set must be chosen in the DSM.")
    return None


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def _document_summary(document):
    units = document.get("units") or {}
    return {
        "acadver": document.get("acadver"),
        "entities": len(document["entities"]),
        "by_kind": document["counts"]["by_kind"],
        "by_origin": document["counts"]["by_origin"],
        "layers": len(document["layers"]),
        "units": units,
        "bounds": _clean(document.get("bounds")),
        "warnings": list(document.get("warnings") or []),
    }


DIMSTYLE_FIELDS = (
    ("arrow_size", "arrow size"),
    ("text_height", "dimension text height"),
    ("extension_offset", "extension line offset"),
    ("extension_beyond", "extension line beyond"),
    ("gap", "text gap"),
    ("scale", "dimension style scale"),
)


def compare_drawing_defaults(before, after):
    """DIMSTYLE and layer-table changes that no style setting owns."""
    items = []
    for key in sorted(set(before.get("dimstyles") or {}) & set(after.get("dimstyles") or {})):
        old = before["dimstyles"][key]
        new = after["dimstyles"][key]
        for field, label in DIMSTYLE_FIELDS:
            old_value = old.get(field)
            new_value = new.get(field)
            if old_value is None or new_value is None:
                continue
            if abs(old_value - new_value) > 1e-6:
                items.append({
                    "area": "dimension style",
                    "name": old.get("name") or key,
                    "field": label,
                    "before": _clean(old_value),
                    "after": _clean(new_value),
                })
    for key in sorted(set(before.get("layers") or {}) & set(after.get("layers") or {})):
        old = before["layers"][key]
        new = after["layers"][key]
        if (old.get("color") is not None and new.get("color") is not None
                and old["color"] != new["color"]):
            items.append({
                "area": "layer",
                "name": old.get("name") or key,
                "field": "colour",
                "before": old["color"],
                "after": new["color"],
            })
    return items


def _view_scale(denominator):
    try:
        value = float(denominator)
    except (TypeError, ValueError):
        return None
    return 1.0 / value if value else None


def _style_summary(style_model, style_database, index):
    if not style_model and not style_database:
        return None
    views = []
    styles = []
    for master in (style_model or {}).get("masters") or []:
        style = master.get("style") or {}
        style_name = _row_name(style.get("row")) or "style"
        if style_name not in styles:
            styles.append(style_name)
        for request in style.get("requests") or []:
            views.append({
                "style": style_name,
                "view": request.get("short_name") or _row_name(request.get("row")),
                "scale": _view_scale(request.get("scale_denom")),
                "scale_denom": request.get("scale_denom"),
                "scale_label": request.get("scale_label"),
            })
    return {
        "database": style_database,
        "styles": styles,
        "views": views,
        "requests_indexed": len(index or []),
    }


def flatten_views(style_model):
    if not style_model:
        return []
    views = []
    for master in style_model.get("masters") or []:
        style = master.get("style") or {}
        style_name = _row_name(style.get("row")) or "style"
        for request in style.get("requests") or []:
            views.append({
                "style": style_name,
                "view": request.get("short_name") or _row_name(request.get("row")),
                "scale": _view_scale(request.get("scale_denom")),
                "scale_denom": request.get("scale_denom"),
                "scale_label": request.get("scale_label"),
            })
    return views


def _limitations():
    return [
        "Read-only: this page compares two DXF files and reports. It does not "
        "change the style or the drawing.",
        "The pair must be the same detail, exported before and after the hand "
        "edits, with the same assembly coordinates. Otherwise the diff reports "
        "every difference between two unrelated drawings.",
        "Advance Steel vs hand-made is inferred from the layer name (AS_ or "
        "ADVANCE prefix) and AS XDATA. Check the rule against your own export.",
        "Part marks, m-numbers and dimension values are ignored. Dimensions are "
        "compared by where they are and which way they run.",
        "The feature named for a dimension is the nearest generated line, not a "
        "model part name. The DXF does not carry the Advance Steel object.",
        "A whole view moved on the sheet is reported as many moved entities, not "
        "as one view-layout edit: the style controls arrangement order and spacing, "
        "not exact coordinates.",
        "Advance Steel enum labels (dimension direction, point position, title "
        "position) are not in the style export; no label is guessed.",
        "Phase 2 (apply the plan to a copy, regenerate and repeat) is blocked "
        "until the style-item write path passes verification A4 and a real "
        "before/after pair is checked under A7.",
    ]


def build_report(before_source, after_source, tolerance=None,
                 request_index=None, style_model=None, style_database=None,
                 style_graph=None):
    """Read both files and return the reviewable Phase 1 report."""
    before = read_dxf(before_source)
    after = read_dxf(after_source)
    diagonal = (_diagonal(_contour_bounds(before))
                or _diagonal(_contour_bounds(after))
                or _diagonal(before.get("bounds"))
                or _diagonal(after.get("bounds")) or 0.0)
    if tolerance is None:
        tolerance = max(diagonal * 0.005, 1e-6)
    frame = reference_frame(before, tolerance)
    scale = detect_scale_change(before, after, tolerance,
                                style_views=flatten_views(style_model))
    diff = diff_documents(
        before, after, tolerance=tolerance,
        scale_factor=scale.get("factor") if scale.get("changed") else None)
    edits = group_edits(diff, frame, before, tolerance)
    edits = _pair_replacements(edits, diff["move_radius"])

    index = list(request_index or [])
    index.extend(flatten_dimension_requests(style_model))
    usage_cache = {}
    for edit in edits:
        edit["style"] = map_edit(edit, request_index=index,
                                 style_graph=style_graph,
                                 usage_cache=usage_cache)

    not_style = []
    for edit in edits:
        for aspect in edit["style"].get("not_style") or []:
            not_style.append({
                "edit": edit["id"],
                "summary": edit["intent"]["summary"],
                "aspect": aspect["aspect"],
                "reason": aspect["reason"],
                "basis": aspect["basis"],
            })
    drawing_defaults = compare_drawing_defaults(before, after)
    for item in drawing_defaults:
        if item["area"] == "dimension style":
            reason = ("The DXF dimension style (arrow size, text height, extension "
                      "offsets, scale) is a drawing default, not a style setting.")
        else:
            reason = ("Layer colours come from the drawing defaults or the DWG "
                      "prototype, not the style export.")
        not_style.append({
            "edit": None,
            "summary": "Drawing defaults",
            "aspect": f"{item['name']} {item['field']}",
            "reason": reason,
            "basis": "DIMSTYLE/layer table in the uploaded files",
        })

    warnings = list(before.get("warnings") or []) + list(after.get("warnings") or [])
    unknown = sum(count for origin, count in after["counts"]["by_origin"].items()
                  if origin == "unknown")
    if unknown:
        warnings.append(
            f"{unknown} entity/entities have no Advance Steel marker and are on "
            "layer 0 or an empty layer, so their origin is unclassified.")
    if ((before.get("units") or {}).get("name")
            != (after.get("units") or {}).get("name")):
        warnings.append(
            f"The files declare different units ({_model_units(before)} and "
            f"{_model_units(after)}); distances and the scale reading are not "
            "comparable.")
    if before["counts"]["by_origin"].get("generated") == 0:
        warnings.append(
            "The before file has no entity on an Advance Steel layer. The feature "
            "and side readings use its whole outline, but check the layer rule.")

    return {
        "before": _document_summary(before),
        "after": _document_summary(after),
        "units": _model_units(before),
        "tolerance": _clean(tolerance),
        "reference": {
            "source": frame["source"],
            "bounds": _clean(frame["bounds"]),
            "main_axis_degrees": (frame["axis"] or {}).get("degrees"),
            "main_axis_basis": (frame["axis"] or {}).get("basis"),
        },
        "diff": {
            "counts": diff["counts"],
            "unchanged": diff["unchanged"],
            "moved_radius": diff["move_radius"],
        },
        "edits": edits,
        "scale": scale,
        "style": _style_summary(style_model, style_database, index),
        "drawing_defaults": drawing_defaults,
        "not_style": not_style,
        "warnings": warnings,
        "limitations": _limitations(),
        "summary": {
            "edits": len(edits),
            "added": diff["counts"]["added"],
            "removed": diff["counts"]["removed"],
            "moved": diff["counts"]["moved"],
            "changed": diff["counts"]["changed"],
            "unchanged": diff["counts"]["unchanged"],
            "hand": after["counts"]["by_origin"].get("hand", 0),
            "generated": after["counts"]["by_origin"].get("generated", 0),
        },
    }
