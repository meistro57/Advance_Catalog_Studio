"""Unit tests for the shear-stud (connector) browser model (issue #4).

Fixtures mirror the OBSERVED Nelson H4L export documented in
`docs/shear-stud-schema.md`. No database required; the SQL helpers are tested
against patched `utils.db` functions.
"""

import pytest

from utils import shear_studs as ss


# --- fixture rows -----------------------------------------------------------

def standard_row(key="Nelson H4L"):
    return {"Key": key, "RunName": key, "OwnerText": "DSC"}


def material_row(key="Mild Steel", weight=0.0):
    return {"Key": key, "RunName": key, "weight": weight, "OwnerText": "DSC"}


def diameter_row(key, run_name=None):
    return {
        "Key": key,
        "RunName": ss.format_metric_run_name(key) if run_name is None else run_name,
        "Description": None,
    }


def distance_row(key, along=None, across=None, hole_tolerance=0.0):
    return {
        "Key": key,
        "HoleTolerance": hole_tolerance,
        "along": along if along is not None else key * 2,
        "across": across if across is not None else key * 1.5,
        "Description": None,
    }


def relation_row(key, standard="Nelson H4L", material="Mild Steel", diameter=6.0):
    return {
        "Key": key,
        "ConnectorStandard": standard,
        "ConnectorMaterial": material,
        "ConnectorDiameter": diameter,
    }


def stud_row(diameter=6.0, length=10.0, standard="Nelson H4L", material="Mild Steel",
             head_diameter=None, head_height=None, corners=0, weight=0.0059,
             name=None, stud_type=2):
    return {
        "Standard": standard,
        "Material": material,
        "Diameter": diameter,
        "Length": length,
        "ScrewHeadOuterDiameter": head_diameter if head_diameter is not None else diameter * 2,
        "HeadHeight": head_height if head_height is not None else diameter / 2,
        "NumberOfCorners": corners,
        "Name": ss.expected_stud_name(standard, diameter, length) if name is None else name,
        "Weight": weight,
        "OwnerText": "DSC",
        "Source": standard,
        "Type": stud_type,
    }


def nelson_shape():
    """The real Nelson H4L shape: one family/grade, 4 diameters, 31 studs."""
    diameters = [6.0, 10.0, 13.0, 16.0]
    lengths = {
        6.0: [10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0],
        10.0: [15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0],
        13.0: [25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0],
        16.0: [30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0],
    }
    return {
        "standards": [standard_row()],
        "materials": [material_row()],
        "diameters": [diameter_row(d) for d in diameters],
        "distances": [distance_row(d) for d in diameters],
        "relations": [relation_row(n + 1, diameter=d) for n, d in enumerate(diameters)],
        "studs": [
            stud_row(diameter=d, length=length)
            for d in diameters
            for length in lengths[d]
        ],
    }


def build(**overrides):
    shape = nelson_shape()
    shape.update(overrides)
    return ss.build_groups(
        standards=shape["standards"],
        materials=shape["materials"],
        diameters=shape["diameters"],
        distances=shape["distances"],
        relations=shape["relations"],
        stud_rows=shape["studs"],
    )


# --- units and names --------------------------------------------------------

def test_parse_metric_run_name_accepts_observed_forms():
    assert ss.parse_metric_run_name(" 10.00 mm") == 10.0
    assert ss.parse_metric_run_name("   6.00 mm") == 6.0
    assert ss.parse_metric_run_name("16 mm") == 16.0
    assert ss.parse_metric_run_name("6.0") == 6.0
    assert ss.parse_metric_run_name(" 3/8 inch") is None
    assert ss.parse_metric_run_name(None) is None


def test_format_metric_run_name_matches_canonical_form():
    assert ss.format_metric_run_name(10) == " 10.00 mm"
    assert ss.format_metric_run_name(6) == " 6.00 mm"


def test_number_text_trims_trailing_zeros():
    assert ss.number_text(6.0) == "6"
    assert ss.number_text(12.5) == "12.5"
    assert ss.number_text(9.525) == "9.525"


def test_expected_stud_name_follows_observed_convention():
    assert ss.expected_stud_name("Nelson H4L", 16.0, 40.0) == "Nelson H4L 16 x 40"
    assert ss.expected_stud_name("Nelson H4L", 12.5, 7.0) == "Nelson H4L 12.5 x 7"


