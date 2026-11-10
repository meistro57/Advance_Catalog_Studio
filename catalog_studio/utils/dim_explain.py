# utils/dim_explain.py
"""Plain-language reading of a drawing style's dimension requests.

The Drawing Style Manager shows a dimension request as three dense panels
(chain direction, point selection rules, arrangement check boxes) and packs
the arrangement into a three-letter code at the end of the request name, for
example ``Mp X - Extreme GTA``. This module turns one
``DetViewDimRequestLinear`` row plus its ``DetViewDimPointSelection`` rows into
sentences a detailer can read at a glance.

Every statement carries a *basis* so the page never presents a guess as fact:

``guide``
    The meaning comes from the Advance Steel Drawing Style Manager Guide
    (2016, chapter 6 "Dimension Request", and the 6.1 guide). For the flag
    columns the match is by column name to the DSM option text; the DSM name
    code is used as a cross-check against the stored flags.
``name``
    Read from a rule's ``RunName`` (e.g. ``Holes - All`` or
    ``Main Part - Extreme as reference``). Names are written by whoever made
    the rule, so they describe intent, not stored settings.
``data``
    A value read directly from the row (object set name, point count, …).
``observed``
    Seen in Advance Steel's own output for a real export (recorded in
    ``docs/verification-log.md``) but not yet confirmed in the DSM's option
    list. One observation, so it says so.
``raw``
    A number whose label lives in Advance Steel's built-in database
    (``AstorDetailsBase``), which an export does not contain. Shown unchanged;
    no label is invented.

No database access here: callers pass rows in, sentences come out.
"""

import re

# --------------------------------------------------------------------------
# The DSM name code: <G|L><T|B><S|A> at the end of a request name.
# Guide (2016) p.72: "The name of the dimension definition contains the
# settings mentioned above using their abbreviation", example
# "Mp X - Extreme GTA".
# --------------------------------------------------------------------------

NAME_CODE = re.compile(r"(?:^|[\s\-_])([GL])([TB])([SA])\s*$")

CODE_LETTERS = {
    "G": ("ArrangeGlobally", True,
          "G · kept clear of the whole detail's geometry"),
    "L": ("ArrangeGlobally", False,
          "L · kept clear of the dimensioned part only"),
    "T": ("ArrangeAbove", True, "T · placed above (left in a vertical view)"),
    "B": ("ArrangeAbove", False, "B · placed below (right in a vertical view)"),
    "S": ("OneChainPerObjectInPoints1", True, "S · one chain per object found"),
    "A": ("OneChainPerObjectInPoints1", False, "A · everything found in one chain"),
}

# Columns this module explains; anything else on the row is listed raw.
LINEAR_KNOWN = {
    "Key", "RunName", "OwnerText", "Direction", "ArrangeAbove", "ArrangeGlobally",
    "GroupRelatedDimensions", "OneChainPerObjectInPoints1", "AllowCombine",
    "AutomaticallySeparate", "Group", "LabelContents", "Number of Points",
    "NumberOfPoints",
} | {f"Point{i}" for i in range(1, 16)}

POINT_KNOWN = {"Key", "RunName", "Objects", "OwnerText"}

# DetViewDimPointSelection columns -> the DSM field they hold. The column names
# say it, and the export's InfoTableRelations points each one at its own
# AstorDetailsBase list (DetViewDimPointtype, DetVwDimGeomRestrictions, ...).
# Values verified across the 373 point rules of delivered AstorDetails.mdf (A5.2)
# are mapped in POINT_VALUE_TABLES below; unverified numbers stay raw.
POINT_FIELD_LABELS = {
    "PointType": "Point type",
    "PointGeometricRestrictions": "Position on object",
    "MpGeomRestriction": "Position on main part",
    "VisibilityStatus": "Visibility",
    "DepthPosition": "Depth position",
    "GeometricRestrictions": "Object geometric restriction",
    "ReferenceAxis": "Reference axis",
    "MPReferenceAxis": "Main-part reference axis",
    "ParentRelativePositonRestriction": "Position relative to parent",
}

LINEAR_FIELD_LABELS = {"LabelPosition": "Label position"}

