"""Unit tests for the fabrication detail sheet (issue #2): dimension
formatting/conversion, filename logic, validation, hardware schedule, and the
dimensioned SVG elevation. No database required."""

import pytest

from utils import fabrication as fab


# --- fixtures ---------------------------------------------------------------

def part(slot, role, din, side, bottom, top, diameter=12.7, width=25.4,
         height=12.3031, material="10.9", matched=True, position=2):
    return {
        "slot": slot, "din": din, "material": material, "diameter": diameter,
        "position": position, "role": role, "height": height, "width": width,
        "matched": matched, "name": f"{din} item", "side": side,
        "stack_bottom": bottom, "stack_top": top,
    }


def view_fixture(length=152.4, thread=76.2, top=25.4, dia=12.7, kind="hook",
                 hook_radius=25.0, components=None):
    if components is None:
        washer = part(2, "washer", "ASTM F436", "top", 135.3344, 140.0969,
                      diameter=dia, width=30.1625, height=4.7625, position=1)
        nut = part(1, "nut", "ASTM A563", "top", 140.0969, 152.4,
                   diameter=dia, width=25.4, height=12.3031, position=2)
        components = [nut, washer]
    termination = {"kind": "plain"}
    if kind == "hook":
        termination = {"kind": "hook", "hook_radius": hook_radius}
    if kind == "head":
        termination = {"kind": "head", "height": 7.9375, "width": 25.4, "corners": 6}
    return {
        "ok": True,
        "selection": {"anchor_id": 1, "def_id": 2, "standard": "US Hooked Anchors",
                      "material": "10.9", "diameter": dia, "set_name": "MuS",
                      "part_name": "Hooked Anchor 1/2x6x1-1/2", "length": length},
        "anchor": {"standard": "US Hooked Anchors", "material": "10.9",
                   "diameter": dia, "set_name": "MuS", "name": "Hooked Anchor 1/2x6x1-1/2",
                   "weight": 0.2},
        "geometry": {"length_mm": length, "thread_length_mm": thread,
                     "top_distance_mm": top, "termination": termination,
                     "distances": [{"field": "DistanceA", "label": "Distance A",
                                    "value_mm": 38.1}]},
        "thread": {"top": length, "bottom": length - thread},
        "concrete_y": length - top,
        "components": components,
        "notes": ["note"],
        "warnings": [],
    }


# --- conversions ------------------------------------------------------------

@pytest.mark.parametrize("mm,whole,num,den,text", [
    (12.7, 0, 1, 2, "1/2"),
    (9.525, 0, 3, 8, "3/8"),
    (6.35, 0, 1, 4, "1/4"),
    (25.4, 1, 0, 1, "1"),
    (31.75, 1, 1, 4, "1 1/4"),
    (28.575, 1, 1, 8, "1 1/8"),
    (4.7625, 0, 3, 16, "3/16"),
    (0.0, 0, 0, 1, "0"),
])
def test_inch_fraction_reduction(mm, whole, num, den, text):
    fr = fab.inch_fraction(mm)
    assert (fr["whole"], fr["num"], fr["den"]) == (whole, num, den)
    assert fab.fraction_text(fr) == text
    assert fr["exact"] is True


def test_inch_fraction_marks_inexact_values():
    fr = fab.inch_fraction(100.0)  # 3.937 in is not exactly k/16
    assert fr["exact"] is False
    assert fab.format_in(100.0).startswith("\u2248")


def test_format_dim_modes():
    d = fab.format_dim(76.2, "imperial")
    assert d["metric"] == "76.2"
    assert d["imperial"] == "3"
    assert "in (76.2 mm)" in d["dual"]
    assert fab.format_dim_text(12.7, "metric") == "12.7"
    assert fab.format_dim_text(12.7, "imperial") == "1/2"
    assert "in (" in fab.format_dim_text(12.7, "dual")
    assert fab.format_dim_text(None, "imperial") == "\u2014"


def test_trim_number_preserves_precision():
    assert fab.trim_number(12.7000) == "12.7"
    assert fab.trim_number(9.5250) == "9.525"
    assert fab.trim_number(0.0) == "0"


# --- filenames --------------------------------------------------------------

