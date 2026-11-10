"""Pure-function tests for drawing-style exports and composite-key row tokens.
No database needed."""

import pytest

from utils import drawing_styles as ds
from utils import db


# --- relations --------------------------------------------------------------

REL_ROWS = [
    {"TableName": "DetViewRequest", "ColumnName": "SystemAndBox", "TypeProperty": "Relations",
     "ReferToDB": "", "ReferToTable": "DetViewSystemAndBox", "ReferToBindedColumn": "Key",
     "ReferToDisplayedColumn": "RunName"},
    {"TableName": "DetViewRequest", "ColumnName": "Scale", "TypeProperty": "Relations",
     "ReferToDB": "AstorBase", "ReferToTable": "Scale", "ReferToBindedColumn": "Value",
     "ReferToDisplayedColumn": "RunName"},
    {"TableName": "DetailMasterTable", "ColumnName": "OwnerText", "TypeProperty": "Relations",
     "ReferToDB": "AstorBase", "ReferToTable": "Authors", "ReferToBindedColumn": "CompanyText AS Ausdr1",
     "ReferToDisplayedColumn": "CompanyName AS Ausdr2"},
    {"TableName": "DetObjAppearance", "ColumnName": "HatchVisible", "TypeProperty": "Relations",
     "ReferToDB": "", "ReferToTable": "Detail", "ReferToBindedColumn": "", "ReferToDisplayedColumn": ""},
    {"TableName": "DetViewRequestCategories", "ColumnName": "Key", "TypeProperty": "Relations",
     "ReferToDB": "", "ReferToTable": "DetBaseCategories", "ReferToBindedColumn": "Key",
     "ReferToDisplayedColumn": "Category"},
    {"TableName": "DetailStyle", "ColumnName": "Key", "TypeProperty": "PrimaryKey"},
]
PRESENT = ["DetViewRequest", "DetViewSystemAndBox", "DetailMasterTable", "DetObjAppearance",
           "DetHatchSettings", "DetObjReprMapItems", "DetObjAppearance", "Linetypes",
           "DetViewRequestCategories", "DetBaseCategories"]


def test_parse_relations_local_vs_external():
    rels = ds.parse_relations(REL_ROWS, PRESENT)
    sb = rels[("DetViewRequest", "SystemAndBox")]
    assert sb["local"] and sb["table"] == "DetViewSystemAndBox" and sb["display"] == "RunName"
    assert not rels[("DetViewRequest", "Scale")]["local"]
    owner = rels[("DetailMasterTable", "OwnerText")]
    assert owner["bind"] == "CompanyText" and owner["display"] == "CompanyName"


def test_parse_relations_supplementary_fixes_and_ignores():
    rels = ds.parse_relations(REL_ROWS, PRESENT)
    hv = rels[("DetObjAppearance", "HatchVisible")]
    assert hv["table"] == "DetHatchSettings" and hv["local"]
    assert rels[("DetObjReprMapItems", "Appearance")]["table"] == "DetObjAppearance"
    assert ("DetViewRequestCategories", "Key") not in rels
    # supplementary entries for tables not in the file are skipped
    assert ("DetViewDimRequestLinear", "Point1") not in rels


# --- scales & lengths -----------------------------------------------------------

@pytest.mark.parametrize("value,label", [
    (0.0625, '1:16 (3/4" = 1\'-0")'),
    (1 / 96, '1:96 (1/8" = 1\'-0")'),
    (0.25, '1:4 (3" = 1\'-0")'),
    (1.0, '1:1 (12" = 1\'-0")'),
    (1 / 192, '1:192 (1/16" = 1\'-0")'),
    (1 / 7, "1:7"),
])
def test_scale_label(value, label):
    assert ds.scale_label(value) == label


def test_scale_denominator_rejects_junk():
    assert ds.scale_denominator(0) is None
    assert ds.scale_denominator("x") is None
    assert ds.scale_denominator(0.3) is None


