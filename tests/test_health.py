"""Unit tests for the read-only catalog health report.

Fixtures mirror the shapes returned by `db.get_catalog_diameters`, the anchor
tables and the per-type modules. No database required.
"""

from utils import health


# --- fixtures ---------------------------------------------------------------

def diameter(key=12.7, run_name=" 1/2 inch", counts=None, is_orphan=False):
    counts = {"BoltsDistances": 1, "ScrewNew": 1, "SetOfBolts": 2,
              "SetNutsBolts": 4, "SetBolts": 3} if counts is None else counts
    return {
        "key": key,
        "run_name": run_name,
        "description": "",
        "token": run_name.strip(),
        "counts": counts,
        "total_related": sum(counts.values()),
        "is_orphan": is_orphan,
    }


def anchor_name(anchor_id=1, standard="US Hooked Anchors", diameter=12.7,
                set_name="MuS", din=None):
    din = din if din is not None else [("ASTM A563", 12.7, "10.9", 2)]
    row = {
        "ID": anchor_id, "Standard": standard, "Diameter": diameter,
        "SetName": set_name, "MaterialKey": "10.9", "NumItems": len(din),
    }
    for slot in range(1, 7):
        if slot <= len(din):
            standard_i, diameter_i, material_i, position_i = din[slot - 1]
            row.update({
                f"DIN{slot}": standard_i, f"Diameter{slot}": diameter_i,
                f"Material{slot}": material_i, f"Position{slot}": position_i,
            })
        else:
            row.update({
                f"DIN{slot}": None, f"Diameter{slot}": 0.0,
                f"Material{slot}": None, f"Position{slot}": 0,
            })
    return row


def definition(def_id=10, anchor_id=1, length=152.4, thread=76.2,
               hook_radius=25.0):
    return {
        "ID": def_id, "AnchorID": anchor_id, "Length": length,
        "ThreadLength": thread, "TopDistance": 25.4, "HookRadius": hook_radius,
        "PartName": "Hooked Anchor 1/2x6x1-1/2",
    }


def nut_row(standard="ASTM A563", diameter=12.7, material="10.9", nut_type=1):
    return {
        "Standard": standard, "Diameter": diameter, "Material": material,
        "Type": nut_type, "Height": 12.3, "OutsideDiameter": 25.4,
        "NumberOfCorners": 6, "Name": "A563 Nut 1/2", "Weight": 0.03,
    }


ANCHOR_TABLES = {"AnchorsName", "AnchorsDefinition", "SetNutsBolts"}
BOLT_TABLES = {"BoltsDiameters", "BoltsDistances", "ScrewNew", "SetOfBolts",
               "SetNutsBolts", "SetBolts"}


def codes(findings):
    return [f["code"] for f in findings]


# --- bolt catalogs ----------------------------------------------------------

def test_bolt_clean_diameters_produce_no_findings():
    assert health.bolt_findings([diameter()], BOLT_TABLES) == []


def test_bolt_orphan_diameter_is_an_error():
    findings = health.bolt_findings(
        [diameter(counts={}, is_orphan=True)], BOLT_TABLES)
    assert codes(findings) == ["diameter_orphan"]
    assert findings[0]["severity"] == "error"


def test_bolt_missing_related_rows_is_a_warning_listing_tables():
    findings = health.bolt_findings(
        [diameter(counts={"SetBolts": 3, "BoltsDistances": 1})], BOLT_TABLES)
    assert codes(findings) == ["diameter_incomplete"]
    assert findings[0]["severity"] == "warn"
    assert "SetOfBolts" in findings[0]["message"]
    assert findings[0]["context"]["missing"] == ["ScrewNew", "SetOfBolts", "SetNutsBolts"]


def test_bolt_without_bolts_diameters_table_is_an_error():
    findings = health.bolt_findings([], {"SetBolts"})
    assert codes(findings) == ["bolts_diameters_missing"]


def test_bolt_with_no_diameters_is_an_error():
    findings = health.bolt_findings([], BOLT_TABLES)
    assert codes(findings) == ["no_diameters"]


# --- anchor catalogs --------------------------------------------------------

def test_anchor_clean_catalog_produces_no_findings():
    findings = health.anchor_findings(
        [anchor_name()], [definition()], [nut_row()], ANCHOR_TABLES)
    assert findings == []