def test_sheet_filename_matches_issue_example():
    name = fab.sheet_filename(job="Job-2065", anchor_mark="A1",
                              standard="US Hooked Anchors", length_mm=609.6,
                              diameter_mm=19.05, revision="0")
    assert name == "Job-2065_A1_Hooked-Anchor_3-4x24_Rev-0.pdf"


def test_sheet_filename_sanitizes_and_drafts():
    name = fab.sheet_filename(job="Job/2065 x", anchor_mark="A 1",
                              standard="US Hooked Anchors", length_mm=609.6,
                              diameter_mm=19.05)
    assert name.startswith("Job-2065-x_A-1_Hooked-Anchor_3-4x24_Rev-0.pdf")
    draft = fab.sheet_filename(job="J1", standard="US Hooked Anchors",
                               length_mm=152.4, diameter_mm=12.7, draft=True)
    assert draft.startswith("DRAFT_")
    assert "/" not in draft and " " not in draft


def test_size_and_family_slugs():
    assert fab.size_slug(609.6, 19.05) == "3-4x24"
    assert fab.family_slug("US Threaded Anchors") == "Threaded-Anchor"
    assert fab.family_slug("Whatever Brand") == "Whatever-Brand"


# --- validation -------------------------------------------------------------

def test_validate_sheet_clean_model_has_no_errors():
    issues = fab.validate_sheet(view_fixture())
    assert issues == []


def test_validate_sheet_missing_length_is_error():
    v = view_fixture()
    v["geometry"]["length_mm"] = None
    codes = [i["code"] for i in fab.validate_sheet(v)]
    assert "missing_length_mm" in codes


def test_validate_sheet_thread_exceeding_length_is_error():
    v = view_fixture(length=100.0, thread=200.0)
    codes = [i["code"] for i in fab.validate_sheet(v)]
    assert "thread_exceeds_length" in codes


def test_validate_sheet_unmatched_component_is_error():
    v = view_fixture(components=[part(1, "nut", "ASTM A563", "top", 140, 152.4,
                                      matched=False)])
    codes = [i["code"] for i in fab.validate_sheet(v)]
    assert "unmatched_component" in codes


def test_validate_sheet_bad_hook_is_error():
    v = view_fixture(kind="hook", hook_radius=0.0)
    codes = [i["code"] for i in fab.validate_sheet(v)]
    assert "missing_hook_radius" in codes


# --- hardware schedule ------------------------------------------------------

def test_hardware_schedule_counts_and_letters():
    comps = [
        part(1, "nut", "ASTM A563", "top", 140, 152.4),
        part(2, "washer", "ASTM F436", "top", 135, 140),
        part(3, "nut", "ASTM A563", "bottom", 0, 12),
        part(4, "washer", "ASTM F436", "bottom", 12, 17),
    ]
    rows = fab.hardware_schedule(view_fixture(components=comps))
    assert [r["qty"] for r in rows] == [2, 2]
    assert rows[0]["letter"] == "A" and rows[1]["letter"] == "B"


# --- svg elevation ----------------------------------------------------------

def test_elevation_svg_contains_dimensions_and_hook():
    svg = fab.generate_elevation_svg(view_fixture(), mode="imperial")
    assert svg.startswith("<svg")
    assert 'aria-label="Anchor fabrication detail"' in svg
    # dims are in inches (imperial default): 152.4mm -> 6 in, 76.2 -> 3 in
    assert "L = 6" in svg
    assert "thread = 3" in svg
    assert "top projection = 1" in svg
    # hook drawn as an arc path + radius label (25 mm rounds to ~1 in)
    assert "hook R = " in svg
    assert "\u2248" in svg
    # hardware letters reference the fabrication table
    assert ">A</text>" in svg and ">B</text>" in svg


def test_elevation_svg_metric_and_dual_labels():
    v = view_fixture(length=100.0)
    m = fab.generate_elevation_svg(v, mode="metric")
    assert "L = 100" in m
    assert "in (" not in m
    d = fab.generate_elevation_svg(v, mode="dual")
    assert "in (" in d and "L =" in d


def test_elevation_svg_head_termination():
    svg = fab.generate_elevation_svg(view_fixture(kind="head", hook_radius=0),
                                     mode="imperial")
    assert "hook R" not in svg