@pytest.mark.parametrize("mm,text", [
    (609.6, "2'-0\""), (609.5999999999999, "2'-0\""), (101.6, '4"'), (12.7, '1/2"'),
    (38.1, '1 1/2"'), (0, '0"'), (476.25, "1'-6 3/4\""), (2.54, '≈ 1/8"'),
])
def test_format_ft_in(mm, text):
    assert ds.format_ft_in(mm) == text


@pytest.mark.parametrize("text,mm", [
    ("3'", 914.4), ("2'-0\"", 609.6), ("1'-6 1/2\"", 469.9), ('3/4"', 19.05),
    ('24"', 609.6), ("101.6", 101.6), ("1' 6\"", 457.2), ("", None),
])
def test_parse_length(text, mm):
    got = ds.parse_length(text)
    assert got == (pytest.approx(mm) if mm is not None else None)


@pytest.mark.parametrize("bad", ["abc'", "1/0\"", "'"])
def test_parse_length_rejects_junk(bad):
    with pytest.raises(ValueError):
        ds.parse_length(bad)


def test_length_roundtrip_display_then_parse():
    for mm in (609.6, 101.6, 12.7, 914.4, 457.2):
        assert ds.parse_length(ds.format_ft_in(mm)) == pytest.approx(mm)


# --- label formulas -------------------------------------------------------------

def test_label_parse_splits_greedy_field():
    p = ds.parse_label_format('%BoltCountx%Diameterøx%Length#Newline%Norm')
    assert p["fields"] == ["BoltCount", "Diameter", "Length", "Norm"]
    line1 = [s for s in p["lines"][0] if s["kind"] in ("text", "field")]
    assert [s.get("field") or s["text"] for s in line1] == ["BoltCount", "x", "Diameter", "øx", "Length"]
    assert len(p["lines"]) == 2


def test_label_parse_styles_and_frame():
    p = ds.parse_label_format(
        "#Color(1)#Bold(1)%UserAttr1#Newline#Color(257)#Bold(0)#Rounded#Bold(1)%MainPartPosNum#End "
        "#Newline#Height(1.60)%Name"
    )
    l1, l2, l3 = p["lines"]
    ua = [s for s in l1 if s["kind"] == "field"][0]
    assert ua["bold"] and ua["color"] == ds.ACI_COLORS[1]
    kinds = [s["kind"] for s in l2]
    assert kinds[0] == "frame_open" and "frame_close" in kinds
    mp = [s for s in l2 if s["kind"] == "field"][0]
    assert mp["bold"] and mp["color"] is None
    assert [s for s in l3 if s["kind"] == "field"][0]["height"] == 1.6


def test_label_parse_italic_flag():
    p = ds.parse_label_format("#Italic(1)%Name#Newline#Italic(0)%Note")
    name = [s for s in p["lines"][0] if s["kind"] == "field"][0]
    note = [s for s in p["lines"][1] if s["kind"] == "field"][0]
    assert name["italic"] and not note["italic"]
    assert not [s for line in p["lines"] for s in line if s["kind"] == "cmd"]


def test_label_parse_frame_across_newline_stays_balanced():
    p = ds.parse_label_format("#Rounded%Position#Newline%Name#End")
    for line in p["lines"]:
        opens = sum(1 for s in line if s["kind"] == "frame_open")
        closes = sum(1 for s in line if s["kind"] == "frame_close")
        assert opens == closes


def test_label_parse_title_trailing_newline_and_unknown():
    p = ds.parse_label_format("#Height(6.40)#Underline(1)SECTION %Note-%Note#Newline#Foo(2)%Zork#Newline")
    assert len(p["lines"]) == 2
    assert any(s["kind"] == "cmd" and s["text"] == "#Foo(2)" for s in p["lines"][1])
    zork = [s for s in p["lines"][1] if s["kind"] == "field"][0]
    assert zork["field"] == "Zork" and not zork["known"]


def test_label_parse_empty():
    assert ds.parse_label_format("")["lines"] == [[]]
    assert ds.parse_label_format(None)["fields"] == []


# --- integrity --------------------------------------------------------------------

