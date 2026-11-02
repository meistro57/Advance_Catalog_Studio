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
    "Key", "RunName", "Direction", "ArrangeAbove", "ArrangeGlobally",
    "GroupRelatedDimensions", "OneChainPerObjectInPoints1", "AllowCombine",
    "AutomaticallySeparate", "Group", "LabelContents", "Number of Points",
    "NumberOfPoints",
} | {f"Point{i}" for i in range(1, 16)}

POINT_KNOWN = {"Key", "RunName", "Objects"}

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


def _lower_words(text):
    return re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower())


def read_point_name(name):
    """Split ``"Main Part - Extreme as reference"`` into what/where/reference."""
    raw = str(name or "").strip()
    reference = bool(re.search(r"\bas\s+reference\b|\breference\b", raw, re.I))
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
            "subject_text": head.strip(), "detail_text": tail.strip()}


def explain_point(point_row, qset_names=None, index=1):
    """One point selection rule as a sentence plus its raw extras."""
    qset_names = qset_names or {}
    row = point_row or {}
    name = row.get("RunName") or f"point rule #{row.get('Key')}"
    parsed = read_point_name(name)
    objects_key = row.get("Objects")
    objects_name = None
    if objects_key not in NULL_REFS:
        objects_name = qset_names.get(objects_key, f"object set #{objects_key}")

    target = objects_name or parsed["subject"] or parsed["subject_text"]
    meaning = parsed["meaning"]
    if meaning and target and not (meaning == "the hole centers" and target.lower() in {"holes", "hole"}):
        sentence = f"{meaning} of {target}"
    elif meaning:
        sentence = meaning
    else:
        sentence = f"points from {target or 'the selected objects'} ({parsed['detail_text'] or name})"

    extras = [
        {"column": c, "value": v}
        for c, v in row.items()
        if c not in POINT_KNOWN and v not in (None, "")
    ]
    return {
        "index": index,
        "name": name,
        "key": row.get("Key"),
        "sentence": sentence,
        "hint": parsed["hint"],
        "reference": parsed["reference"],
        "objects": objects_name,
        "objects_basis": "data" if objects_name else None,
        "basis": "name",
        "extras": extras,
    }


def direction_text(linear):
    """Chain direction as words, keeping the stored number visible."""
    value = _int((linear or {}).get("Direction"))
    if value == 0:
        return {"text": "runs along X", "axis": "x", "value": 0, "basis": "data",
                "note": "This app draws Direction 0 as X; the full DSM list has ~20 options."}
    if value == 1:
        return {"text": "runs along Y", "axis": "y", "value": 1, "basis": "data",
                "note": "This app draws Direction 1 as Y; the full DSM list has ~20 options."}
    if value is None:
        return {"text": "direction not set", "axis": None, "value": None, "basis": "raw", "note": ""}
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


def explain_request(linear, point_rows=(), qset_names=None, order=None):
    """Everything the page shows for one dimension request.

    ``point_rows`` are the ``DetViewDimPointSelection`` rows in Point1..N
    order (missing ones as None).
    """
    lin = linear or {}
    name = lin.get("RunName") or f"dimension request #{lin.get('Key')}"
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
        {"column": c, "value": v}
        for c, v in lin.items()
        if c not in LINEAR_KNOWN and v not in (None, "")
    ]
    label = lin.get("LabelContents")
    return {
        "order": order,
        "name": name,
        "summary": summary,
        "direction": direction,
        "placement": placement,
        "points": points,
        "measured": measured,
        "reference": reference,
        "name_code": check,
        "warnings": warnings,
        "label": label if label not in (None, "") else None,
        "group": lin.get("Group"),
        "extras": extras,
    }


def explain_strategy(dims, point_lookup, qset_names=None):
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
        out.append(explain_request(lin, rows, qset_names, order=(d.get("row") or {}).get("Order")))
    return out
