# utils/drawing_styles.py
"""Drawing-style exports (Drawing Style Manager -> Export) as an editable tree.

An exported style mdf is a small relational graph, keyed in the 22001+ range:

    DetailMasterTable (what shows in the style picker)
      -> DetailStyle (title formats, Request1..Request10)
           -> DetViewRequest (one per view: scale, view box, clipping, ...)
                -> DetViewSystemAndBox   view coordinate system + depth box
                -> DetViewLengthClip     length clipping (break lines)
                -> DetObjReprMapsNew -> DetObjReprMapItems (Key, Order)
                       the representation rules: object set -> appearance,
                       label strategy, linetype. Evaluated top to bottom.
                -> DetViewDimStrategyNew -> DetViewDimStrategyItems (Key, Order)
                       -> DetViewDimRequestLinear -> Point1..15 -> DetViewDimPointSelection

Advance Steel ships its own column -> lookup map inside every export
(InfoTableRelations, TypeProperty='Relations'), so most dropdowns here come
straight from Autodesk's metadata. A handful of links it leaves out (or points
at a bogus table) are added in SUPPLEMENTARY_RELATIONS; each one was verified
against real export data (values fall exactly inside the target's key range).

References into AstorBase / AstorDetailsBase (Autodesk's built-in enums such as
DetObjQualifier or DetGeometricRestrictions) are NOT in the export, so those
columns show raw numbers. Nothing here invents labels for them.

Lengths are stored in millimetres. Everything is reverse engineered from
Advance Steel 2026 exports.
"""

import re
from fractions import Fraction

from utils import dim_explain

# ---------------------------------------------------------------------------
# Pure helpers (unit-tested, no database)
# ---------------------------------------------------------------------------

STYLE_MARKER_TABLES = ("DetailStyle", "DetObjReprMapItems")

# (table, column) -> (target table, bound column, displayed column)
SUPPLEMENTARY_RELATIONS = {
    ("DetObjReprMapItems", "Key"): ("DetObjReprMapsNew", "Key", "RunName"),
    ("DetObjReprMapItems", "ObjQualifier"): ("DetObjQualifierSet", "Key", "RunName"),
    ("DetObjReprMapItems", "Appearance"): ("DetObjAppearance", "Key", "RunName"),
    ("DetObjReprMapItems", "AnnotationStrategy"): ("DetObjAnnotationStrategy", "Key", "RunName"),
    ("DetObjReprMapItems", "LineType"): ("Linetypes", "Key", "LinetypeName"),
    ("DetObjAnnotationStrategy", "AnnotationType"): ("DetAnnotationType", "Key", "RunName"),
    ("DetObjAnnotationStrategy", "ArrangerStrategy"): ("DetArrangerStrategy", "Key", "RunName"),
    ("DetObjAnnotationStrategy", "Group"): ("DetObjAnnotationGroup", "Key", "RunName"),
    # InfoTableRelations points these at a non-existent "Detail" table.
    ("DetObjAppearance", "HatchVisible"): ("DetHatchSettings", "Key", "RunName"),
    ("DetObjAppearance", "HatchHidden"): ("DetHatchSettings", "Key", "RunName"),
    ("DetObjQualifierSetItem", "IdDetObjQualifierSet"): ("DetObjQualifierSet", "Key", "RunName"),
    ("DetViewDimRequestLinear", "Group"): ("DetViewDimRequestLinearGroup", "Key", "RunName"),
    # Display "RunName" is missing in InfoTableRelations for this one.
    ("DetViewDimPointSelection", "Objects"): ("DetObjQualifierSet", "Key", "RunName"),
}
for _i in range(1, 16):
    SUPPLEMENTARY_RELATIONS[("DetViewDimRequestLinear", f"Point{_i}")] = (
        "DetViewDimPointSelection", "Key", "RunName",
    )

# Autodesk entries that are simply wrong for integrity purposes: the row's own
# Key is listed as pointing at DetBaseCategories (the Category column does that).
IGNORED_RELATIONS = {("DetViewRequestCategories", "Key")}

# Values that mean "none / default" rather than a dangling reference.
NULL_REFS = {None, 0, -1, "", "0", "-1"}

# Columns stored in mm that read better as feet-inches and accept ft-in input.
LENGTH_COLUMNS = {
    "DetViewSystemAndBox": {"xDelta", "yDelta", "zDeltaFront", "zDeltaRear", "MinSizeEnv"},
    "DetViewLengthClip": {"MinRemainingLength", "MinClipIntervalLength", "Extension"},
    "DetObjReprMapItems": {"SimplifiedGap"},
    "DetViewArrangeStrategy": {"ViewDistance"},
    "DetArrangerStrategy": {f"{p}{i}" for p in ("MinDistance", "MaxDistance") for i in range(1, 11)},
}

STANDARD_SCALE_DENOMINATORS = [1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 384]

# Tables whose RunName column receives "Copy of " / "Copy (n) " when Advance
# Steel's Drawing Style Manager performs a Deep Copy (issue #16). Ordered from
# style root down to views, presentation rules/libraries, and dimension chains.
DEEP_COPY_NAME_TABLES = (
    ("DetailMasterTable", "Style picker entry"),
    ("DetailStyle", "Drawing style"),
    ("DetViewRequest", "Views"),
    ("DetViewArrangeStrategy", "View arrangement strategies"),
    ("DetViewSystemAndBox", "View coordinate system & box"),
    ("DetViewLengthClip", "Length clipping rules"),
    ("DetObjReprMapsNew", "Object presentation maps"),
    ("DetObjQualifierSet", "Model object sets"),
    ("DetObjAppearance", "Appearances"),
    ("DetHatchSettings", "Hatch settings"),
    ("DetObjAnnotationStrategy", "Labeling strategies"),
    ("DetAnnotationType", "Label formulas"),
    ("DetArrangerStrategy", "Label arranger strategies"),
    ("DetViewDimStrategyNew", "Dimension strategies"),
    ("DetViewDimRequestLinear", "Dimension requests"),
    ("DetViewDimPointSelection", "Dimension point selection rules"),
)