# Verified from AstorDetailsBase.DetViewDimPointtype and cross-checked across
# all 373 DetViewDimPointSelection rows in AstorDetails.mdf (A5.2).
# Values >= 1000 add +1000 for "as reference" ("Ref.").
POINT_TYPE_LABELS = {
    0: "All (ANY)",
    1: "Extreme",
    2: "Contour",
    3: "Inside processings",
    4: "Holes",
    5: "Attached parts",
    8: "Inside processings (each)",
    9: "System",
    10: "Center",
    11: "Inside (curved/bent beam)",
    12: "Outside (curved/bent beam)",
    14: "Assembly overall",
    15: "Templates reference point",
    16: "Development lines",
    17: "Median",
    19: "End processings",
    20: "Helper line points",
    21: "Environment system",
    22: "Environment median points",
    23: "Environment contour points",
    24: "Camber points",
    1000: "All as reference",
    1001: "Ref. Extreme",
    1002: "Ref. Contour",
    1003: "Ref. Inside processings",
    1004: "Ref. Holes",
    1005: "Ref. Attached parts",
    1009: "Ref. System",
    1010: "Ref. Center",
    1011: "Ref. Inside (curved/bent beam)",
    1012: "Ref. Outside (curved/bent beam)",
    1014: "Ref. Assembly overall",
    1015: "Ref. Template reference point",
    1017: "Ref. Median",
    1021: "Ref. Environment system",
    1022: "Ref. Environment median points",
    1023: "Ref. Environment contour points",
}

# Verified from AstorDetailsBase.DetVwDimGeomRestrictions and 186/186 rules in
# AstorDetails.mdf DetViewDimPointSelection (A5.2).
POINT_POSITION_LABELS = {
    0: "Any",
    1: "Left",
    2: "Right",
    4: "Bottom",
    5: "BottomLeft",
    6: "BottomRight",
    8: "Top",
    9: "TopLeft",
    10: "TopRight",
    11: "LeftExtreme (Leftmost)",
    12: "RightExtreme (Rightmost)",
    13: "TopExtreme (Topmost)",
    14: "BottomExtreme (Bottommost)",
    15: "Left & Right Extremes",
    16: "Top & Bottom Extremes",
}

# Verified from AstorDetailsBase.DetailVisibilityStatus (A5.2).
VISIBILITY_LABELS = {
    0: "Default",
    1: "Visible",
    2: "Visible and hidden",
    3: "Hidden",
}

# Verified from AstorDetailsBase.DetailDepthPosition (A5.2).
DEPTH_POSITION_LABELS = {
    0: "Any",
    1: "BothSides-CenterFront",
    2: "BothSides-CenterRear",
    3: "Front (entirely)",
    4: "Rear (entirely)",
    5: "BothSides-Center",
    6: "Both Sides",
    7: "Front (by center)",
    8: "Rear (by center)",
}

# Verified from AstorDetailsBase.DetGeometricRestrictions (A5.2).
GEOM_RESTRICTION_LABELS = {
    0: "All",
    1: "Li (Linear)",
    2: "NLi (Non-linear)",
    3: "Tv (Top / Transversal)",
    4: "Fr+Side (Front + Side)",
    5: "Side (Side/Width)",
    6: "Tv+Fr (Top+Front/Length)",
    7: "Fr (Front/Length)",
    8: "Top+Side/Width",
    9: "Li+Fr (Linear Front)",
    10: "Li+Tv (Linear Top)",
    11: "Linear Side",
    12: "Non Linear Front",
    13: "NLi+Tv (Non Linear Top)",
    14: "Non Linear Side",
}

# Verified from AstorDetailsBase.DetailReferenceAxis (A5.2).
REFERENCE_AXIS_LABELS = {
    0: "Relative to dimensioning line direction",
    1: "Relative to object direction",
}

# Verified from AstorDetailsBase.DetVwDimParentRelaPosRestriction (A5.2).
PARENT_POS_LABELS = {
    0: "Any",
    1: "Top Flange",
    2: "Bottom Flange",
    3: "Flanges (Both)",
    4: "Web",
}

POINT_VALUE_TABLES = {
    "PointType": POINT_TYPE_LABELS,
    "PointGeometricRestrictions": POINT_POSITION_LABELS,
    "MpGeomRestriction": POINT_POSITION_LABELS,
    "VisibilityStatus": VISIBILITY_LABELS,
    "DepthPosition": DEPTH_POSITION_LABELS,
    "GeometricRestrictions": GEOM_RESTRICTION_LABELS,
    "ReferenceAxis": REFERENCE_AXIS_LABELS,
    "MPReferenceAxis": REFERENCE_AXIS_LABELS,
    "ParentRelativePositonRestriction": PARENT_POS_LABELS,
}

