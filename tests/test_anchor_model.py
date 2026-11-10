"""Unit tests for the anchor view-model mapping (graphical anchor
configurator). Fixtures mimic pymssql as_dict rows from the sample anchor
catalogs (HiltiHY200, US_Headed/Hooked/Threaded_Anchors). No database needed.
"""

import pytest

from utils import anchor_sets as an
from utils import bolt_sets as bs


def comp(slot, role="nut", height=12.3031, din="ASTM A563", diameter=12.7,
         position=2, matched=True, width=25.4):
    return {
        "slot": slot, "din": din, "diameter": diameter, "material": "10.9",
        "position": position, "role": role, "height": height, "width": width,
        "matched": matched, "name": f"{din} part {slot}",
    }


def name_row(pos1=2, pos2=1, diameter=12.7, set_name="MuS"):
    return {
        "ID": 1, "Standard": "US Threaded Anchors", "MaterialKey": "10.9",
        "Diameter": diameter, "SetName": set_name, "NumItems": 2,
        "DIN1": "ASTM A563", "Diameter1": diameter, "Material1": "10.9", "Position1": pos1,
        "DIN2": "ASTM F436", "Diameter2": diameter, "Material2": "10.9", "Position2": pos2,
        "DIN3": None, "Diameter3": 0.0, "Material3": None, "Position3": 0,
        "DIN4": None, "Diameter4": 0.0, "Material4": None, "Position4": 0,
        "DIN5": None, "Diameter5": 0.0, "Material5": None, "Position5": 0,
        "DIN6": None, "Diameter6": 0.0, "Material6": None, "Position6": 0,
    }


def def_row(length=152.4, thread=76.2, top=25.4, **kw):
    row = {
        "ID": 1, "AnchorID": 1, "Length": length, "ThreadLength": thread,
        "TopDistance": top, "PartName": "Threaded Anchor 1/2x6",
        "Weight": 0.2,
    }
    row.update(kw)  # use DB column names, e.g. HeadDiameter / HookRadius / DistanceA
    return row


# --- slot parsing (anchor uses plain "DiameterN" columns) -------------------

def test_parse_anchor_slots_uses_plain_diameter_columns():
    slots = bs.parse_component_slots(name_row(), diameter_suffix="")
    assert [s["slot"] for s in slots] == [1, 2]
    assert slots[0]["diameter"] == 12.7
    assert slots[0]["position"] == 2


# --- termination classification ---------------------------------------------

def test_classify_termination_kinds():
    assert an.classify_termination(def_row()) == {"kind": "plain"}
    head = an.classify_termination(def_row(HeadDiameter=25.4, HeadHeight=7.9375,
                                          NumberOfHeadEdges=6))
    assert head["kind"] == "head" and head["corners"] == 6
    hook = an.classify_termination(def_row(HookRadius=25.0))
    assert hook["kind"] == "hook" and hook["hook_radius"] == 25.0


def test_collect_distances_ignores_empty_fields():
    dists = an.collect_distances(def_row(DistanceA=38.1))
    labels = [d["label"] for d in dists]
    assert "Bolt projection from concrete" in labels and "Distance A" in labels
    assert "Top distance" not in labels
    assert all(d["value_mm"] not in (None, 0) for d in dists)


# --- end splitting (sign convention) ----------------------------------------

def test_split_sides_groups_by_position_sign():
    parts = an.split_sides([comp(1, position=2), comp(2, position=-1), comp(3, position=None)])
    assert [c["slot"] for c in parts["top"]] == [1, 3]
    assert [c["slot"] for c in parts["bottom"]] == [2]
    assert parts["notes"]  # two-sided interpretation is flagged


# --- layout ----------------------------------------------------------------

def test_build_anchor_layout_top_stack_hangs_from_rod_tip():
    """Slot order is preserved: DIN1 (nut) outermost at the rod tip."""
    top = [comp(1, role="nut", height=12.3031), comp(2, role="washer", height=4.7625)]
    layout = an.build_anchor_layout(
        {"length": 152.4, "thread_length": 76.2, "top_distance": 25.4}, top, [])

    by_slot = {p["slot"]: p for p in layout["parts"]}
    assert by_slot[1]["stack_top"] == 152.4            # nut at the rod tip
    assert by_slot[2]["stack_top"] == by_slot[1]["stack_bottom"]  # washer under the nut
    assert by_slot[2]["stack_bottom"] == pytest.approx(135.3344, abs=1e-3)
    assert layout["concrete_y"] == 127.0
    assert layout["thread"] == {"top": 152.4, "bottom": 76.2}
    assert layout["warnings"] == []