def test_anchor_without_length_variants_is_an_error():
    findings = health.anchor_findings([anchor_name()], [], [nut_row()], ANCHOR_TABLES)
    assert "anchor_without_length" in codes(findings)


def test_anchor_definition_pointing_at_a_missing_name_is_an_error():
    findings = health.anchor_findings(
        [anchor_name(anchor_id=1)], [definition(anchor_id=99)], [nut_row()], ANCHOR_TABLES)
    assert "definition_orphan" in codes(findings)


def test_anchor_unmatched_hardware_slot_is_an_error():
    findings = health.anchor_findings(
        [anchor_name()], [definition()], [], ANCHOR_TABLES)
    assert codes(findings) == ["unmatched_component"]
    assert findings[0]["context"]["slot"] == 1


def test_anchor_hardware_matching_ignores_material_mismatch():
    findings = health.anchor_findings(
        [anchor_name()], [definition()], [nut_row(material="8.8")], ANCHOR_TABLES)
    assert findings == []


def test_anchor_thread_longer_than_length_is_an_error():
    findings = health.anchor_findings(
        [anchor_name()], [definition(length=100.0, thread=150.0)], [nut_row()], ANCHOR_TABLES)
    assert codes(findings) == ["thread_exceeds_length"]


def test_anchor_invalid_length_is_an_error():
    findings = health.anchor_findings(
        [anchor_name()], [definition(length=0.0)], [nut_row()], ANCHOR_TABLES)
    assert "invalid_length" in codes(findings)


def test_anchor_without_positive_diameter_is_an_error():
    findings = health.anchor_findings(
        [anchor_name(diameter=0.0)], [definition()], [nut_row()], ANCHOR_TABLES)
    assert "anchor_diameter_missing" in codes(findings)


def test_anchor_catalog_missing_a_table_is_an_error():
    findings = health.anchor_findings(
        [anchor_name()], [definition()], [nut_row()], {"AnchorsName"})
    assert codes(findings) == ["anchor_tables_missing"]


# --- shear-stud catalogs ----------------------------------------------------

def test_stud_findings_pass_through_with_areas():
    model = {
        "groups": [{"diameter": 6.0}],
        "issues": [
            {"severity": "error", "code": "no_lengths",
             "message": "No stud lengths.", "table": "SetBolts", "context": {}},
            {"severity": "info", "code": "run_name_format",
             "message": "Spacing kept.", "table": "ConnectorDiameters", "context": {}},
        ],
    }
    findings = health.stud_findings(model)
    assert codes(findings) == ["no_lengths", "run_name_format"]
    assert findings[0]["area"] == "hardware"
    assert findings[1]["area"] == "diameters"


def test_stud_findings_report_an_empty_connector_catalog():
    findings = health.stud_findings({"groups": [], "issues": []})
    assert codes(findings) == ["no_connector_families"]


# --- drawing-style exports --------------------------------------------------

def test_drawing_style_dangling_references_are_errors():
    report = {"dangling": [{
        "table": "DetObjReprMapItems", "column": "Appearance",
        "target": "DetObjAppearance",
        "missing": [1, 2, 3, 4, 5, 6, 7],
    }], "notes": []}
    findings = health.drawing_style_findings(report)
    assert codes(findings) == ["dangling_reference"]
    assert findings[0]["severity"] == "error"
    assert "DetObjReprMapItems.Appearance" in findings[0]["message"]
    assert "(2 more)" in findings[0]["message"]


def test_drawing_style_notes_are_warnings():
    report = {"dangling": [], "notes": ["rule order isn't 0..3"]}
    findings = health.drawing_style_findings(report)
    assert codes(findings) == ["style_structure"]
    assert findings[0]["severity"] == "warn"


def test_drawing_style_clean_report_is_empty():
    assert health.drawing_style_findings({"dangling": [], "notes": []}) == []


# --- sorting, summary and sections ------------------------------------------

def test_sort_findings_orders_by_severity_then_area():
    findings = [
        health.finding("info", "a", "note", area="structure"),
        health.finding("warn", "b", "warn", area="geometry"),
        health.finding("error", "c", "error", area="integrity"),
        health.finding("error", "d", "error", area="structure"),
    ]
    ordered = health.sort_findings(findings)
    assert [f["code"] for f in ordered] == ["d", "c", "b", "a"]