# Verified from AstorDetailsBase.DetRequestLinearDirection (0..19) and
# cross-checked across 398 requests in AstorDetails.mdf (A5.2).
DIRECTION_LABELS = {
    0: ("runs along X", "x",
        "AstorDetailsBase.DetRequestLinearDirection #0 (viewX): x-orientation of the view."),
    1: ("runs along Y", "y",
        "AstorDetailsBase.DetRequestLinearDirection #1 (viewY): y-orientation of the view."),
    2: ("runs along the object's X axis", "x",
        "AstorDetailsBase.DetRequestLinearDirection #2 (objectX): x-axis of an object."),
    3: ("runs along the object's Y axis", "y",
        "AstorDetailsBase.DetRequestLinearDirection #3 (objectY): y-axis of an object."),
    4: ("runs along the main part's X axis", "x",
        "AstorDetailsBase.DetRequestLinearDirection #4 (main part X): x-axis of a main part."),
    5: ("runs along the main part's Y axis", "y",
        "AstorDetailsBase.DetRequestLinearDirection #5 (main part Y): y-axis of a main part."),
    6: ("runs along a bent beam's Y axis", "y",
        "AstorDetailsBase.DetRequestLinearDirection #6 (Bent Y): y-axis CurvedBeam."),
    7: ("runs along a bent beam's system X axis", "x",
        "AstorDetailsBase.DetRequestLinearDirection #7 (Bent X System): x-axis CurvedBeam system."),
    8: ("runs along a bent beam's inner X axis", "x",
        "AstorDetailsBase.DetRequestLinearDirection #8 (Bent X Inner): x-axis CurvedBeam inner."),
    9: ("runs along a bent beam's outer X axis", "x",
        "AstorDetailsBase.DetRequestLinearDirection #9 (Bent X Outer): x-axis CurvedBeam outer."),
    10: ("runs along an internal linear / radial direction", None,
         "AstorDetailsBase.DetRequestLinearDirection #10: Internal direction linear."),
    11: ("runs along negative X (view)", "x",
         "AstorDetailsBase.DetRequestLinearDirection #11 (MinusViewX): Negative x-orientation of the view."),
    12: ("runs along negative Y (view)", "y",
         "AstorDetailsBase.DetRequestLinearDirection #12 (MinusViewY): Negative y-orientation of the view."),
    13: ("runs along the object's negative X axis", "x",
         "AstorDetailsBase.DetRequestLinearDirection #13 (MinusObjectX): Negative x-axis of an object."),
    14: ("runs along the object's negative Y axis", "y",
         "AstorDetailsBase.DetRequestLinearDirection #14 (MinusObjectY): Negative y-axis of an object."),
    15: ("runs along the main part's negative X axis", "x",
         "AstorDetailsBase.DetRequestLinearDirection #15 (MinusMainpartX): Negative x-axis of a main part."),
    16: ("runs along the main part's negative Y axis", "y",
         "AstorDetailsBase.DetRequestLinearDirection #16 (MinusMainpartY): Negative y-axis of a main part."),
    17: ("measures an internal angle", None,
         "AstorDetailsBase.DetRequestLinearDirection #17: Internal direction angle."),
    18: ("runs along the internal bolt/hole X direction", "x",
         "AstorDetailsBase.DetRequestLinearDirection #18: Internal bolt/hole direction X."),
    19: ("runs along the internal bolt/hole Y direction", "y",
         "AstorDetailsBase.DetRequestLinearDirection #19: Internal bolt/hole direction Y."),
}

DIRECTION_CHOICES = [
    (0, "0 · X (view)"),
    (1, "1 · Y (view)"),
    (2, "2 · X of object"),
    (3, "3 · Y of object"),
    (4, "4 · X of main part"),
    (5, "5 · Y of main part"),
    (6, "6 · Y curved (Bent Y)"),
    (7, "7 · X curved system (Bent X System)"),
    (8, "8 · X curved inner (Bent X Inner)"),
    (9, "9 · X curved outer (Bent X Outer)"),
    (10, "10 · Internal linear"),
    (11, "11 · -X (MinusViewX)"),
    (12, "12 · -Y (MinusViewY)"),
    (13, "13 · -X of object (MinusObjectX)"),
    (14, "14 · -Y of object (MinusObjectY)"),
    (15, "15 · -X of main part (MinusMainpartX)"),
    (16, "16 · -Y of main part (MinusMainpartY)"),
    (17, "17 · Internal angle"),
    (18, "18 · Internal bolt/hole X"),
    (19, "19 · Internal bolt/hole Y"),
]

# Direction numbers whose meaning has been SEEN in Advance Steel output but not
# yet read from the DSM list. Kept for compatibility; verified entries live in
# DIRECTION_LABELS above.
OBSERVED_DIRECTIONS = {}

