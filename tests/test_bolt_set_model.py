"""Unit tests for the bolt-set view-model mapping (issue #1, Phase 1).

Fixtures are synthetic dict rows shaped like real pymssql as_dict output from
the checked-in sample catalogs (A325TC_mark / Grade5). No database required.
"""

from utils import bolt_sets as bs

import pytest


# --- fixture rows -----------------------------------------------------------

def sob_row(din1="ASTM A563", p1=-2, din2="ASTM F436", p2=-1, din3="ASTM F436", p3=1,
            length=3, diameter=12.7, set_name="Mu2S"):
    return {
        "Standard": "ASTM A325TC", "Set": set_name, "Material": "10.9",
        "Diameter": diameter, "Length": length,
        "DIN1": din1, "Diameter1 (mm)": diameter, "Material1": "10.9", "Position1": p1,
        "DIN2": din2, "Diameter2 (mm)": diameter, "Material2": "10.9", "Position2": p2,
        "DIN3": din3, "Diameter3 (mm)": diameter if din3 != "-" else 0.0,
        "Material3": "10.9", "Position3": p3,
        "DIN4": "-", "Diameter4 (mm)": 0.0, "Material4": "-", "Position4": 0,
        "DIN5": None, "Diameter5 (mm)": None, "Material5": None, "Position5": None,
        "DIN6": None, "Diameter6 (mm)": None, "Material6": None, "Position6": None,
    }


def nut_row(standard="ASTM A563", diameter=12.7, material="10.9", height=12.3031,
            width=25.4, corners=6, name="A563 Nut 1/2"):
    return {
        "Standard": standard, "Material": material, "Diameter": diameter,
        "Height": height, "NumberOfCorners": corners, "OutsideDiameter": width,
        "Name": name, "Weight": 0.0297, "ItemNumber": "-", "Type": 1,
    }


def washer_row(standard="ASTM F436", diameter=12.7, material="10.9", height=4.7625,
               width=30.1625, name="Washer F436 - 1/2"):
    return {
        "Standard": standard, "Material": material, "Diameter": diameter,
        "Height": height, "NumberOfCorners": 0, "OutsideDiameter": width,
        "Name": name, "Weight": 0.009, "ItemNumber": "-", "Type": 2,
    }


# --- slot parsing -----------------------------------------------------------

def test_parse_component_slots_skips_empty_and_dash_slots():
    slots = bs.parse_component_slots(sob_row())
    assert [s["slot"] for s in slots] == [1, 2, 3]
    assert slots[0]["din"] == "ASTM A563"
    assert slots[0]["diameter"] == 12.7
    assert slots[0]["position"] == -2


def test_parse_component_slots_ignores_none_diameter_slots():
    row = sob_row(din3="-", p3=0)
    slots = bs.parse_component_slots(row)
    assert [s["slot"] for s in slots] == [1, 2]


# --- matching ---------------------------------------------------------------

def test_match_setnut_exact_key():
    slot = bs.parse_component_slots(sob_row())[0]
    match = bs.match_setnut(slot, [nut_row(), washer_row()])
    assert match["record"]["Name"] == "A563 Nut 1/2"
    assert "material_mismatch" not in match


def test_match_setnut_unmatched_returns_none():
    slot = bs.parse_component_slots(sob_row())[0]
    assert bs.match_setnut(slot, [washer_row()]) is None


def test_match_setnut_loose_material_mismatch_flagged():
    slot = bs.parse_component_slots(sob_row())[0]
    loose = nut_row(material="GR4")  # same standard+diameter, different material
    match = bs.match_setnut(slot, [loose])
    assert match is not None and match["material_mismatch"] is True


def test_match_setnut_ambiguous_loose_match_returns_none():
    slot = bs.parse_component_slots(sob_row())[0]
    a = nut_row(material="GR4")
    b = nut_row(material="Stvz.")
    assert bs.match_setnut(slot, [a, b]) is None


def test_component_role_classifies_nut_and_washer():
    assert bs.component_role(nut_row()) == "nut"
    assert bs.component_role(washer_row()) == "washer"
    assert bs.component_role(None) == "part"


# --- partitioning (Position interpretation) ---------------------------------