def test_same_number_tolerates_float_noise():
    assert ss.same_number(12.7000000001, 12.7)
    assert not ss.same_number(12.7, 12.8)


# --- run-name observations --------------------------------------------------

def test_run_name_issue_ignores_canonical_name():
    assert ss.run_name_issue(diameter_row(10.0)) is None


def test_run_name_issue_flags_extra_whitespace_as_info():
    note = ss.run_name_issue(diameter_row(6.0, run_name="   6.00 mm"))
    assert note["severity"] == "info"
    assert note["code"] == "run_name_format"
    assert note["context"]["diameter"] == 6.0


def test_run_name_issue_flags_disagreement_as_error():
    note = ss.run_name_issue(diameter_row(10.0, run_name=" 12.00 mm"))
    assert note["severity"] == "error"
    assert note["code"] == "run_name_mismatch"


def test_run_name_issue_flags_unparseable_name():
    note = ss.run_name_issue(diameter_row(10.0, run_name="M10"))
    assert note["severity"] == "warn"
    assert note["code"] == "run_name_unparsed"


# --- stud validation --------------------------------------------------------

def test_normalize_stud_maps_source_columns():
    stud = ss.normalize_stud(stud_row(diameter=16.0, length=40.0))
    assert stud["diameter"] == 16.0
    assert stud["length"] == 40.0
    assert stud["head_diameter"] == 32.0
    assert stud["head_height"] == 8.0
    assert stud["corners"] == 0
    assert stud["type"] == 2
    assert stud["name"] == "Nelson H4L 16 x 40"
    assert stud["issues"] == []


def test_stud_with_head_no_larger_than_shank_is_an_error():
    stud = ss.normalize_stud(stud_row(diameter=16.0, head_diameter=16.0))
    codes = {(i["severity"], i["code"]) for i in stud["issues"]}
    assert ("error", "head_not_larger") in codes
    assert stud["has_errors"]


def test_stud_with_bad_length_is_an_error():
    stud = ss.normalize_stud(stud_row(length=0.0))
    assert any(i["code"] == "invalid_length" for i in stud["issues"])


def test_stud_name_off_convention_warns_but_is_not_an_error():
    stud = ss.normalize_stud(stud_row(name="Nelson H4L M6x10"))
    assert [i["code"] for i in stud["issues"]] == ["name_mismatch"]
    assert not stud["has_errors"]


def test_head_label_describes_round_and_polygonal_heads():
    assert ss.head_label(ss.normalize_stud(stud_row(corners=0))) == "round head Ø12 mm"
    assert ss.head_label(ss.normalize_stud(stud_row(corners=6))) == "6-sided head Ø12 mm"


# --- grouping / completeness ------------------------------------------------

def test_nelson_shape_builds_four_complete_groups():
    built = build()
    groups = built["groups"]
    assert len(groups) == 4
    assert [g["diameter"] for g in groups] == [6.0, 10.0, 13.0, 16.0]
    assert all(g["complete"] for g in groups)
    assert [g["stud_count"] for g in groups] == [7, 8, 8, 8]
    assert built["issues"] == []


def test_group_exposes_hole_rules_and_relation_keys():
    group = build()["groups"][0]
    assert group["relation_keys"] == [1]
    assert group["distances"][0]["along"] == 12.0
    assert group["distances"][0]["across"] == 9.0


def test_missing_relation_breaks_completeness():
    shape = nelson_shape()
    built = build(relations=shape["relations"][1:])
    group = built["groups"][0]
    assert not group["complete"]
    assert any(i["code"] == "missing_relation" for i in group["issues"])


def test_missing_distance_row_breaks_completeness():
    shape = nelson_shape()
    built = build(distances=shape["distances"][1:])
    assert any(i["code"] == "missing_distances" for i in built["groups"][0]["issues"])


def test_missing_diameter_row_breaks_completeness():
    shape = nelson_shape()
    built = build(diameters=shape["diameters"][1:])
    group = built["groups"][0]
    assert any(i["code"] == "missing_diameter" for i in group["issues"])
    # The removed diameter is still referenced by a relation and by studs, so it
    # is not an orphan; only the group-level "missing diameter row" error fires.
    assert not any(i["code"] == "orphan_diameter" for i in built["issues"])