# DetViewDimStrategyItems.Type -> AstorDetailsBase.DetRequestTypes (1..26),
# verified directly from AstorDetailsBase.mdf (A5.2) and A5.1.
REQUEST_TYPE_LABELS = {
    1: ("radial dimension", "AstorDetailsBase.DetRequestTypes #1: Radial."),
    2: ("chained (relative) linear dimension", "AstorDetailsBase.DetRequestTypes #2: Linear, relative."),
    3: ("relative arc-length dimension", "AstorDetailsBase.DetRequestTypes #3: Arc length, relative."),
    4: ("relative and absolute arc-length dimension", "AstorDetailsBase.DetRequestTypes #4: Arc length, relative and absolute."),
    5: ("absolute arc-length dimension", "AstorDetailsBase.DetRequestTypes #5: Arc length, absolute."),
    6: ("relative arc-angle dimension", "AstorDetailsBase.DetRequestTypes #6: Arc angle, relative."),
    7: ("relative and absolute arc-angle dimension", "AstorDetailsBase.DetRequestTypes #7: Arc angle, relative and absolute."),
    8: ("absolute arc-angle dimension", "AstorDetailsBase.DetRequestTypes #8: Arc angle, absolute."),
    9: ("relative and absolute linear dimension", "AstorDetailsBase.DetRequestTypes #9: Linear, relative and absolute."),
    10: ("absolute linear dimension", "AstorDetailsBase.DetRequestTypes #10: Linear, absolute."),
    11: ("angle dimension", "AstorDetailsBase.DetRequestTypes #11: Angle."),
    12: ("slope triangle dimension", "AstorDetailsBase.DetRequestTypes #12: Slope triangle."),
    13: ("relative and absolute arc-length dimension from end", "AstorDetailsBase.DetRequestTypes #13: Arc length, relative and absolute from end."),
    14: ("absolute arc-length dimension from end", "AstorDetailsBase.DetRequestTypes #14: Arc length, absolute from end."),
    15: ("relative and absolute arc-angle dimension from end", "AstorDetailsBase.DetRequestTypes #15: Arc angle, relative and absolute from end."),
    16: ("absolute arc-angle dimension from end", "AstorDetailsBase.DetRequestTypes #16: Arc angle, absolute from end."),
    17: ("relative and absolute linear dimension from end", "AstorDetailsBase.DetRequestTypes #17: Linear, relative and absolute from end."),
    18: ("absolute linear dimension from end", "AstorDetailsBase.DetRequestTypes #18: Linear, absolute from end."),
    19: ("running (cumulative / ordinate) linear dimension", "AstorDetailsBase.DetRequestTypes #19: Linear, ordinate."),
    20: ("ordinate and relative linear dimension", "AstorDetailsBase.DetRequestTypes #20: Linear, ordinate and relative."),
    21: ("level / elevation dimension", "AstorDetailsBase.DetRequestTypes #21: Level, absolute."),
    22: ("absolute and relative level / elevation dimension", "AstorDetailsBase.DetRequestTypes #22: Level, absolute and relative."),
    23: ("horizontal slope triangle dimension", "AstorDetailsBase.DetRequestTypes #23: Slope triangle, horizontal."),
    24: ("vertical slope triangle dimension", "AstorDetailsBase.DetRequestTypes #24: Slope triangle, vertical."),
    25: ("smallest-edge slope triangle dimension", "AstorDetailsBase.DetRequestTypes #25: Slope triangle, smallest edge."),
    26: ("longest-edge slope triangle dimension", "AstorDetailsBase.DetRequestTypes #26: Slope triangle, longest edge."),
}

OBSERVED_REQUEST_TYPES = {}

# DSM "Point position on object / on main part" options (guide 2016 p.80),
# used to read the position part of a rule name such as "... | Bottom-Any".
POSITION_WORDS = (
    "Left & Right Extremes", "Top & Bottom Extremes", "Bottommost", "BottomLeft",
    "BottomRight", "Leftmost", "Rightmost", "Topmost", "TopLeft", "TopRight",
    "Bottom", "Left", "Right", "Top", "Any",
)

# Advance Steel Deep Copy prefixes: "Copy of X", "Copy (2) of X", and
# "Copy (3) X" (without "of", seen in DetViewArrangeStrategy and subsequent
# deep copies in AstorAddIn), including chained prefixes.
COPY_PREFIX = re.compile(r"^(?:copy(?:\s*\(\d+\)(?:\s+of)?|\s+of)\s+)+", re.I)

NULL_REFS = {None, 0, -1, "", "0", "-1"}

# DSM "Dimension chain direction" options (2016 guide p.70-71). The export
# stores a number for the chosen option; the number-to-option table is in
# AstorDetailsBase, so this list is shown as context, never as a mapping.
DIRECTION_OPTIONS = (
    "X-orientation of the view", "Y-orientation of the view",
    "X-axis of a main part", "Y-axis of a main part",
    "X-axis of an object", "Y-axis of an object",
    "Internal bolt/hole direction X", "Internal bolt/hole direction Y",
    "Internal direction angle", "Internal direction linear",
    "X-axis Bent Beam inner / outer / system", "Y-axis Bent Beam",
    "… and a negative version of the view, main-part and object axes",
)