def format_copy_rename(raw_name, replacement_prefix=""):
    """Replace a leading 'Copy of ' / 'Copy (n) ' prefix on ``raw_name``.

    When ``replacement_prefix`` is blank, the deep-copy prefix is stripped.
    When non-blank, it replaces the deep-copy prefix (adding a separating space
    unless ``replacement_prefix`` already ends with whitespace or ``_``, and
    avoiding a duplicate prefix if the base name already starts with it).
    Returns ``(new_name, matched_prefix)`` or ``(raw_name, "")`` when the name
    has no deep-copy prefix.
    """
    prefix, base = dim_explain.split_copy_prefix(raw_name)
    if not prefix:
        return str(raw_name or ""), ""
    clean_base = base.strip()
    rep = str(replacement_prefix or "").lstrip()
    if not rep:
        return clean_base, prefix.strip()
    if not rep[-1].isspace() and not rep.endswith("_"):
        rep_with_sep = rep + " "
    else:
        rep_with_sep = rep
    if clean_base.lower().startswith(rep.rstrip().lower()):
        return clean_base, prefix.strip()
    return f"{rep_with_sep}{clean_base}", prefix.strip()


def plan_deep_copy_rename(rows_by_table, pk_by_table, replacement_prefix="", include_tables=None):
    """Build a preview/apply plan for renaming deep-copied RunName values.

    Pure helper (no database): ``rows_by_table`` is ``{table: [row, ...]}`` and
    ``pk_by_table`` is ``{table: [pk_col, ...]}``.
    """
    known_labels = dict(DEEP_COPY_NAME_TABLES)
    ordered_tables = [t for t, _ in DEEP_COPY_NAME_TABLES if t in rows_by_table]
    for t in sorted(rows_by_table):
        if t not in known_labels:
            ordered_tables.append(t)

    include_set = set(include_tables) if include_tables is not None else None
    available_tables = []
    planned_tables = []
    prefixes_seen = set()
    warnings = []

    for table in ordered_tables:
        pk_cols = pk_by_table.get(table) or []
        if not pk_cols:
            continue
        rows = rows_by_table.get(table) or []
        candidates = []
        untouched_names = []
        for r in rows:
            if "RunName" not in r:
                continue
            old_name = str(r.get("RunName") or "")
            new_name, matched_prefix = format_copy_rename(old_name, replacement_prefix)
            if not matched_prefix or new_name == old_name:
                if old_name.strip():
                    untouched_names.append(old_name.strip().lower())
                continue
            prefixes_seen.add(matched_prefix)
            pk = {col: r[col] for col in pk_cols}
            candidates.append({
                "pk": pk,
                "key_display": ", ".join(str(r[col]) for col in pk_cols),
                "old_name": old_name,
                "new_name": new_name,
                "prefix": matched_prefix,
                "collision": False,
            })
        if not candidates:
            continue
        selected = include_set is None or table in include_set
        label = known_labels.get(table, table)
        available_tables.append({
            "table": table,
            "label": label,
            "count": len(candidates),
            "selected": selected,
        })
        if not selected:
            continue

        final_counts = {}
        for name_lower in untouched_names:
            final_counts[name_lower] = final_counts.get(name_lower, 0) + 1
        for item in candidates:
            key = item["new_name"].strip().lower()
            final_counts[key] = final_counts.get(key, 0) + 1

        collided_names = set()
        for item in candidates:
            key = item["new_name"].strip().lower()
            if final_counts.get(key, 0) > 1:
                item["collision"] = True
                collided_names.add(item["new_name"])
        for cname in sorted(collided_names):
            warnings.append(
                f"{table}: '{cname}' would appear more than once in this table."
            )

        planned_tables.append({
            "table": table,
            "label": label,
            "pk_cols": list(pk_cols),
            "count": len(candidates),
            "rows": candidates,
        })

    return {
        "replacement_prefix": str(replacement_prefix or ""),
        "available_tables": available_tables,
        "tables": planned_tables,
        "total_rows": sum(t["count"] for t in planned_tables),
        "total_available_rows": sum(t["count"] for t in available_tables),
        "prefixes_seen": sorted(prefixes_seen),
        "warnings": warnings,
    }


def _clean_col(name):
    """InfoTableRelations sometimes has 'CompanyText AS Ausdr1'."""
    if name is None:
        return None
    return re.split(r"\s+AS\s+", str(name), flags=re.I)[0].strip() or None


def parse_relations(rows, present_tables):
    """Turn InfoTableRelations rows into {(table, column): relation}.

    relation = {"table", "bind", "display", "local", "external_db", "source"}.
    local=True only when the target table is inside this export, so it can be
    offered as a dropdown and integrity-checked. Supplementary relations win
    over Autodesk's rows for the same column (they fix known-bad entries)."""
    present = set(present_tables)
    rels = {}
    for r in rows:
        if (r.get("TypeProperty") or "") != "Relations":
            continue
        table, col = r.get("TableName"), r.get("ColumnName")
        target = (r.get("ReferToTable") or "").strip() or None
        ext_db = (r.get("ReferToDB") or "").strip() or None
        if ext_db and ext_db.lower() in ("none",):
            ext_db = None
        bind = _clean_col(r.get("ReferToBindedColumn"))
        display = _clean_col(r.get("ReferToDisplayedColumn")) or bind
        if not table or not col or not target or (table, col) in IGNORED_RELATIONS:
            continue
        rels[(table, col)] = {
            "table": target, "bind": bind, "display": display,
            "external_db": ext_db,
            "local": (ext_db is None and target in present and bool(bind)),
            "source": "InfoTableRelations",
        }
    for (table, col), (target, bind, display) in SUPPLEMENTARY_RELATIONS.items():
        if table not in present:
            continue
        rels[(table, col)] = {
            "table": target, "bind": bind, "display": display, "external_db": None,
            "local": target in present, "source": "verified-from-data",
        }
    return rels