def test_partition_two_sided_row():
    """A325TC_mark Mu2S: nut(-2), under-nut washer(-1), under-head washer(+1)."""
    slots = bs.parse_component_slots(sob_row())
    comps = bs.annotate_components(slots, [nut_row(), washer_row()])
    part = bs.partition_components(comps)
    assert [c["slot"] for c in part["head_side"]] == [3]
    # nut-side ordered bottom-to-top: washer(-1) beneath nut(-2)
    assert [c["slot"] for c in part["nut_side"]] == [2, 1]
    assert any("Split into head-side" in n for n in part["notes"])


def test_partition_single_sided_row_orders_by_type():
    """Grade5 MuS anomaly: HEX nut (Position +1) + Flat washer (Position +2):
    all one sign, so components must be arranged by type (nut outermost)."""
    row = sob_row(din1="Flat", p1=2, din2="HEX", p2=1, din3="-", p3=0, length=2)
    slots = bs.parse_component_slots(row)
    comps = bs.annotate_components(slots, [nut_row(standard="HEX", material="GR4"),
                                           washer_row(standard="Flat")])
    part = bs.partition_components(comps)
    assert part["head_side"] == []
    assert [c["din"] for c in part["nut_side"]] == ["Flat", "HEX"]
    assert any("arranged by component type" in n for n in part["notes"])


def test_partition_unsignable_row_flags_note():
    slots = bs.parse_component_slots(sob_row(p1=None, p2=None, p3=None))
    comps = bs.annotate_components(slots, [nut_row(), washer_row()])
    part = bs.partition_components(comps)
    assert part["head_side"] == []
    assert [c["role"] for c in part["nut_side"]] == ["washer", "washer", "nut"]
    assert part["notes"]  # signals that Position could not confirm layout


# --- layout ----------------------------------------------------------------

def test_build_layout_two_sided_grip():
    bolt = {"length": 50.8, "head_height": 7.9375}
    slots = bs.parse_component_slots(sob_row())
    comps = bs.annotate_components(slots, [nut_row(), washer_row()])
    part = bs.partition_components(comps)
    layout = bs.build_layout(bolt, part)

    by_slot = {p["slot"]: p for p in layout["parts"]}
    # under-head washer sits on the head (0..4.7625)
    assert by_slot[3]["stack_bottom"] == 0
    assert round(by_slot[3]["stack_top"], 4) == 4.7625
    # under-nut washer then nut rise flush to the shank end
    assert round(by_slot[1]["stack_top"], 4) == 50.8
    assert by_slot[1]["stack_bottom"] == by_slot[2]["stack_top"]
    # grip spans between the head-side stack and the nut-side stack
    assert layout["grip"]["bottom"] == 4.7625
    assert layout["grip"]["top"] == by_slot[2]["stack_bottom"]
    assert layout["grip"]["thickness"] > 0
    assert layout["warnings"] == []


def test_build_layout_impossible_stack_warns():
    bolt = {"length": 10.0, "head_height": 7.9375}  # far too short
    slots = bs.parse_component_slots(sob_row())
    comps = bs.annotate_components(slots, [nut_row(), washer_row()])
    part = bs.partition_components(comps)
    layout = bs.build_layout(bolt, part)
    codes = [w["code"] for w in layout["warnings"]]
    assert "impossible_stack" in codes


def test_build_layout_schematic_height_flag():
    """A washer with no Height record gets a schematic thickness + flag."""
    noheight = washer_row()
    noheight["Height"] = None
    slots = bs.parse_component_slots(sob_row(din3="-", p3=0, length=2))
    comps = bs.annotate_components(slots, [nut_row(), noheight])
    part = bs.partition_components(comps)
    layout = bs.build_layout({"length": 50.8, "head_height": 7.9375}, part)
    flagged = [p for p in layout["parts"] if p["schematic_height"]]
    assert len(flagged) == 1 and flagged[0]["slot"] == 2


# --- side/layer tags + grip override ----------------------------------------

def test_build_layout_tags_side_and_layer():
    bolt = {"length": 50.8, "head_height": 7.9375}
    slots = bs.parse_component_slots(sob_row())
    comps = bs.annotate_components(slots, [nut_row(), washer_row()])
    part = bs.partition_components(comps)
    layout = bs.build_layout(bolt, part)
    tags = {(p["slot"], p["side"], p["layer"]) for p in layout["parts"]}
    assert tags == {(3, "head", 0), (2, "nut", 0), (1, "nut", 1)}