# DSM point types (2016 guide p.76-78), keyed by words that appear in point
# selection rule names. Order matters: the first match wins.
POINT_MEANINGS = (
    (("overall", "assembly"), "the overall extents of the assembly",
     "The outermost points of the whole assembly in the chain direction."),
    (("collision",), "the collision points", "Main-part collision dimensions."),
    (("development",), "the development (bend) lines", ""),
    (("stencil",), "the stencil points", "Stencil points grouped as sub-objects."),
    (("template",), "the template reference point", ""),
    (("bend", "bended", "bent"), None, "Bent-beam faces; inside/outside comes from the rule name."),
    (("extreme", "size"), "the overall size",
     "The outer extreme points in the chain direction, i.e. end to end."),
    (("system",), "the system line", "The object's system (work) points, not its faces."),
    (("center", "centre"), "the center point", ""),
    (("contour",), "the outline",
     "Contour points, including points made by shortenings and notches (infinite processings)."),
    (("feature",), "the cut features",
     "Feature points from finite processings, such as rectangular contour cuts."),
    (("processing", "end"), "the beam-end cuts", "Beam-end contour points, including finite cuts at the end."),
    (("attach",), "the attached parts", "Where attached parts sit on the object."),
    (("hole", "bolt"), "the hole centers", ""),
    (("all",), "every dimensionable point", ""),
)

# meanings that already name what they measure: no "of <objects>" after them
STANDALONE_MEANINGS = {"the overall extents of the assembly"}

SUBJECT_WORDS = (
    (("mp", "main part", "mainpart"), "the main part"),
    (("hole", "holes", "bolt", "bolts"), "holes"),
    (("beam", "beams"), "beams"),
    (("plate", "plates"), "plates"),
    (("attached", "attaching", "secondary"), "attached parts"),
)


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def decode_name_code(name):
    """``"Mp X - Extreme GTA"`` -> ``{"code": "GTA", "letters": [...]}`` or None."""
    match = NAME_CODE.search(str(name or ""))
    if not match:
        return None
    letters = []
    for letter in match.groups():
        column, value, text = CODE_LETTERS[letter]
        letters.append({"letter": letter, "column": column, "value": value, "text": text})
    return {"code": "".join(match.groups()), "letters": letters}


def name_code_check(name, linear):
    """Compare the DSM name code with the stored flags.

    Returns ``{"code", "agree": [...], "disagree": [...]}`` or None when the
    name carries no code. A disagreement usually means the request was edited
    after it was named; the flags, not the name, are what Advance Steel uses.
    """
    decoded = decode_name_code(name)
    if not decoded:
        return None
    agree, disagree = [], []
    for item in decoded["letters"]:
        if item["column"] not in linear:
            continue
        stored = _truthy(linear.get(item["column"]))
        entry = {"letter": item["letter"], "column": item["column"],
                 "name_says": item["value"], "stored": stored, "text": item["text"]}
        (agree if stored == item["value"] else disagree).append(entry)
    return {"code": decoded["code"], "agree": agree, "disagree": disagree}


def split_copy_prefix(name):
    """Split leading 'Copy of ' / 'Copy (n) ' prefixes from a RunName.

    Returns ``(prefix, base_name)``. When ``name`` has no deep-copy prefix
    (or nothing left after the prefix), returns ``("", str(name or ""))``.
    """
    text = str(name or "")
    match = COPY_PREFIX.match(text)
    if not match:
        return "", text
    base = text[match.end():]
    if not base.strip():
        return "", text
    return match.group(0), base


def clean_name(name):
    """Drop deep-copy prefixes ("Copy of Copy of X" / "Copy (3) X" -> "X") for display."""
    _, base = split_copy_prefix(name)
    return base.strip()


def read_position(text):
    """``"Bottom-Any"`` -> ``("Bottom", "Any")`` (on object, on main part)."""
    raw = str(text or "").strip()
    found = []
    rest = raw
    while rest:
        for word in POSITION_WORDS:
            if rest.lower().startswith(word.lower()):
                found.append(word)
                rest = rest[len(word):].lstrip(" -/")
                break
        else:
            return None
    if not found or len(found) > 2:
        return None
    return found[0], (found[1] if len(found) > 1 else None)


def position_phrase(on_object, on_main_part):
    parts = []
    if on_object and on_object != "Any":
        parts.append(f"{on_object.lower().replace('&', 'and')} points only")
    if on_main_part and on_main_part != "Any":
        parts.append(f"on the {on_main_part.lower().replace('&', 'and')} of the main part")
    return ", ".join(parts)