def scale_denominator(value):
    """0.0625 -> 16. None when not a clean 1:N scale."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    n = 1.0 / v
    return int(round(n)) if abs(n - round(n)) < 1e-6 else None


def scale_label(value):
    """0.0625 -> '1:16 (3/4" = 1'-0")'. Imperial part only when it's a tidy fraction."""
    n = scale_denominator(value)
    if not n:
        return str(value)
    per_ft = Fraction(12, n)  # inches of paper per foot of model
    if per_ft.denominator in (1, 2, 4, 8, 16, 32, 64):
        whole, rem = divmod(per_ft.numerator, per_ft.denominator)
        frac = Fraction(rem, per_ft.denominator)
        txt = (f"{whole} " if whole else "") + (f"{frac.numerator}/{frac.denominator}" if frac else "")
        txt = txt.strip() or "0"
        return f'1:{n} ({txt}" = 1\'-0")'
    return f"1:{n}"


def format_ft_in(mm, denom=16):
    """609.6 -> 2'-0". 12.7 -> 1/2". Nearest 1/denom inch, '≈' when rounded."""
    if mm is None:
        return ""
    try:
        mm = float(mm)
    except (TypeError, ValueError):
        return ""
    neg = mm < 0
    inches = abs(mm) / 25.4
    snapped = round(inches * denom) / denom
    approx = abs(snapped - inches) > 1e-4
    feet = int(snapped // 12)
    rem = Fraction(snapped - feet * 12).limit_denominator(denom)
    whole_in, frac = divmod(rem.numerator, rem.denominator)
    frac = Fraction(frac, rem.denominator)
    in_txt = str(whole_in) if whole_in or not frac else ""
    if frac:
        in_txt = (in_txt + " " if in_txt else "") + f"{frac.numerator}/{frac.denominator}"
    if feet:
        txt = f"{feet}'-{in_txt or '0'}\""
    else:
        txt = f'{in_txt or "0"}"'
    return ("≈ " if approx else "") + ("-" if neg else "") + txt


_FTIN = re.compile(
    r"""^\s*(?:(?P<ft>-?\d+(?:\.\d+)?)\s*'\s*-?\s*)?
        (?:(?P<inw>\d+(?:\.\d+)?)?\s*(?:(?P<num>\d+)\s*/\s*(?P<den>\d+))?\s*"?)?\s*$""",
    re.X,
)


def parse_length(text):
    """'2\\'' / '1\\'-6 1/2"' / '3/4"' / '24"' -> mm. Plain numbers are mm.
    Raises ValueError on junk."""
    if text is None:
        return None
    t = str(text).strip()
    if t == "":
        return None
    if "'" not in t and '"' not in t:
        return float(t)
    m = _FTIN.match(t)
    if not m or not any(m.group(g) for g in ("ft", "inw", "num")):
        raise ValueError(f"Can't read length {text!r}")
    ft = float(m.group("ft") or 0)
    inches = float(m.group("inw") or 0)
    if m.group("num"):
        den = int(m.group("den"))
        if den == 0:
            raise ValueError(f"Can't read length {text!r}")
        inches += int(m.group("num")) / den
    sign = -1 if ft < 0 else 1
    return round(sign * (abs(ft) * 12 + inches) * 25.4, 6)


# --- label formula parsing (DetAnnotationType.Content, DetailStyle.TitleFormat)

# Sample values for the preview only. The field names come from the token table
# in Autodesk's Advance Steel 2016 Drawing Style Manager guide (plus the fields
# seen in the checked-in exports), so a documented token previews as a value
# instead of an "unknown" placeholder.
KNOWN_FIELDS = {
    "Note": "A", "ViewNumber": "3", "Scale": "3/4\"=1'-0\"", "Date": "10/30/26",
    "MainPartPosNum": "B12", "MainPartPos": "B12", "Position": "b104", "Name": "BEAM",
    "Denotation": "GR-1", "ItemNumber": "C7", "BoltCount": "6", "Diameter": "3/4\"",
    "Length": "2 1/4\"", "Norm": "A325N", "AnchorPartName": "AB-1",
    "Material": "A992", "Section": "W12X26", "Level": "+12'-0\"",
    # Autodesk guide tokens
    "ProfName": "IPE 300", "RodCount": "12", "Coating": "HDG", "PosNum": "P24",
    "Width": "8\"", "Thickness": "1/2\"", "HoleDiameter": "7/8\"",
    "Assembly": "B-12", "SunkDepth": "1/4\"", "Tapping": "LH", "Set": "Mu2S",
    "HeadDiameter": "1 1/4\"", "Alpha_e": "45\u00b0", "Quantity": "4",
    "MainPartQuantity": "2", "Role": "Beam", "USDate": "10/30/2026",
    "Time": "13:45", "Day": "30", "Month": "10", "Year": "2026",
    "Hour": "13", "Minute": "45", "AssemblyLength": "2 1/4\"",
    "FlangeThickness": "3/8\"", "WebThickness": "1/4\"", "AxisLength": "12'-0\"",
}
for _i in range(1, 11):
    KNOWN_FIELDS[f"UserAttr{_i}"] = f"UA{_i}"
for _i in range(1, 5):
    KNOWN_FIELDS[f"ExtName{_i}"] = f"EN-{_i}"

# AutoCAD-style symbol escapes used by label formulas (guide: "special symbols
# can be inserted using ASCII codes", e.g. %%c for the diameter sign).
SYMBOL_ESCAPES = {"c": "\u00d8", "d": "\u00b0", "p": "\u00b1", "%": "%"}

ACI_COLORS = {1: "#d62728", 2: "#c9a400", 3: "#2ca02c", 4: "#17becf", 5: "#1f4fd6",
              6: "#c41fc4", 7: "#111"}
FRAME_COMMANDS = {"Rounded", "Rectangle", "Frame", "Circle", "Box"}

_TOKEN = re.compile(
    r"#(?P<cmd>[A-Za-z]+)(?:\((?P<arg>[^)]*)\))?"
    r"|%%(?P<escape>[cdp%])"
    r"|%(?P<field>[A-Za-z][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _split_field(name):
    """Greedy %Name may swallow trailing text ('%BoltCountx'). Prefer the
    longest known field prefix and hand back the leftover as literal text."""
    if name in KNOWN_FIELDS:
        return name, ""
    for i in range(len(name) - 1, 0, -1):
        if name[:i] in KNOWN_FIELDS:
            return name[:i], name[i:]
    return name, ""


def parse_label_format(content):
    """Parse an AS label/title formula into renderable lines.

    Returns {"lines": [[seg, ...], ...], "fields": [...], "commands": [...]}
    where seg is {"kind": "text"|"field"|"frame_open"|"frame_close"|"cmd", ...}
    carrying the current style (height mm, bold, underline, color)."""
    content = content or ""
    style = {"height": None, "bold": False, "underline": False, "color": None, "italic": False}
    lines = [[]]
    fields, commands = [], []
    frame_open = False
    pos = 0

    def emit(kind, **kw):
        seg = {"kind": kind, **style, **kw}
        lines[-1].append(seg)

    def text(t):
        if t:
            emit("text", text=t)

    for m in _TOKEN.finditer(content):
        text(content[pos:m.start()])
        pos = m.end()
        if m.group("escape"):
            text(SYMBOL_ESCAPES.get(m.group("escape").lower(), m.group(0)))
            continue
        if m.group("field"):
            name, rest = _split_field(m.group("field"))
            fields.append(name)
            emit("field", field=name, sample=KNOWN_FIELDS.get(name, f"<{name}>"),
                 known=name in KNOWN_FIELDS)
            text(rest)
            continue
        cmd, arg = m.group("cmd"), m.group("arg")
        commands.append(cmd)
        if cmd == "Newline":
            if frame_open:
                emit("frame_close")
            lines.append([])
            if frame_open:
                emit("frame_open")
        elif cmd == "Height":
            try:
                style["height"] = float(arg)
            except (TypeError, ValueError):
                emit("cmd", text=m.group(0))
        elif cmd in ("Bold", "Underline", "Italic"):
            style[cmd.lower()] = (str(arg).strip() != "0") if arg is not None else True
        elif cmd == "Color":
            try:
                style["color"] = ACI_COLORS.get(int(arg))
            except (TypeError, ValueError):
                style["color"] = None
        elif cmd in FRAME_COMMANDS:
            if not frame_open:
                emit("frame_open", frame=cmd)
                frame_open = True
        elif cmd == "End":
            if frame_open:
                emit("frame_close")
                frame_open = False
        else:
            emit("cmd", text=m.group(0))
    text(content[pos:])
    if frame_open:
        emit("frame_close")
    # drop a trailing empty line created by a closing #Newline
    if len(lines) > 1 and not [s for s in lines[-1] if s["kind"] in ("text", "field")]:
        lines.pop()
    return {"lines": lines, "fields": fields, "commands": commands}


def find_dangling(relations, column_values, target_keys):
    """Pure integrity core.

    column_values: {(table, col): set(values present)}
    target_keys:   {(table, bind_col): set(keys present)}
    -> list of {"table","column","target","missing":[...]}"""
    out = []
    for (table, col), rel in sorted(relations.items()):
        if not rel.get("local"):
            continue
        vals = column_values.get((table, col))
        if not vals:
            continue
        keys = target_keys.get((rel["table"], rel["bind"]), set())
        keys_s = {str(k) for k in keys}
        missing = sorted(
            {v for v in vals if v not in NULL_REFS and str(v) not in keys_s}, key=str,
        )
        if missing:
            out.append({"table": table, "column": col, "target": rel["table"], "missing": missing})
    return out


# ---------------------------------------------------------------------------
# Database-bound
# ---------------------------------------------------------------------------

def _db():
    from utils import db  # flat import convention (see AGENTS.md)
    return db


def is_drawing_style(database):
    tables = set(_db().list_tables(database))
    return all(t in tables for t in STYLE_MARKER_TABLES)


def _rows(database, sql, params=()):
    conn, cur = _db().connect(database)
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    return rows


def load_relations(database):
    db = _db()
    tables = db.list_tables(database)
    rows = _rows(database, "SELECT * FROM InfoTableRelations") if "InfoTableRelations" in tables else []
    return parse_relations(rows, tables)


def relation_options(database, rel):
    """[(value, label)] for a local relation, ordered by label."""
    if not rel or not rel.get("local"):
        return []
    db = _db()
    cols = {c["COLUMN_NAME"] for c in db.get_columns(database, rel["table"])}
    bind = rel["bind"]
    display = rel["display"] if rel["display"] in cols else bind
    if bind not in cols:
        return []
    rows = _rows(
        database,
        f"SELECT DISTINCT [{bind}] AS v, [{display}] AS l FROM [{rel['table']}] ORDER BY [{display}]",
    )
    return [(r["v"], f"{r['l']}" if display == bind else f"{r['l']}  ·  #{r['v']}") for r in rows]


def options_for_table(database, table, relations=None):
    relations = relations if relations is not None else load_relations(database)
    out = {}
    for (t, col), rel in relations.items():
        if t == table and rel.get("local"):
            out[col] = relation_options(database, rel)
    return out


def _by_key(rows, key="Key"):
    return {r[key]: r for r in rows}


def _label_map(database, table, display="RunName"):
    try:
        return {r["Key"]: r[display] for r in _rows(database, f"SELECT [Key], [{display}] FROM [{table}]")}
    except Exception:
        return {}


def set_short_view_names(requests):
    """Menu labels: drop "Copy of" prefixes and the words every view of the
    style shares, so "6 - Railing (Mp is Handrail) - Front" reads "Front"."""
    live = [r for r in requests if not r.get("missing")]
    names = [dim_explain.clean_name(r["row"].get("RunName")) or f"view {r['row'].get('Key')}" for r in live]
    cut = 0
    if len(names) > 1:
        prefix = names[0]
        for n in names[1:]:
            while not n.startswith(prefix):
                prefix = prefix[:-1]
        # cut back to the last separator so a word is never split
        m = max(prefix.rfind(" - "), prefix.rfind(" | "))
        cut = m + 3 if m >= 0 else 0
    for r, n in zip(live, names):
        short = n[cut:].strip() if cut and n[cut:].strip() else n
        r["short_name"] = short
    return requests


def style_tree(database):
    """Everything the editor page needs, resolved to names."""
    db = _db()
    tables = set(db.list_tables(database))
    tok = db.make_row_token
    pk = {t: db.get_primary_key_columns(database, t) for t in tables}

    def tokrow(table, row):
        return {"row": row, "token": tok(row, pk[table]) if pk.get(table) else None}

    names = {
        "appearance": _label_map(database, "DetObjAppearance"),
        "annot_strategy": _label_map(database, "DetObjAnnotationStrategy"),
        "qset": _label_map(database, "DetObjQualifierSet"),
        "linetype": _label_map(database, "Linetypes", "LinetypeName"),
        "annot_type": _label_map(database, "DetAnnotationType"),
        "point": _label_map(database, "DetViewDimPointSelection"),
        "dim_group": _label_map(database, "DetViewDimRequestLinearGroup"),
    }
    annot_types = _by_key(_rows(database, "SELECT * FROM DetAnnotationType")) if "DetAnnotationType" in tables else {}
    strategies = _by_key(_rows(database, "SELECT * FROM DetObjAnnotationStrategy")) if "DetObjAnnotationStrategy" in tables else {}

    def strategy_preview(skey):
        s = strategies.get(skey)
        if not s:
            return None
        t = annot_types.get(s.get("AnnotationType"))
        return parse_label_format(t["Content"]) if t else None

    styles = _by_key(_rows(database, "SELECT * FROM DetailStyle"))
    requests = _by_key(_rows(database, "SELECT * FROM DetViewRequest"))
    sysbox = _by_key(_rows(database, "SELECT * FROM DetViewSystemAndBox")) if "DetViewSystemAndBox" in tables else {}
    clips = _by_key(_rows(database, "SELECT * FROM DetViewLengthClip")) if "DetViewLengthClip" in tables else {}
    rmaps = _by_key(_rows(database, "SELECT * FROM DetObjReprMapsNew")) if "DetObjReprMapsNew" in tables else {}
    ritems = _rows(database, "SELECT * FROM DetObjReprMapItems ORDER BY [Key], [Order]")
    dstrats = _by_key(_rows(database, "SELECT * FROM DetViewDimStrategyNew")) if "DetViewDimStrategyNew" in tables else {}
    ditems = _rows(database, "SELECT * FROM DetViewDimStrategyItems ORDER BY [Key], [Order]") if "DetViewDimStrategyItems" in tables else []
    dlins = _by_key(_rows(database, "SELECT * FROM DetViewDimRequestLinear")) if "DetViewDimRequestLinear" in tables else {}
    dpoints = _by_key(_rows(database, "SELECT * FROM DetViewDimPointSelection")) if "DetViewDimPointSelection" in tables else {}
    varrange = _by_key(_rows(database, "SELECT * FROM DetViewArrangeStrategy")) if "DetViewArrangeStrategy" in tables else {}

    def build_request(rk):
        r = requests.get(rk)
        if not r:
            return {"missing": rk}
        items = []
        for it in ritems:
            if it["Key"] != r.get("ObjReprMap"):
                continue
            d = tokrow("DetObjReprMapItems", it)
            d.update({
                "qset_name": names["qset"].get(it["ObjQualifier"], f"#{it['ObjQualifier']}"),
                "appearance_name": names["appearance"].get(it["Appearance"], f"#{it['Appearance']}"),
                "strategy_name": names["annot_strategy"].get(it["AnnotationStrategy"], f"#{it['AnnotationStrategy']}"),
                "linetype_name": names["linetype"].get(it["LineType"], f"#{it['LineType']}"),
                "label": strategy_preview(it["AnnotationStrategy"]),
            })
            items.append(d)
        dims = []
        # DetViewDimStrategyNew.Items names the item list; it has matched the
        # strategy's own Key in every export seen, so fall back to that.
        strat = dstrats.get(r.get("DimStrategy")) or {}
        items_key = strat.get("Items") if strat.get("Items") not in NULL_REFS else r.get("DimStrategy")
        for di in ditems:
            if di["Key"] != items_key:
                continue
            lin = dlins.get(di["RequestLinear"])
            pts, pkeys = [], []
            if lin:
                for i in range(1, int(lin.get("Number of Points") or 0) + 1):
                    pkey = lin.get(f"Point{i}")
                    pts.append(names["point"].get(pkey, f"#{pkey}"))
                    pkeys.append(pkey)
            dims.append({
                **tokrow("DetViewDimStrategyItems", di),
                "linear": tokrow("DetViewDimRequestLinear", lin) if lin else None,
                "points": pts,
                "point_keys": pkeys,
            })
        explained = dim_explain.explain_strategy(dims, dpoints, names["qset"], names["dim_group"])
        for d, e in zip(dims, explained):
            d["explain"] = e
            d["point_rows"] = [
                tokrow("DetViewDimPointSelection", dpoints[k]) for k in d["point_keys"] if k in dpoints
            ]
        sb = sysbox.get(r.get("SystemAndBox"))
        cl = clips.get(r.get("LengthclipXY"))
        rm = rmaps.get(r.get("ObjReprMap"))
        ds = dstrats.get(r.get("DimStrategy"))
        return {
            **tokrow("DetViewRequest", r),
            "scale_label": scale_label(r.get("Scale")),
            "scale_denom": scale_denominator(r.get("Scale")),
            "sysbox": tokrow("DetViewSystemAndBox", sb) if sb else None,
            "clip": tokrow("DetViewLengthClip", cl) if cl else None,
            "repr_map": tokrow("DetObjReprMapsNew", rm) if rm else None,
            "repr_items": items,
            "dim_strategy": tokrow("DetViewDimStrategyNew", ds) if ds else None,
            "dims": dims,
        }

    masters = []
    for m in _rows(database, "SELECT * FROM DetailMasterTable"):
        s = styles.get(m["StyleKey"])
        style = None
        if s:
            n = int(s.get("Number of items") or 0)
            reqs = [s.get(f"Request{i}") for i in range(1, 11)]
            reqs = [k for k in reqs[: max(n, 0)] if k not in NULL_REFS] or [k for k in reqs if k not in NULL_REFS]
            style = {
                **tokrow("DetailStyle", s),
                "title_preview": parse_label_format(s.get("TitleFormat")),
                "cut_title_preview": parse_label_format(s.get("CutViewTitleFormat")),
                "arrange": tokrow("DetViewArrangeStrategy", varrange[s["ViewArrangeStrategy"]])
                if s.get("ViewArrangeStrategy") in varrange else None,
                "requests": [build_request(k) for k in reqs],
            }
            set_short_view_names(style["requests"])
        masters.append({**tokrow("DetailMasterTable", m), "style": style})

    libraries = {}
    for t in ("DetAnnotationType", "DetObjAnnotationStrategy", "DetObjAppearance",
              "DetObjQualifierSet", "DetHatchSettings", "Linetypes", "DetArrangerStrategy"):
        if t in tables:
            order = "[Key]"
            libraries[t] = [tokrow(t, r) for r in _rows(database, f"SELECT * FROM [{t}] ORDER BY {order}")]
    for entry in libraries.get("DetAnnotationType", []):
        entry["preview"] = parse_label_format(entry["row"].get("Content"))

    qset_items = {}
    if "DetObjQualifierSetItem" in tables:
        for it in _rows(database, "SELECT * FROM DetObjQualifierSetItem ORDER BY [Key]"):
            qset_items.setdefault(it["IdDetObjQualifierSet"], []).append(it)

    return {"masters": masters, "libraries": libraries, "qset_items": qset_items}


def repr_block(database, map_key, relations=None, uid=None):
    """One representation map's rules, for an in-place partial re-render.

    Rule actions (move / copy / delete / renumber) only need this block, so
    the editor can swap it without rebuilding the whole style page.

    `uid` scopes the block's element ids. A representation map can be shared by
    several views, so the page passes "<view key>-<map key>"; the standalone
    fragment falls back to the map key, which is unique within one request.
    """
    db = _db()
    tables = set(db.list_tables(database))
    tok = db.make_row_token
    pk_items = db.get_primary_key_columns(database, "DetObjReprMapItems")

    names = {
        "qset": _label_map(database, "DetObjQualifierSet"),
        "appearance": _label_map(database, "DetObjAppearance"),
        "annot_strategy": _label_map(database, "DetObjAnnotationStrategy"),
        "linetype": _label_map(database, "Linetypes", "LinetypeName"),
    }
    annot_types = _by_key(_rows(database, "SELECT * FROM DetAnnotationType")) if "DetAnnotationType" in tables else {}
    strategies = _by_key(_rows(database, "SELECT * FROM DetObjAnnotationStrategy")) if "DetObjAnnotationStrategy" in tables else {}

    def strategy_preview(skey):
        strategy = strategies.get(skey)
        if not strategy:
            return None
        annot_type = annot_types.get(strategy.get("AnnotationType"))
        return parse_label_format(annot_type["Content"]) if annot_type else None

    rmap = None
    if "DetObjReprMapsNew" in tables:
        rows = _rows(database, "SELECT * FROM DetObjReprMapsNew WHERE [Key] = %s", (map_key,))
        rmap = rows[0] if rows else None
    rmap_token = None
    if rmap is not None:
        rmap_pk = db.get_primary_key_columns(database, "DetObjReprMapsNew")
        rmap_token = tok(rmap, rmap_pk) if rmap_pk else None

    items = []
    for it in _rows(database, "SELECT * FROM DetObjReprMapItems WHERE [Key] = %s ORDER BY [Order]", (map_key,)):
        entry = {"row": it, "token": tok(it, pk_items) if pk_items else None}
        entry.update({
            "qset_name": names["qset"].get(it["ObjQualifier"], f"#{it['ObjQualifier']}"),
            "appearance_name": names["appearance"].get(it["Appearance"], f"#{it['Appearance']}"),
            "strategy_name": names["annot_strategy"].get(it["AnnotationStrategy"], f"#{it['AnnotationStrategy']}"),
            "linetype_name": names["linetype"].get(it["LineType"], f"#{it['LineType']}"),
            "label": strategy_preview(it["AnnotationStrategy"]),
        })
        items.append(entry)

    return {
        "uid": uid or str(map_key),
        "map_key": map_key,
        "repr_map": {"row": rmap, "token": rmap_token},
        "repr_items": items,
        "options": options_for_table(database, "DetObjReprMapItems", relations),
    }


def all_relation_options(database, relations=None):
    """{table: {col: [(v, label)]}} for every table that has local relations."""
    relations = relations if relations is not None else load_relations(database)
    out = {}
    cache = {}
    for (t, col), rel in relations.items():
        if not rel.get("local"):
            continue
        ck = (rel["table"], rel["bind"], rel["display"])
        if ck not in cache:
            cache[ck] = relation_options(database, rel)
        out.setdefault(t, {})[col] = cache[ck]
    return out


def apply_field_edits(database, edits, relations=None):
    """edits: list of (table, token, column, raw_text). Groups by row, coerces
    types (ft-in accepted on length columns), validates local relations, and
    updates each row with the exactly-one-row guard. Returns (n_rows, errors)."""
    db = _db()
    tables = set(db.list_tables(database))
    relations = relations if relations is not None else load_relations(database)
    grouped = {}
    errors = []
    for table, token, col, raw in edits:
        if table not in tables:
            errors.append(f"Unknown table {table}")
            continue
        grouped.setdefault((table, token), {})[col] = raw

    opts_cache = {}
    n = 0
    for (table, token), cols in grouped.items():
        types = {c["COLUMN_NAME"]: c["DATA_TYPE"] for c in db.get_columns(database, table)}
        pk_cols = db.get_primary_key_columns(database, table)
        try:
            pk = db.parse_row_token(token, pk_cols)
        except ValueError as e:
            errors.append(f"{table}: {e}")
            continue
        updates = {}
        for col, raw in cols.items():
            if col not in types:
                errors.append(f"{table}.{col}: unknown column")
                continue
            if col in pk_cols:
                errors.append(f"{table}.{col}: key columns can't be edited here")
                continue
            try:
                if col in LENGTH_COLUMNS.get(table, ()) and types[col] in ("float", "real", "decimal", "numeric"):
                    val = parse_length(raw)
                else:
                    val = db.coerce_value(raw, types[col])
            except ValueError as e:
                errors.append(f"{table}.{col}: {e}")
                continue
            rel = relations.get((table, col))
            if rel and rel.get("local") and val not in NULL_REFS:
                key = (rel["table"], rel["bind"], rel["display"])
                if key not in opts_cache:
                    opts_cache[key] = {str(v) for v, _ in relation_options(database, rel)}
                if str(val) not in opts_cache[key]:
                    errors.append(f"{table}.{col}: {val} isn't a valid {rel['table']} entry")
                    continue
            updates[col] = val
        if updates:
            try:
                db.update_row(database, table, pk, updates)
                n += 1
            except Exception as e:
                errors.append(f"{table}: {e}")
    return n, errors


def move_repr_item(database, map_key, order, direction):
    """Swap a representation rule with its neighbour (direction -1 up / +1 down).
    Order is part of the PK, so swap through a temporary value in one transaction."""
    db = _db()
    rows = _rows(database, "SELECT [Order] FROM DetObjReprMapItems WHERE [Key] = %s ORDER BY [Order]", (map_key,))
    orders = [r["Order"] for r in rows]
    if order not in orders:
        raise ValueError("Rule not found.")
    i = orders.index(order)
    j = i + (-1 if direction < 0 else 1)
    if j < 0 or j >= len(orders):
        return False
    a, b = orders[i], orders[j]
    tmp = -999999
    conn, cur = db.connect(database)
    conn.autocommit(False)
    try:
        q = "UPDATE DetObjReprMapItems SET [Order] = %s WHERE [Key] = %s AND [Order] = %s"
        cur.execute(q, (tmp, map_key, a))
        cur.execute(q, (a, map_key, b))
        cur.execute(q, (b, map_key, tmp))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True


def compact_repr_orders(database, map_key):
    """Renumber Order 0..n-1 after deletes so there are no gaps."""
    db = _db()
    rows = _rows(database, "SELECT [Order] FROM DetObjReprMapItems WHERE [Key] = %s ORDER BY [Order]", (map_key,))
    orders = [r["Order"] for r in rows]
    if orders == list(range(len(orders))):
        return
    conn, cur = db.connect(database)
    conn.autocommit(False)
    try:
        q = "UPDATE DetObjReprMapItems SET [Order] = %s WHERE [Key] = %s AND [Order] = %s"
        for i, o in enumerate(orders):
            cur.execute(q, (-1000000 - i, map_key, o))
        for i in range(len(orders)):
            cur.execute(q, (i, map_key, -1000000 - i))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_repr_item_after(database, map_key, order):
    """Copy a rule and place the copy directly below it."""
    db = _db()
    src = db.get_row(database, "DetObjReprMapItems", {"Key": map_key, "Order": order})
    if not src:
        raise ValueError("Rule not found.")
    conn, cur = db.connect(database)
    conn.autocommit(False)
    try:
        cur.execute(
            "SELECT [Order] FROM DetObjReprMapItems WHERE [Key] = %s AND [Order] > %s ORDER BY [Order] DESC",
            (map_key, order),
        )
        for r in cur.fetchall():  # shift everything below down by one, bottom first
            cur.execute(
                "UPDATE DetObjReprMapItems SET [Order] = [Order] + 1 WHERE [Key] = %s AND [Order] = %s",
                (map_key, r["Order"]),
            )
        new = dict(src)
        new["Order"] = order + 1
        cols = list(new.keys())
        cur.execute(
            f"INSERT INTO DetObjReprMapItems ({', '.join(f'[{c}]' for c in cols)}) "
            f"VALUES ({', '.join(['%s'] * len(cols))})",
            [new[c] for c in cols],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return order + 1


def integrity_report(database, relations=None):
    """Dangling local references + a few structural checks."""
    db = _db()
    tables = set(db.list_tables(database))
    relations = relations if relations is not None else load_relations(database)
    col_vals, tgt_keys = {}, {}
    for (t, col), rel in relations.items():
        if not rel.get("local") or t not in tables:
            continue
        cols = {c["COLUMN_NAME"] for c in db.get_columns(database, t)}
        if col not in cols:
            continue
        col_vals[(t, col)] = {r["v"] for r in _rows(database, f"SELECT DISTINCT [{col}] AS v FROM [{t}]")}
        tk = (rel["table"], rel["bind"])
        if tk not in tgt_keys:
            tcols = {c["COLUMN_NAME"] for c in db.get_columns(database, rel["table"])}
            tgt_keys[tk] = (
                {r["v"] for r in _rows(database, f"SELECT DISTINCT [{rel['bind']}] AS v FROM [{rel['table']}]")}
                if rel["bind"] in tcols else set()
            )
    problems = find_dangling(relations, col_vals, tgt_keys)

    notes = []
    for s in _rows(database, "SELECT * FROM DetailStyle"):
        used = [s.get(f"Request{i}") for i in range(1, 11)]
        used = [k for k in used if k not in NULL_REFS]
        n = int(s.get("Number of items") or 0)
        if n != len(used):
            notes.append(
                f"DetailStyle '{s['RunName']}': 'Number of items' = {n} but {len(used)} Request columns are set."
            )
    if "DetObjReprMapItems" in tables:
        for r in _rows(database, "SELECT [Key], COUNT(*) AS n, MIN([Order]) AS lo, MAX([Order]) AS hi "
                                 "FROM DetObjReprMapItems GROUP BY [Key]"):
            if r["lo"] != 0 or r["hi"] != r["n"] - 1:
                notes.append(
                    f"Representation map {r['Key']}: rule order isn't 0..{r['n'] - 1} "
                    f"(found {r['lo']}..{r['hi']}). Use 'Renumber' to compact it."
                )
    return {"dangling": problems, "notes": notes,
            "checked": sum(1 for r in relations.values() if r.get("local"))}


def preview_deep_copy_rename(database, replacement_prefix="", include_tables=None):
    """Scan a drawing-style export for 'Copy of ' / 'Copy (n) ' RunName values."""
    db = _db()
    present_tables = db.list_tables(database)
    rows_by_table = {}
    pk_by_table = {}
    for table in present_tables:
        cols = {c["COLUMN_NAME"] for c in db.get_columns(database, table)}
        if "RunName" not in cols:
            continue
        pk_cols = db.get_primary_key_columns(database, table)
        if not pk_cols or not all(c in cols for c in pk_cols):
            continue
        select_cols = list(dict.fromkeys(list(pk_cols) + ["RunName"]))
        col_sql = ", ".join(f"[{c}]" for c in select_cols)
        order_sql = ", ".join(f"[{c}]" for c in pk_cols)
        rows_by_table[table] = _rows(
            database, f"SELECT {col_sql} FROM [{table}] ORDER BY {order_sql}"
        )
        pk_by_table[table] = pk_cols

    plan = plan_deep_copy_rename(
        rows_by_table,
        pk_by_table,
        replacement_prefix=replacement_prefix,
        include_tables=include_tables,
    )
    for tbl in plan["tables"]:
        for item in tbl["rows"]:
            item["token"] = db.make_row_token(item["pk"], tbl["pk_cols"])
    return plan


def apply_deep_copy_rename(database, replacement_prefix="", include_tables=None):
    """Rename deep-copied RunName values across the selected tables in one transaction."""
    db = _db()
    plan = preview_deep_copy_rename(
        database,
        replacement_prefix=replacement_prefix,
        include_tables=include_tables,
    )
    if not plan["total_rows"]:
        return {}

    conn, cur = db.connect(database)
    conn.autocommit(False)
    counts = {}
    try:
        for tbl in plan["tables"]:
            table = tbl["table"]
            pk_cols = tbl["pk_cols"]
            where_sql = " AND ".join(f"[{c}] = %s" for c in pk_cols)
            sql = f"UPDATE [{table}] SET [RunName] = %s WHERE {where_sql}"
            for item in tbl["rows"]:
                params = [item["new_name"]] + [item["pk"][c] for c in pk_cols]
                cur.execute(sql, params)
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"Expected 1 row updated in {table} ({item['key_display']}), "
                        f"got {cur.rowcount}."
                    )
            counts[table] = tbl["count"]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return counts
