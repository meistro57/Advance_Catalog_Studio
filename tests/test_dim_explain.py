"""Plain-language dimension requests: name codes, point rules, switches, and
the warnings the editor shows. Pure functions, no SQL Server needed."""

from utils import dim_explain as dx


def linear(**overrides):
    row = {
        "Key": 22010, "RunName": "Mp X - Extreme GTA", "Direction": 0,
        "ArrangeAbove": True, "ArrangeGlobally": True,
        "OneChainPerObjectInPoints1": False, "GroupRelatedDimensions": False,
        "AllowCombine": True, "AutomaticallySeparate": False, "Group": 3,
        "LabelContents": "", "Number of Points": 2,
        "Point1": 22100, "Point2": 22101,
    }
    for i in range(3, 16):
        row[f"Point{i}"] = 0
    row.update(overrides)
    return row


HOLES = {"Key": 22100, "RunName": "Holes - All", "Objects": 22050}
MP_REF = {"Key": 22101, "RunName": "Main Part - Extreme as reference", "Objects": 0}
QSETS = {22050: "Holes"}


# --- name code ---------------------------------------------------------------

def test_decodes_the_dsm_name_code():
    decoded = dx.decode_name_code("Mp X - Extreme GTA")
    assert decoded["code"] == "GTA"
    assert [l["column"] for l in decoded["letters"]] == [
        "ArrangeGlobally", "ArrangeAbove", "OneChainPerObjectInPoints1"]
    assert [l["value"] for l in decoded["letters"]] == [True, True, False]


def test_name_without_a_code_is_none():
    assert dx.decode_name_code("Beam X - Holes") is None
    assert dx.decode_name_code("") is None
    assert dx.decode_name_code(None) is None


def test_code_must_be_a_separate_word():
    # "TOTAL" ends in letters but is not a code
    assert dx.decode_name_code("Plate - TOTAL") is None
    assert dx.decode_name_code("Plate - Extreme LBS")["code"] == "LBS"


def test_name_code_agrees_with_stored_switches():
    check = dx.name_code_check("Mp X - Extreme GTA", linear())
    assert check["code"] == "GTA"
    assert len(check["agree"]) == 3 and check["disagree"] == []


def test_name_code_disagreement_is_reported():
    check = dx.name_code_check("Mp X - Extreme GTA", linear(ArrangeAbove=False))
    assert [d["letter"] for d in check["disagree"]] == ["T"]


def test_name_code_skips_columns_the_row_does_not_have():
    row = {"RunName": "x GTA", "ArrangeAbove": True}
    check = dx.name_code_check("x GTA", row)
    assert [a["letter"] for a in check["agree"]] == ["T"]


# --- point rules -------------------------------------------------------------

def test_holes_all_reads_as_hole_centers():
    p = dx.explain_point(HOLES, QSETS)
    assert p["sentence"] == "the hole centers"
    assert not p["reference"]
    assert p["objects"] == "Holes"


def test_main_part_extreme_as_reference():
    p = dx.explain_point(MP_REF, QSETS)
    assert p["sentence"] == "the overall size of the main part"
    assert p["reference"] is True
    assert p["objects"] is None  # Objects = 0 means no set


def test_system_and_contour_and_features():
    assert dx.explain_point({"RunName": "Beam - System as reference"})["sentence"] == "the system line of beams"
    assert dx.explain_point({"RunName": "Object contour as reference"})["sentence"] == "the outline"
    assert dx.explain_point({"RunName": "Mp - Features"})["sentence"] == "the cut features of the main part"


def test_bent_beam_side_comes_from_the_name():
    assert dx.explain_point({"RunName": "Bended beams inside"})["sentence"] == "the inside face of bent beams"
    assert dx.explain_point({"RunName": "Bended beams outside"})["sentence"] == "the outside face of bent beams"


def test_object_set_name_beats_the_name_subject():
    p = dx.explain_point({"Key": 1, "RunName": "Beam - Extreme", "Objects": 7}, {7: "Columns"})
    assert p["sentence"] == "the overall size of Columns"


def test_unknown_object_set_key_is_shown_as_a_number():
    p = dx.explain_point({"Key": 1, "RunName": "Beam - Extreme", "Objects": 99})
    assert p["objects"] == "object set #99"


def test_unrecognised_rule_name_falls_back_to_the_name():
    p = dx.explain_point({"Key": 1, "RunName": "Weird thing"})
    assert "Weird thing" in p["sentence"]


def test_unexplained_point_columns_are_kept_raw():
    p = dx.explain_point({"Key": 1, "RunName": "Holes - All", "Objects": 0, "PointType": 12, "Empty": None})
    assert p["extras"] == [{"column": "PointType", "value": 12}]