def _lower_words(text):
    return re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower())


def read_point_name(name):
    """Split ``"Main Part - Extreme as reference"`` into what/where/reference."""
    raw = clean_name(name)
    reference = bool(re.search(r"\bas\s+reference\b|\breference\b", raw, re.I))
    position = None
    if "|" in raw:
        # "Objects | Point kind | Position" (e.g. "Railings - Posts Landing | System | Bottom-Any")
        pieces = [x.strip() for x in raw.split("|")]
        head, tail = pieces[0], " ".join(pieces[1:2])
        if len(pieces) > 2:
            position = read_position(pieces[2])
    else:
        head, _, tail = raw.partition(" - ")
        if not tail:
            head, tail = "", raw
    words = _lower_words(f"{head} {tail}")
    tail_words = _lower_words(tail)

    def match(text_words, include_generic):
        for keys, text, hint in POINT_MEANINGS:
            if keys == ("all",) and not include_generic:
                continue
            if any(re.search(rf"\b{k}", text_words) for k in keys):
                if text is None:
                    side = "inside" if ("inside" in words or "inner" in words) else (
                        "outside" if ("outside" in words or "outer" in words) else "")
                    text = f"the {side} face of bent beams" if side else "the bent-beam faces"
                return text, hint
        return None

    # the part after " - " first ("Main Part - Extreme"), then the subject
    # ("Holes - All": holes carry the meaning), and plain "All" last.
    found = match(tail_words, False) or match(words, False) or match(words, True)
    meaning, hint = found if found else (None, "")

    subject = None
    head_words = _lower_words(head)
    for keys, text in SUBJECT_WORDS:
        if any(re.search(rf"\b{re.escape(k)}\b", head_words) for k in keys):
            subject = text
            break
    return {"subject": subject, "meaning": meaning, "hint": hint, "reference": reference,
            "position": position,
            "subject_text": head.strip(), "detail_text": tail.strip()}


def explain_point(point_row, qset_names=None, index=1):
    """One point selection rule as a sentence plus its stored settings."""
    has_qset_map = bool(qset_names)
    qset_names = qset_names or {}
    row = point_row or {}
    name = row.get("RunName") or f"point rule #{row.get('Key')}"
    parsed = read_point_name(name)
    pt_num = _int(row.get("PointType"))
    is_ref_code = pt_num is not None and pt_num >= 1000
    reference = parsed["reference"] or is_ref_code

    objects_key = row.get("Objects")
    objects_name = None
    dangling_objects = None
    if objects_key not in NULL_REFS:
        if has_qset_map and objects_key not in qset_names:
            dangling_objects = objects_key
        objects_name = clean_name(qset_names.get(objects_key, f"object set #{objects_key}"))
        if objects_name.lower() in {"mp", "main part", "mainpart"}:
            objects_name = "the main part"

    target = objects_name or parsed["subject"] or parsed["subject_text"]
    meaning = parsed["meaning"]
    if not meaning and pt_num is not None:
        base_pt = pt_num - 1000 if pt_num >= 1000 else pt_num
        pt_label = POINT_TYPE_LABELS.get(base_pt)
        if pt_label:
            pt_parsed = read_point_name(pt_label)
            meaning = pt_parsed["meaning"] or f"the {pt_label.lower()} points"
    if meaning in STANDALONE_MEANINGS:
        sentence = meaning
    elif meaning and target and not (meaning == "the hole centers" and target.lower() in {"holes", "hole"}):
        sentence = f"{meaning} of {target}"
    elif meaning:
        sentence = meaning
    else:
        sentence = f"points from {target or 'the selected objects'} ({parsed['detail_text'] or name})"

    pos_tuple = parsed["position"]
    if not pos_tuple:
        obj_pos = POINT_POSITION_LABELS.get(_int(row.get("PointGeometricRestrictions")))
        mp_pos = POINT_POSITION_LABELS.get(_int(row.get("MpGeomRestriction")))
        if (obj_pos and obj_pos != "Any") or (mp_pos and mp_pos != "Any"):
            pos_tuple = (
                obj_pos.split(" (")[0] if obj_pos else "Any",
                mp_pos.split(" (")[0] if mp_pos else "Any",
            )
    if pos_tuple:
        phrase = position_phrase(*pos_tuple)
        if phrase:
            sentence = f"{sentence} ({phrase})"

    extras = []
    for c, v in row.items():
        if c in POINT_KNOWN or v in (None, ""):
            continue
        v_int = _int(v)
        val_label = POINT_VALUE_TABLES.get(c, {}).get(v_int)
        extras.append({
            "column": c,
            "label": POINT_FIELD_LABELS.get(c, c),
            "value": v,
            "value_label": val_label,
            "basis": "data" if val_label is not None else "raw",
        })
    return {
        "index": index,
        "name": name,
        "display_name": clean_name(name),
        "key": row.get("Key"),
        "sentence": sentence,
        "hint": parsed["hint"],
        "reference": reference,
        "objects": objects_name,
        "objects_basis": "data" if objects_name else None,
        "dangling_objects": dangling_objects,
        "basis": "name",
        "extras": extras,
    }