def test_find_dangling():
    rels = {
        ("A", "x"): {"local": True, "table": "B", "bind": "Key"},
        ("A", "y"): {"local": False, "table": "Ext", "bind": "Key"},
        ("A", "z"): {"local": True, "table": "C", "bind": "Key"},
    }
    vals = {("A", "x"): {1, 2, 0, -1, None}, ("A", "y"): {999}, ("A", "z"): {"5"}}
    keys = {("B", "Key"): {1}, ("C", "Key"): {5}}
    out = ds.find_dangling(rels, vals, keys)
    assert out == [{"table": "A", "column": "x", "target": "B", "missing": [2]}]


# --- composite row tokens ---------------------------------------------------------

def test_row_token_single_is_raw_value():
    assert db.make_row_token({"Key": 22001}, ["Key"]) == "22001"
    assert db.parse_row_token("22001", ["Key"]) == {"Key": "22001"}


def test_row_token_composite_roundtrip():
    cols = ["Key", "Order"]
    tok = db.make_row_token({"Key": 22001, "Order": 7, "Other": "x"}, cols)
    assert tok.startswith(db.COMPOSITE_TOKEN_PREFIX) and "/" not in tok
    assert db.parse_row_token(tok, cols) == {"Key": 22001, "Order": 7}


def test_row_token_composite_rejects_single_value():
    with pytest.raises(ValueError, match="composite key"):
        db.parse_row_token("22001", ["Key", "Order"])


def test_row_token_composite_handles_floats_and_text():
    cols = ["Standard", "Diameter", "Length"]
    row = {"Standard": "A325 / TC", "Diameter": 19.05, "Length": 50.8}
    assert db.parse_row_token(db.make_row_token(row, cols), cols) == row


def test_label_parse_symbol_escapes():
    p = ds.parse_label_format("%%c20 %%C %%d %%p 100%%")
    text = "".join(s.get("text") or "" for s in p["lines"][0])
    assert text == "Ø20 Ø ° ± 100%%"
    assert not [s for s in p["lines"][0] if s["kind"] == "cmd"]


def test_label_parse_guide_tokens_preview_as_values():
    p = ds.parse_label_format("%Thickness %Width %Role %ExtName2 %UserAttr10")
    samples = [s["sample"] for s in p["lines"][0] if s["kind"] == "field"]
    assert samples == ["1/2\"", "8\"", "Beam", "EN-2", "UA10"]
    assert all(s["known"] for s in p["lines"][0] if s["kind"] == "field")


def test_short_view_names_drop_copy_and_the_shared_words():
    reqs = [{"row": {"Key": 1, "RunName": "Copy of 6 - Railing (Mp is Handrail) - Front"}},
            {"missing": 9},
            {"row": {"Key": 2, "RunName": "Copy of 6 - Railing (Mp is Handrail) - Top"}}]
    ds.set_short_view_names(reqs)
    assert reqs[0]["short_name"] == "Front" and reqs[2]["short_name"] == "Top"
    assert "short_name" not in reqs[1]


def test_short_view_names_keep_a_single_view_whole():
    reqs = [{"row": {"Key": 1, "RunName": "Copy of Elevation - Full"}}]
    ds.set_short_view_names(reqs)
    assert reqs[0]["short_name"] == "Elevation - Full"


def test_short_view_names_never_split_a_word():
    reqs = [{"row": {"Key": 1, "RunName": "Plan North"}}, {"row": {"Key": 2, "RunName": "Plan Nest"}}]
    ds.set_short_view_names(reqs)
    assert reqs[0]["short_name"] == "Plan North" and reqs[1]["short_name"] == "Plan Nest"


# --- deep-copy rename (issue #16) -------------------------------------------