def test_relation_without_studs_is_an_error():
    shape = nelson_shape()
    studs = [s for s in shape["studs"] if s["Diameter"] != 16.0]
    built = build(studs=studs)
    group = built["groups"][-1]
    assert group["diameter"] == 16.0
    assert group["stud_count"] == 0
    assert not group["complete"]
    assert any(i["code"] == "no_lengths" for i in group["issues"])


def test_missing_standard_lookup_is_an_error():
    built = build(standards=[])
    assert any(i["code"] == "missing_standard" for i in built["groups"][0]["issues"])


def test_duplicate_relation_rows_are_flagged():
    shape = nelson_shape()
    relations = shape["relations"] + [relation_row(99, diameter=6.0)]
    built = build(relations=relations)
    assert any(i["code"] == "duplicate_relation" for i in built["groups"][0]["issues"])


def test_duplicate_stud_rows_are_flagged_catalog_wide():
    shape = nelson_shape()
    built = build(studs=shape["studs"] + [stud_row(diameter=6.0, length=10.0)])
    codes = [i["code"] for i in built["issues"]]
    assert codes.count("duplicate_stud") == 1


def test_orphan_lookups_are_warned_about():
    shape = nelson_shape()
    built = build(
        standards=shape["standards"] + [standard_row("Nelson P")],
        materials=shape["materials"] + [material_row("Stainless")],
        diameters=shape["diameters"] + [diameter_row(20.0)],
    )
    codes = {i["code"] for i in built["issues"]}
    assert {"orphan_standard", "orphan_material", "orphan_diameter"} <= codes


def test_stud_issues_are_collected_with_their_group():
    shape = nelson_shape()
    studs = shape["studs"] + [stud_row(diameter=6.0, length=45.0, head_diameter=6.0)]
    built = build(studs=studs)
    issues = ss.collect_issues(built["groups"], built["issues"])
    assert issues[0]["severity"] == "error"
    assert any(i["code"] == "head_not_larger" and i["group"]["diameter"] == 6.0
               for i in issues)


# --- family tree / filtering / summary --------------------------------------

def test_family_tree_groups_grades_and_diameters():
    families = ss.family_tree(build()["groups"])
    assert len(families) == 1
    family = families[0]
    assert family["standard"] == "Nelson H4L"
    assert family["diameters"] == [6.0, 10.0, 13.0, 16.0]
    assert family["stud_count"] == 31
    assert [g["material"] for g in family["grades"]] == ["Mild Steel"]
    assert len(family["grades"][0]["diameters"]) == 4


def test_filter_groups_narrows_by_length_inside_groups():
    groups = ss.filter_groups(build()["groups"], diameter="10", length="25")
    assert len(groups) == 1
    assert groups[0]["lengths"] == [25.0]
    assert groups[0]["stud_count"] == 1


def test_filter_groups_ignores_blank_filters():
    assert len(ss.filter_groups(build()["groups"], standard="", material=None,
                                diameter="", length="")) == 4


def test_filter_groups_drops_unmatched_selection():
    assert ss.filter_groups(build()["groups"], standard="Other") == []


def test_filter_options_list_selectable_values():
    options = ss.filter_options(build()["groups"])
    assert options["standards"] == ["Nelson H4L"]
    assert options["diameters"] == [6.0, 10.0, 13.0, 16.0]
    assert options["lengths"][0] == 10.0
    assert 25.0 in options["lengths"]


def test_summarize_counts_records_and_issues():
    built = build()
    issues = ss.collect_issues(built["groups"], built["issues"])
    summary = ss.summarize(built["groups"], issues)
    assert summary["families"] == 1
    assert summary["materials"] == 1
    assert summary["diameters"] == 4
    assert summary["studs"] == 31
    assert summary["complete"] == 4
    assert summary["errors"] == 0


# --- SQL helpers ------------------------------------------------------------

def test_get_browser_model_rejects_non_connector_catalogs(monkeypatch):
    monkeypatch.setattr("utils.db.list_tables", lambda database: ["SetBolts", "Sources"])
    with pytest.raises(ValueError) as exc:
        ss.get_browser_model("Grade5")
    assert "ConnectorDiameters" in str(exc.value)