def direction_text(linear):
    """Chain direction as words, keeping the stored number visible."""
    value = _int((linear or {}).get("Direction"))
    if value is None:
        return {"text": "direction not set", "axis": None, "value": None, "basis": "raw", "note": ""}
    if value in DIRECTION_LABELS:
        text, axis, note = DIRECTION_LABELS[value]
        shown = text if value in (0, 1) else f"{text} (direction #{value})"
        return {"text": shown, "axis": axis, "value": value, "basis": "data", "note": note}
    if value in OBSERVED_DIRECTIONS:
        text, note = OBSERVED_DIRECTIONS[value]
        return {"text": f"{text} (direction #{value})", "axis": None, "value": value,
                "basis": "observed", "note": note}
    return {"text": f"uses direction option #{value}", "axis": None, "value": value, "basis": "raw",
            "note": "The label for this number is in Advance Steel's built-in list, not the export."}


def placement_lines(linear):
    """The DSM 'Arrangement on the drawing' switches, one line each."""
    lin = linear or {}
    vertical = _int(lin.get("Direction")) == 1
    lines = []

    if "ArrangeAbove" in lin:
        above = _truthy(lin.get("ArrangeAbove"))
        side = ("on the left" if above else "on the right") if vertical else (
            "above the view" if above else "below the view")
        lines.append({
            "column": "ArrangeAbove", "on": above, "basis": "guide",
            "text": f"Placed {side}.",
            "help": "DSM: 'Arrange dimension line above and not below'. In a vertical "
                    "chain, above means left and below means right.",
        })
    if "ArrangeGlobally" in lin:
        on = _truthy(lin.get("ArrangeGlobally"))
        lines.append({
            "column": "ArrangeGlobally", "on": on, "basis": "guide",
            "text": "Kept clear of the whole detail's geometry." if on
                    else "Only kept clear of the part it dimensions; it may cross other parts.",
            "help": "DSM: 'Dimension line must not overlap the total geometry' "
                    "(G = global, L = local).",
        })
    if "OneChainPerObjectInPoints1" in lin:
        on = _truthy(lin.get("OneChainPerObjectInPoints1"))
        lines.append({
            "column": "OneChainPerObjectInPoints1", "on": on, "basis": "guide",
            "text": "One chain per object found by the first point rule (e.g. each bolt pattern gets its own chain)."
                    if on else "Everything the point rules find goes into one chain.",
            "help": "DSM: 'Create a separate dimension chain for each item marked with *' "
                    "(S = single, A = all). A bolt pattern is one object, so it makes one chain either way.",
        })
    if "GroupRelatedDimensions" in lin:
        on = _truthy(lin.get("GroupRelatedDimensions"))
        lines.append({
            "column": "GroupRelatedDimensions", "on": on, "basis": "guide",
            "text": "Bolt and hole groups on secondary parts get a dimension line each."
                    if on else "Related bolt/hole groups are not split into their own lines.",
            "help": "DSM: 'Group only related dimensions'.",
        })
    if "AllowCombine" in lin:
        on = _truthy(lin.get("AllowCombine"))
        lines.append({
            "column": "AllowCombine", "on": on, "basis": "guide",
            "text": "May merge with other chains that share points or values."
                    if on else "Never merged with other chains, even when they share points or values.",
            "help": "DSM: 'Do not combine with other dimensions' is the opposite of this column.",
        })
    if "AutomaticallySeparate" in lin:
        on = _truthy(lin.get("AutomaticallySeparate"))
        lines.append({
            "column": "AutomaticallySeparate", "on": on, "basis": "raw",
            "text": f"Automatic separation switch is {'on' if on else 'off'}.",
            "help": "Not described in the DSM guides; behaviour unverified.",
        })
    return lines