@pytest.mark.parametrize("raw,prefix,expected,matched", [
    ("Copy of External objects", "", "External objects", "Copy of"),
    ("Copy (3) Not Visible", "", "Not Visible", "Copy (3)"),
    ('Copy (1) 0" distance', "", '0" distance', "Copy (1)"),
    ("Copy (2) of Mp - Beam", "", "Mp - Beam", "Copy (2) of"),
    ("Copy of Copy (3) Off", "", "Off", "Copy of Copy (3)"),
    ("Copy (3) Not Visible", "MARK", "MARK Not Visible", "Copy (3)"),
    ("Copy of External objects", "MARK -", "MARK - External objects", "Copy of"),
    ("Copy of External objects", "MARK - ", "MARK - External objects", "Copy of"),
    ("Copy of Off", "MH_", "MH_Off", "Copy of"),
    ("Copy of 6 - Railing", "Marks", "Marks 6 - Railing", "Copy of"),
    ("Copy of Marks 6 - Railing", "Marks", "Marks 6 - Railing", "Copy of"),
    ("Plain name", "MARK", "Plain name", ""),
])
def test_format_copy_rename(raw, prefix, expected, matched):
    assert ds.format_copy_rename(raw, prefix) == (expected, matched)


def test_plan_deep_copy_rename_groups_tables_and_detects_collisions():
    rows_by_table = {
        "DetObjQualifierSet": [
            {"Key": 22001, "RunName": "Copy (3) Not Visible"},
            {"Key": 22002, "RunName": "Copy of External objects"},
            {"Key": 22003, "RunName": "Not Visible"},
        ],
        "DetObjAppearance": [
            {"Key": 22010, "RunName": "Copy (3) Off"},
            {"Key": 22011, "RunName": "Copy of VisibleHidden"},
        ],
    }
    pk_by_table = {
        "DetObjQualifierSet": ["Key"],
        "DetObjAppearance": ["Key"],
    }

    plan = ds.plan_deep_copy_rename(rows_by_table, pk_by_table, replacement_prefix="")
    assert plan["total_rows"] == 4
    assert plan["prefixes_seen"] == ["Copy (3)", "Copy of"]
    assert [t["table"] for t in plan["tables"]] == ["DetObjQualifierSet", "DetObjAppearance"]
    qset_rows = plan["tables"][0]["rows"]
    assert qset_rows[0]["new_name"] == "Not Visible"
    assert qset_rows[0]["collision"] is True
    assert qset_rows[1]["collision"] is False
    assert any("DetObjQualifierSet: 'Not Visible'" in w for w in plan["warnings"])

    # Replacing with a custom prefix avoids colliding with the stock "Not Visible" row.
    prefixed = ds.plan_deep_copy_rename(rows_by_table, pk_by_table, replacement_prefix="MARK -")
    assert prefixed["warnings"] == []
    assert prefixed["tables"][0]["rows"][0]["new_name"] == "MARK - Not Visible"

    # Table filter restricts the active plan while keeping available_tables intact.
    filtered = ds.plan_deep_copy_rename(
        rows_by_table, pk_by_table, replacement_prefix="MARK", include_tables=["DetObjAppearance"]
    )
    assert filtered["total_rows"] == 2
    assert filtered["total_available_rows"] == 4
    assert [t["table"] for t in filtered["tables"]] == ["DetObjAppearance"]