def test_summarize_counts_each_severity():
    findings = [
        health.finding("error", "e", "x"),
        health.finding("warn", "w", "x"),
        health.finding("info", "i", "x"),
        health.finding("info", "i2", "x"),
    ]
    assert health.summarize(findings) == {
        "errors": 1, "warnings": 1, "notes": 2, "total": 4}


def test_sections_group_by_area_in_declared_order():
    findings = health.sort_findings([
        health.finding("warn", "h", "x", area="hardware"),
        health.finding("error", "s", "x", area="structure"),
    ])
    grouped = health.sections(findings)
    assert [s["area"] for s in grouped] == ["structure", "hardware"]
    assert grouped[0]["title"] == "Catalog structure"


# --- report assembly --------------------------------------------------------

def _patch_tables(monkeypatch, tables, catalog_type, diameters=None):
    monkeypatch.setattr("utils.db.list_tables", lambda database: list(tables))
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: catalog_type)
    monkeypatch.setattr("utils.db.get_row_count",
                        lambda database, table: 1)
    if diameters is not None:
        monkeypatch.setattr("utils.db.get_catalog_diameters",
                            lambda database: diameters)


def test_build_report_for_a_bolt_catalog(monkeypatch):
    _patch_tables(monkeypatch, BOLT_TABLES, "bolt",
                  diameters=[diameter(counts={}, is_orphan=True)])
    report = health.build_report("A325TC")
    assert report["catalog_type"] == "bolt"
    assert report["summary"]["errors"] == 1
    assert report["sections"][0]["area"] == "diameters"
    assert {t["name"] for t in report["tables"]} == BOLT_TABLES


def test_build_report_for_an_anchor_catalog(monkeypatch):
    tables = {"AnchorsName", "AnchorsDefinition", "SetNutsBolts"}
    _patch_tables(monkeypatch, tables, "anchor")
    rows = {
        "AnchorsName": [anchor_name()],
        "AnchorsDefinition": [definition()],
        "SetNutsBolts": [nut_row()],
    }
    monkeypatch.setattr("utils.db.get_rows",
                        lambda database, table, limit=1000: rows.get(table, []))
    report = health.build_report("US_Hooked_Anchors")
    assert report["catalog_type"] == "anchor"
    assert report["findings"] == []
    assert report["summary"]["total"] == 0


def test_build_report_for_a_shear_stud_catalog(monkeypatch):
    _patch_tables(monkeypatch, {"SetBolts", "ConnectorDiameters"}, "shear stud")
    monkeypatch.setattr(
        "utils.shear_studs.get_browser_model",
        lambda database: {"groups": [], "issues": []})
    report = health.build_report("NelsonH4L")
    assert codes(report["findings"]) == ["no_connector_families"]


def test_build_report_for_a_drawing_style(monkeypatch):
    _patch_tables(monkeypatch, {"DetailStyle", "DetObjReprMapItems"}, "drawing style")
    monkeypatch.setattr(
        "utils.drawing_styles.integrity_report",
        lambda database: {"dangling": [], "notes": ["check me"], "checked": 3})
    report = health.build_report("DrawingStyleSample")
    assert codes(report["findings"]) == ["style_structure"]


def test_build_report_flags_an_unknown_shape(monkeypatch):
    _patch_tables(monkeypatch, {"SomeTable"}, "unknown")
    report = health.build_report("Mystery")
    assert codes(report["findings"]) == ["unknown_catalog_type"]


def test_build_report_notes_truncated_anchor_checks(monkeypatch):
    tables = {"AnchorsName", "AnchorsDefinition", "SetNutsBolts"}
    _patch_tables(monkeypatch, tables, "anchor")
    monkeypatch.setattr("utils.health.ROW_LIMIT", 1)
    rows = {
        "AnchorsName": [anchor_name()],
        "AnchorsDefinition": [definition()],
        "SetNutsBolts": [nut_row()],
    }
    monkeypatch.setattr("utils.db.get_rows",
                        lambda database, table, limit=1000: rows.get(table, []))
    report = health.build_report("US_Hooked_Anchors")
    assert codes(report["findings"]).count("truncated_check") == 3
    assert all(f["severity"] == "info" for f in report["findings"]
               if f["code"] == "truncated_check")
