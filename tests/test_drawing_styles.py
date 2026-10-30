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