def test_get_browser_model_reads_connector_tables(monkeypatch):
    shape = nelson_shape()
    table_rows = {
        "ConnectorStandard": shape["standards"],
        "ConnectorMaterial": shape["materials"],
        "ConnectorDiameters": shape["diameters"],
        "ConnectorDistances": shape["distances"],
        "ConnectorRelations": shape["relations"],
        "SetBolts": shape["studs"],
    }
    monkeypatch.setattr("utils.db.list_tables", lambda database: list(table_rows))
    monkeypatch.setattr("utils.db.get_rows",
                        lambda database, table, limit=1000: table_rows[table])
    model = ss.get_browser_model("NelsonH4L")
    assert model["summary"]["studs"] == 31
    assert model["families"][0]["standard"] == "Nelson H4L"
    assert model["options"]["diameters"] == [6.0, 10.0, 13.0, 16.0]


# --- clone proposal (preview only) -----------------------------------------

def plan(**overrides):
    """Plan a clone from the Nelson shape with sensible defaults."""
    built = build(**{k: v for k, v in overrides.items() if k in
                     {"standards", "materials", "diameters", "distances",
                      "relations", "studs"}})
    groups = built["groups"]
    diameter_keys = sorted({g["diameter"] for g in groups})
    relation_keys = [r["Key"] for r in nelson_shape()["relations"]]
    params = {
        "standard": "Nelson H4L", "material": "Mild Steel",
        "source_diameter": 10.0, "target_diameter": 12.0, "lengths": "30, 35",
    }
    params.update({k: v for k, v in overrides.items() if k not in
                   {"standards", "materials", "diameters", "distances",
                    "relations", "studs"}})
    return ss.plan_clone(groups, relation_keys, diameter_keys, **params)


def plan_tables(result):
    return {t["table"]: t["rows"] for t in result["tables"]}


def test_parse_lengths_accepts_separators_and_reports_bad_tokens():
    values, rejected = ss.parse_lengths("30, 35 40;45  50")
    assert values == [30.0, 35.0, 40.0, 45.0, 50.0]
    assert rejected == []
    values, rejected = ss.parse_lengths("30 abc ,40")
    assert values == [30.0, 40.0]
    assert rejected == ["abc"]


def test_next_relation_key_uses_max_plus_one():
    assert ss.next_relation_key([1, 2, 3]) == 4
    assert ss.next_relation_key([]) == 1
    assert ss.next_relation_key([1, None, 7]) == 8


def test_plan_clone_proposes_rows_in_four_tables():
    result = plan()
    assert result["ok"], result["issues"]
    assert result["status"] == "preview"
    assert [t["table"] for t in result["tables"]] == [
        "ConnectorDiameters", "ConnectorDistances", "ConnectorRelations", "SetBolts"]
    assert result["summary"] == {
        "tables": 4, "rows": 5, "errors": 0, "warnings": 0, "notes": 1}


def test_plan_clone_scales_head_and_hole_rules():
    result = plan()
    tables = plan_tables(result)
    assert result["scale_factor"] == 1.2
    assert tables["ConnectorDiameters"][0]["Key"] == 12.0
    assert tables["ConnectorDiameters"][0]["RunName"] == " 12.00 mm"
    assert tables["ConnectorDistances"][0]["along"] == 24.0
    assert tables["ConnectorDistances"][0]["across"] == 18.0
    assert tables["ConnectorDistances"][0]["HoleTolerance"] == 0.0
    studs = tables["SetBolts"]
    assert [s["Length"] for s in studs] == [30.0, 35.0]
    assert studs[0]["ScrewHeadOuterDiameter"] == 24.0
    assert studs[0]["HeadHeight"] == 6.0
    assert studs[0]["Name"] == "Nelson H4L 12 x 30"
    assert studs[0]["Type"] == 2
    assert studs[0]["Source"] == "Nelson H4L"


def test_plan_clone_reuses_source_weight_for_same_length():
    studs = plan_tables(plan())["SetBolts"]
    assert studs[0]["Weight"] == pytest.approx(0.0059 * 1.44, rel=1e-3)


def test_plan_clone_leaves_weight_empty_without_a_source_length():
    result = plan(lengths="55")
    studs = plan_tables(result)["SetBolts"]
    assert studs[0]["Weight"] is None
    assert any(i["code"] == "weight_unknown" for i in result["issues"])