# --- direction and placement --------------------------------------------------

def test_direction_words_keep_the_number():
    assert dx.direction_text({"Direction": 0})["text"] == "runs along X"
    assert dx.direction_text({"Direction": 1})["axis"] == "y"
    other = dx.direction_text({"Direction": 7})
    assert other["basis"] == "raw" and other["value"] == 7 and "#7" in other["text"]
    assert dx.direction_text({})["text"] == "direction not set"


def test_above_means_left_in_a_vertical_chain():
    horiz = {p["column"]: p for p in dx.placement_lines(linear())}
    assert horiz["ArrangeAbove"]["text"] == "Placed above the view."
    vert = {p["column"]: p for p in dx.placement_lines(linear(Direction=1, ArrangeAbove=False))}
    assert vert["ArrangeAbove"]["text"] == "Placed on the right."


def test_switches_explain_both_states():
    on = {p["column"]: p for p in dx.placement_lines(linear(OneChainPerObjectInPoints1=True, AllowCombine=False))}
    assert "One chain per object" in on["OneChainPerObjectInPoints1"]["text"]
    assert "Never merged" in on["AllowCombine"]["text"]
    off = {p["column"]: p for p in dx.placement_lines(linear(ArrangeGlobally=False))}
    assert "Only kept clear" in off["ArrangeGlobally"]["text"]


def test_unverified_switch_is_marked_raw():
    lines = {p["column"]: p for p in dx.placement_lines(linear())}
    assert lines["AutomaticallySeparate"]["basis"] == "raw"
    assert lines["ArrangeAbove"]["basis"] == "guide"


def test_string_booleans_are_read():
    lines = {p["column"]: p for p in dx.placement_lines({"ArrangeAbove": "False", "Direction": 0})}
    assert lines["ArrangeAbove"]["on"] is False


# --- whole request ------------------------------------------------------------

def test_request_summary_reads_like_a_sentence():
    e = dx.explain_request(linear(), [HOLES, MP_REF], QSETS)
    assert e["summary"].startswith("Measures the hole centers. The chain runs along X, placed above the view.")
    assert "Reference points (the overall size of the main part)" in e["summary"]
    assert [p["name"] for p in e["measured"]] == ["Holes - All"]
    assert [p["name"] for p in e["reference"]] == ["Main Part - Extreme as reference"]
    assert e["warnings"] == []


def test_all_reference_chain_is_flagged():
    e = dx.explain_request(linear(), [MP_REF], QSETS)
    assert any("never drawn on its own" in w for w in e["warnings"])


def test_no_points_is_flagged():
    e = dx.explain_request(linear(**{"Number of Points": 0, "Point1": 0, "Point2": 0}), [])
    assert any("nothing to measure" in w for w in e["warnings"])


def test_point_count_mismatch_is_flagged():
    e = dx.explain_request(linear(**{"Number of Points": 1}), [HOLES], QSETS)
    assert any("Number of Points says 1 but 2" in w for w in e["warnings"])


def test_name_code_mismatch_becomes_a_warning():
    e = dx.explain_request(linear(ArrangeGlobally=False), [HOLES], QSETS)
    assert any("GTA disagrees" in w and "G (ArrangeGlobally)" in w for w in e["warnings"])


def test_missing_point_rows_are_skipped():
    e = dx.explain_request(linear(), [HOLES, None], QSETS)
    assert len(e["points"]) == 1


def test_unknown_request_columns_are_listed():
    e = dx.explain_request(linear(Mystery=4), [HOLES], QSETS)
    assert {"column": "Mystery", "value": 4} in e["extras"]
    assert all(x["column"] != "Point3" for x in e["extras"])


def test_long_point_lists_are_shortened_in_the_summary():
    rows = [{"Key": i, "RunName": f"Holes - set {i}"} for i in range(5)]
    e = dx.explain_request(linear(), rows)
    assert "+2 more" in e["summary"]


def test_explain_strategy_follows_strategy_order_and_flags_missing_requests():
    dims = [
        {"row": {"Order": 0, "RequestLinear": 22010}, "linear": {"row": linear()}, "point_keys": [22100, 22101]},
        {"row": {"Order": 1, "RequestLinear": 999}, "linear": None, "point_keys": []},
    ]
    out = dx.explain_strategy(dims, {22100: HOLES, 22101: MP_REF}, QSETS)
    assert out[0]["order"] == 0 and out[0]["measured"][0]["sentence"] == "the hole centers"
    assert out[1]["missing"] is True and "not in the file" in out[1]["warnings"][0]