def test_build_layout_stacks_multiple_head_side_parts():
    """Two under-head washers stack sequentially on the head."""
    row = sob_row()
    row["DIN4"] = "ASTM F436"
    row["Diameter4 (mm)"] = 12.7
    row["Material4"] = "10.9"
    row["Position4"] = 2
    row["Length"] = 4
    slots = bs.parse_component_slots(row)
    comps = bs.annotate_components(slots, [nut_row(), washer_row(), washer_row()])
    part = bs.partition_components(comps)
    layout = bs.build_layout({"length": 50.8, "head_height": 7.9375}, part)
    head_parts = sorted([p for p in layout["parts"] if p["side"] == "head"],
                        key=lambda p: p["layer"])
    assert len(head_parts) == 2
    assert head_parts[0]["layer"] == 0 and head_parts[0]["stack_bottom"] == 0
    # second washer sits directly on top of the first (no 0.0 stacking bug)
    assert head_parts[1]["layer"] == 1
    assert head_parts[1]["stack_bottom"] == head_parts[0]["stack_top"]


def test_build_layout_grip_override_fixed_and_clamped():
    """Single nut-side stack (washer 4.7625 + nut 12.3031 = 17.0656 mm) on a
    50.8 mm bolt leaves 33.7344 mm available."""
    row = sob_row(din3="-", p3=0, length=2)
    slots = bs.parse_component_slots(row)
    comps = bs.annotate_components(slots, [nut_row(), washer_row()])
    part = bs.partition_components(comps)
    bolt = {"length": 50.8, "head_height": 7.9375}

    fixed = bs.build_layout(bolt, part, grip_override=20.0)
    assert fixed["grip"]["thickness"] == 20.0
    assert fixed["grip"]["bottom"] == 0.0
    assert fixed["parts"][0]["stack_bottom"] == 20.0
    assert fixed["parts"][-1]["stack_top"] == pytest.approx(37.0656, abs=1e-4)

    clamped = bs.build_layout(bolt, part, grip_override=200.0)
    codes = [w["code"] for w in clamped["warnings"]]
    assert "grip_limited" in codes
    assert clamped["grip"]["thickness"] == pytest.approx(33.7344, abs=1e-4)


def test_normalize_catalog_parts_dedupes_and_sorts():
    rows = [
        nut_row(),
        washer_row(),
        nut_row(),  # duplicate key -> dropped
    ]
    parts = bs.normalize_catalog_parts(rows)
    keys = [(p["standard"], p["material"], p["diameter"]) for p in parts]
    assert len(set(keys)) == len(keys)  # deduplicated by (standard, material, diameter)
    assert all("role" in p and "width" in p and "corners" in p for p in parts)
    assert [p["standard"] for p in parts] == sorted(p["standard"] for p in parts)


# --- screw rules ------------------------------------------------------------

def test_normalize_screw_rules_drops_empty_bands():
    row = {
        "Standard": "ASTM A325TC", "Set": "MuS", "Material": "10.9",
        "GripLengthMin1": 2.38125, "GripLengthMax1": 5.55625,
        "ScrewLengthBase1": 25.4, "ScrewLengthDelta1": 6.35,
        "GripLengthMin2": 5.55625, "GripLengthMax2": 232.56874,
        "ScrewLengthBase2": 31.75, "ScrewLengthDelta2": 6.35,
        "GripLengthMin3": 0.0, "GripLengthMax3": 0.0,
        "ScrewLengthBase3": 0.0, "ScrewLengthDelta3": 0.0,
        "GripLengthMin4": None, "GripLengthMax4": None,
        "ScrewLengthBase4": None, "ScrewLengthDelta4": None,
        "GripLengthMin5": None, "GripLengthMax5": None,
        "ScrewLengthBase5": None, "ScrewLengthDelta5": None,
        "GripLengthMin6": None, "GripLengthMax6": None,
        "ScrewLengthBase6": None, "ScrewLengthDelta6": None,
        "GripLengthMin7": None, "GripLengthMax7": None,
        "ScrewLengthBase7": None, "ScrewLengthDelta7": None,
    }
    bands = bs.normalize_screw_rules([row])
    assert len(bands) == 2
    assert bands[0]["base_length"] == 25.4
    assert bands[1]["grip_max"] == pytest.approx(232.56874, abs=1e-4)