def test_plan_clone_can_copy_geometry_unchanged():
    result = plan(scale_geometry=False)
    tables = plan_tables(result)
    assert result["scale_geometry"] is False
    assert tables["SetBolts"][0]["ScrewHeadOuterDiameter"] == 20.0
    assert tables["SetBolts"][0]["HeadHeight"] == 5.0
    assert tables["ConnectorDistances"][0]["along"] == 20.0
    assert not any(i["code"] == "scaled_estimate" for i in result["issues"])


def test_plan_clone_accepts_explicit_hole_rules():
    result = plan(along=26.0, across=20.0, hole_tolerance=0.5)
    rule = plan_tables(result)["ConnectorDistances"][0]
    assert (rule["along"], rule["across"], rule["HoleTolerance"]) == (26.0, 20.0, 0.5)


def test_plan_clone_warns_when_spacing_is_tight():
    result = plan(along=10.0)
    assert any(i["code"] == "tight_spacing" for i in result["issues"])
    assert result["ok"]


def test_plan_clone_rejects_an_existing_diameter():
    result = plan(target_diameter=13.0, lengths="70")
    codes = {i["code"] for i in result["issues"]}
    assert {"diameter_exists", "group_exists"} <= codes
    assert not result["ok"]


def test_plan_clone_rejects_existing_lengths_of_the_target_group():
    result = plan(target_diameter=13.0, lengths="25")
    codes = {i["code"] for i in result["issues"]}
    assert {"group_exists", "diameter_exists", "length_exists"} <= codes
    assert not result["ok"]


def test_plan_clone_rejects_duplicate_and_invalid_lengths():
    result = plan(lengths="30 30 abc 0")
    codes = [i["code"] for i in result["issues"]]
    assert "duplicate_length" in codes
    assert codes.count("bad_length") == 2
    assert not result["ok"]


def test_plan_clone_rejects_a_missing_source():
    result = plan(source_diameter=99.0)
    assert any(i["code"] == "source_missing" for i in result["issues"])
    assert not result["ok"]
    assert result["tables"] == []


def test_plan_clone_rejects_an_incomplete_source():
    shape = nelson_shape()
    result = plan(source_diameter=6.0, distances=shape["distances"][1:])
    assert any(i["code"] == "source_incomplete" for i in result["issues"])
    assert not result["ok"]


def test_plan_clone_rejects_a_name_collision():
    shape = nelson_shape()
    studs = shape["studs"] + [stud_row(diameter=13.0, length=30.0,
                                       name="Nelson H4L 12 x 30")]
    result = plan(studs=studs)
    assert any(i["code"] == "name_exists" for i in result["issues"])
    assert not result["ok"]


def test_plan_clone_rejects_a_non_positive_target():
    result = plan(target_diameter=0)
    assert any(i["code"] == "bad_target" for i in result["issues"])
    assert not result["ok"]


def test_plan_clone_proposes_the_next_relation_key():
    result = plan()
    row = plan_tables(result)["ConnectorRelations"][0]
    assert row["Key"] == 5
    assert row["ConnectorDiameter"] == 12.0


# --- catalog type detection -------------------------------------------------

def test_guess_catalog_type_prefers_connector_tables_over_setbolts(monkeypatch):
    from utils import db
    monkeypatch.setattr(db, "list_tables",
                        lambda database: ["SetBolts", "ConnectorStandard",
                                          "ConnectorDiameters"])
    assert db.guess_catalog_type("NelsonH4L") == "shear stud"


def test_guess_catalog_type_detects_a_connector_diameters_table_alone(monkeypatch):
    from utils import db
    monkeypatch.setattr(db, "list_tables", lambda database: ["ConnectorDiameters", "SetBolts"])
    assert db.guess_catalog_type("PartialConnector") == "shear stud"


def test_guess_catalog_type_still_labels_plain_bolt_catalogs(monkeypatch):
    from utils import db
    monkeypatch.setattr(db, "list_tables",
                        lambda database: ["SetBolts", "BoltsDiameters", "SetOfBolts"])
    assert db.guess_catalog_type("A325TC_mark") == "bolt"


def test_guess_catalog_type_still_labels_anchor_catalogs(monkeypatch):
    from utils import db
    monkeypatch.setattr(db, "list_tables",
                        lambda database: ["SetBolts", "AnchorsDefinition"])
    assert db.guess_catalog_type("US_Hooked_Anchors") == "anchor"