def request_type_text(value):
    """DetViewDimStrategyItems.Type (the DSM 'dimension type' column)."""
    num = _int(value)
    if num is None:
        return None
    if num in REQUEST_TYPE_LABELS:
        text, note = REQUEST_TYPE_LABELS[num]
        return {"value": num, "text": f"{text} (type #{num})", "basis": "data", "note": note}
    if num in OBSERVED_REQUEST_TYPES:
        text, note = OBSERVED_REQUEST_TYPES[num]
        return {"value": num, "text": f"{text} (type #{num})", "basis": "observed", "note": note}
    return {"value": num, "text": f"dimension type #{num}", "basis": "raw",
            "note": "The DSM's dimension types (linear relative/absolute, arc, angle, slope…) "
                    "are a built-in list; this number's label isn't in the export."}


def explain_request(linear, point_rows=(), qset_names=None, order=None,
                    item=None, group_names=None):
    """Everything the page shows for one dimension request.

    ``point_rows`` are the ``DetViewDimPointSelection`` rows in Point1..N
    order (missing ones as None).
    """
    lin = linear or {}
    raw_name = lin.get("RunName") or f"dimension request #{lin.get('Key')}"
    name = clean_name(raw_name) or raw_name
    points = [explain_point(p, qset_names, i + 1) for i, p in enumerate(point_rows) if p]
    measured = [p for p in points if not p["reference"]]
    reference = [p for p in points if p["reference"]]
    direction = direction_text(lin)
    placement = placement_lines(lin)

    # point count sanity: stored count vs populated Point1..15
    stored_count = _int(lin.get("Number of Points", lin.get("NumberOfPoints")))
    populated = sum(1 for i in range(1, 16) if lin.get(f"Point{i}") not in NULL_REFS)
    warnings = []
    if stored_count is not None and stored_count != populated:
        warnings.append(
            f"Number of Points says {stored_count} but {populated} point rule(s) are filled in; "
            f"only the first {stored_count} are listed as this chain's points.")
    if not points:
        warnings.append("No point selection rules: this request has nothing to measure.")
    elif not measured:
        warnings.append("Every point rule is 'as reference', so this chain is never drawn on its own.")
    for p in points:
        if p.get("dangling_objects") is not None:
            warnings.append(
                f"Point rule '{p['display_name']}' references object set "
                f"#{p['dangling_objects']}, which is not in this file."
            )
    check = name_code_check(name, lin)
    if check and check["disagree"]:
        letters = ", ".join(f"{d['letter']} ({d['column']})" for d in check["disagree"])
        warnings.append(f"The name code {check['code']} disagrees with the stored switches: {letters}. "
                        "The switches are what Advance Steel uses; the name is probably out of date.")

    # one-line summary
    if measured:
        what = "; ".join(p["sentence"] for p in measured[:3])
        if len(measured) > 3:
            what += f"; +{len(measured) - 3} more"
    else:
        what = "nothing on its own"
    where = next((p["text"].rstrip(".").lower() for p in placement if p["column"] == "ArrangeAbove"), "")
    summary = f"Measures {what}. The chain {direction['text']}" + (f", {where}" if where else "") + "."
    if reference:
        summary += (" Reference points ("
                    + ", ".join(p["sentence"] for p in reference[:2])
                    + (" …" if len(reference) > 2 else "")
                    + ") are added only when the chain already has something to measure.")

    extras = [
        {"column": c, "label": LINEAR_FIELD_LABELS.get(c, c), "value": v}
        for c, v in lin.items()
        if c not in LINEAR_KNOWN and v not in (None, "")
    ]
    label = lin.get("LabelContents")
    group_key = lin.get("Group")
    group_name = None
    if group_names and group_key in group_names:
        group_name = str(group_names[group_key] or "").strip() or None
    return {
        "order": order,
        "name": name,
        "raw_name": raw_name,
        "dim_type": request_type_text((item or {}).get("Type")),
        "group_name": group_name,
        "summary": summary,
        "direction": direction,
        "placement": placement,
        "points": points,
        "measured": measured,
        "reference": reference,
        "name_code": check,
        "warnings": warnings,
        "label": label if label not in (None, "", "-") else None,
        "group": lin.get("Group"),
        "extras": extras,
    }


def explain_strategy(dims, point_lookup, qset_names=None, group_names=None):
    """``dims`` as built by ``drawing_styles.style_tree`` (each with ``linear``
    and ``point_keys``) -> one explanation per chain, in strategy order."""
    out = []
    for d in dims or ():
        lin = (d.get("linear") or {}).get("row")
        if not lin:
            out.append({"order": (d.get("row") or {}).get("Order"), "missing": True,
                        "name": f"request #{(d.get('row') or {}).get('RequestLinear')}",
                        "warnings": ["This chain points at a dimension request that is not in the file."]})
            continue
        rows = [point_lookup.get(k) for k in d.get("point_keys") or ()]
        out.append(explain_request(lin, rows, qset_names, order=(d.get("row") or {}).get("Order"),
                                   item=d.get("row"), group_names=group_names))
    return out