def test_apply_deep_copy_rename_commits_in_one_transaction_and_rolls_back_on_mismatch(monkeypatch):
    executed = []
    state = {"committed": False, "rolled_back": False, "closed": False, "rowcount": 1}

    class FakeCursor:
        @property
        def rowcount(self):
            return state["rowcount"]

        def execute(self, sql, params=()):
            executed.append((sql, list(params)))

    class FakeConn:
        def autocommit(self, val):
            state["autocommit"] = val

        def commit(self):
            state["committed"] = True

        def rollback(self):
            state["rolled_back"] = True

        def close(self):
            state["closed"] = True

    fake_plan = {
        "total_rows": 2,
        "tables": [{
            "table": "DetObjAppearance",
            "label": "Appearances",
            "pk_cols": ["Key"],
            "count": 2,
            "rows": [
                {"pk": {"Key": 22001}, "key_display": "22001", "old_name": "Copy (3) Off", "new_name": "MARK Off"},
                {"pk": {"Key": 22002}, "key_display": "22002", "old_name": "Copy of Visible", "new_name": "MARK Visible"},
            ],
        }],
    }
    monkeypatch.setattr(ds, "preview_deep_copy_rename", lambda *a, **k: fake_plan)
    monkeypatch.setattr("utils.db.connect", lambda database: (FakeConn(), FakeCursor()))

    counts = ds.apply_deep_copy_rename("Marks_Railing", replacement_prefix="MARK")
    assert counts == {"DetObjAppearance": 2}
    assert state["autocommit"] is False
    assert state["committed"] is True and not state["rolled_back"] and state["closed"] is True
    assert executed == [
        ("UPDATE [DetObjAppearance] SET [RunName] = %s WHERE [Key] = %s", ["MARK Off", 22001]),
        ("UPDATE [DetObjAppearance] SET [RunName] = %s WHERE [Key] = %s", ["MARK Visible", 22002]),
    ]

    # If a row update affects != 1 row, the whole transaction rolls back.
    executed.clear()
    state.update({"committed": False, "rolled_back": False, "closed": False, "rowcount": 0})
    with pytest.raises(RuntimeError, match="Expected 1 row updated"):
        ds.apply_deep_copy_rename("Marks_Railing", replacement_prefix="MARK")
    assert state["rolled_back"] is True and not state["committed"] and state["closed"] is True


def test_drawing_style_rename_copies_route_preview_and_apply(monkeypatch):
    from app import app

    fake_plan = {
        "replacement_prefix": "MARK",
        "available_tables": [{"table": "DetObjAppearance", "label": "Appearances", "count": 1, "selected": True}],
        "tables": [{
            "table": "DetObjAppearance",
            "label": "Appearances",
            "pk_cols": ["Key"],
            "count": 1,
            "rows": [{
                "pk": {"Key": 22001},
                "key_display": "22001",
                "old_name": "Copy (3) Off",
                "new_name": "MARK Off",
                "prefix": "Copy (3)",
                "collision": False,
                "token": "22001",
            }],
        }],
        "total_rows": 1,
        "total_available_rows": 1,
        "prefixes_seen": ["Copy (3)"],
        "warnings": [],
    }
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "drawing style")
    monkeypatch.setattr("utils.metadata.get", lambda database: {})
    monkeypatch.setattr("utils.drawing_styles.preview_deep_copy_rename", lambda *a, **k: fake_plan)

    client = app.test_client()
    get_resp = client.get("/db/Marks_Railing/drawing-style/rename-copies?replacement_prefix=MARK")
    assert get_resp.status_code == 200
    body = get_resp.get_data(as_text=True)
    assert "Copy (3) Off" in body and "MARK Off" in body

    with client.session_transaction() as sess:
        csrf = sess["_csrf"]

    # Fail-closed when snapshot fails: apply_deep_copy_rename must not run.
    applied = []
    monkeypatch.setattr(
        "utils.drawing_styles.apply_deep_copy_rename",
        lambda *a, **k: applied.append((a, k)) or {"DetObjAppearance": 1},
    )

    def fail_snap(database, reason):
        raise RuntimeError("disk full")

    monkeypatch.setattr("utils.snapshots.create_snapshot", fail_snap)
    fail_resp = client.post(
        "/db/Marks_Railing/drawing-style/rename-copies",
        data={"csrf_token": csrf, "action": "apply", "replacement_prefix": "MARK"},
    )
    assert fail_resp.status_code == 200
    assert "Pre-change snapshot failed" in fail_resp.get_data(as_text=True)
    assert applied == []

    # When snapshot succeeds, apply runs and redirects to the style editor.
    monkeypatch.setattr(
        "utils.snapshots.create_snapshot",
        lambda database, reason: {"filename": "Marks_Railing_snap.bak"},
    )
    ok_resp = client.post(
        "/db/Marks_Railing/drawing-style/rename-copies",
        data={"csrf_token": csrf, "action": "apply", "replacement_prefix": "MARK"},
    )
    assert ok_resp.status_code == 302
    assert ok_resp.headers["Location"].endswith("/db/Marks_Railing/drawing-style")
    assert len(applied) == 1