def test_build_anchor_layout_bottom_stack_clears_head():
    """With a head at the rod bottom, embedded-end hardware starts above it."""
    layout = an.build_anchor_layout(
        {"length": 152.4, "thread_length": 76.2, "top_distance": 25.4}, [],
        [comp(3, role="washer", height=4.7625), comp(4, role="nut", height=12.3031)],
        bottom_start=7.9375)
    bottoms = sorted(p["stack_bottom"] for p in layout["parts"])
    assert bottoms[0] == 7.9375


def test_build_anchor_layout_thread_longer_than_rod_warns():
    layout = an.build_anchor_layout(
        {"length": 76.2, "thread_length": 200.0, "top_distance": 12.7},
        [comp(1, role="nut", height=12.3031)], [])
    codes = [w["code"] for w in layout["warnings"]]
    assert "thread_exceeds_length" in codes
    assert layout["thread"]["bottom"] == 0.0


def test_build_anchor_layout_warns_when_stack_intrudes_below_concrete():
    """Small TopDistance leaves no room for the hardware above the surface."""
    top = [comp(1, role="nut", height=12.3031), comp(2, role="washer", height=4.7625)]
    layout = an.build_anchor_layout(
        {"length": 152.4, "thread_length": 76.2, "top_distance": 6.0}, top, [])
    codes = [w["code"] for w in layout["warnings"]]
    assert "stack_below_concrete" in codes


def test_anchor_view_supports_top_distance_override(monkeypatch):
    """Issue #19: anchor_view accepts top_distance_override while preserving catalog_top_distance_mm."""
    monkeypatch.setattr(
        an.dbcore, "list_tables", lambda db: ["AnchorsName", "AnchorsDefinition", "SetNutsBolts"]
    )
    monkeypatch.setattr(an, "_fetch_anchor_name", lambda db, aid: name_row())
    monkeypatch.setattr(an, "_fetch_anchor_def", lambda db, did: def_row(length=304.8, top=50.8))
    monkeypatch.setattr(an, "_fetch_nut_rows", lambda db: [])

    default_view = an.anchor_view("US_Headed_Anchors", 1, 1)
    assert default_view["ok"] is True
    assert default_view["geometry"]["top_distance_mm"] == 50.8
    assert default_view["geometry"]["catalog_top_distance_mm"] == 50.8
    assert default_view["concrete_y"] == 254.0

    overridden = an.anchor_view("US_Headed_Anchors", 1, 1, top_distance_override=101.6)
    assert overridden["geometry"]["top_distance_mm"] == 101.6
    assert overridden["geometry"]["catalog_top_distance_mm"] == 50.8
    assert overridden["concrete_y"] == 203.2


def test_anchor_configurator_template_has_projection_and_unit_controls():
    """Issues #18, #19, #21: template includes projection controls, unit toggle, and all script element IDs."""
    import os
    import re
    from flask import render_template
    from app import app

    with app.test_request_context("/"):
        html = render_template(
            "anchor_configurator.html",
            database="US_Headed_Anchors",
            options=[{
                "anchor_id": 1, "standard": "ASTM F1554", "set_name": "MuS",
                "material": "Gr36", "diameter": 19.05, "def_count": 4,
            }],
        )
    assert "Bolt projection from concrete" in html
    assert 'id="projectionInput"' in html
    assert 'id="projTypical4Btn"' in html
    assert 'id="projResetBtn"' in html
    assert 'id="unitInBtn"' in html and 'id="unitMmBtn"' in html
    script = open(os.path.join(app.root_path, "static", "js", "anchor-configurator.js")).read()
    ids = set(re.findall(r"\$\('([A-Za-z0-9_]+)'\)", script))
    missing = sorted(i for i in ids if f'id="{i}"' not in html)
    assert missing == []
