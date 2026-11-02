"""Smoke tests that the Flask app wires the bolt-set viewer routes and that the
viewer template renders for a bolt catalog without requiring a database."""

import pytest


def test_bolt_set_viewer_routes_registered():
    from app import app
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert "bolt_set_viewer" in endpoints
    assert "bolt_set_viewer_payload" in endpoints


def test_anchor_configurator_routes_registered():
    from app import app
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert "anchor_configurator" in endpoints
    assert "anchor_configurator_payload" in endpoints


def test_fabrication_sheet_route_registered():
    from app import app
    assert "fabrication_sheet" in {r.endpoint for r in app.url_map.iter_rules()}


def test_fabrication_sheet_redirects_when_ids_missing():
    from app import app
    client = app.test_client()
    resp = client.get("/db/SomeDb/fabrication-sheet")
    assert resp.status_code == 302
    assert "anchor-configurator" in resp.headers["Location"]


def test_bolt_set_viewer_redirects_for_non_bolt(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "anchor")
    client = app.test_client()
    resp = client.get("/db/SomeAnchor/bolt-set-viewer")
    assert resp.status_code == 302
    assert "/db/SomeAnchor" in resp.headers["Location"]


def test_payload_rejects_bad_numbers():
    from app import app
    client = app.test_client()
    resp = client.get("/db/SomeDb/bolt-set-viewer/payload?standard=A&set=B&material=C&diameter=abc")
    assert resp.status_code == 400


def test_payload_rejects_missing_fields():
    from app import app
    client = app.test_client()
    resp = client.get("/db/SomeDb/bolt-set-viewer/payload?diameter=12.7")
    assert resp.status_code == 400


def test_anchor_configurator_redirects_for_non_anchor(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "bolt")
    client = app.test_client()
    resp = client.get("/db/SomeBolt/anchor-configurator")
    assert resp.status_code == 302
    assert "/db/SomeBolt" in resp.headers["Location"]


def test_anchor_payload_rejects_bad_ids():
    from app import app
    client = app.test_client()
    resp = client.get("/db/SomeDb/anchor-configurator/payload?anchor_id=abc&def_id=1")
    assert resp.status_code == 400


def test_drawing_style_routes_registered():
    from app import app
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    for ep in ("drawing_style", "drawing_style_save", "drawing_style_rule", "drawing_style_label_preview"):
        assert ep in endpoints


def test_drawing_style_redirects_for_non_style(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "bolt")
    resp = app.test_client().get("/db/SomeBolt/drawing-style")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/db/SomeBolt")


def test_drawing_style_writes_require_csrf():
    from app import app
    client = app.test_client()
    assert client.post("/db/X/drawing-style/save", data={}).status_code == 400
    assert client.post("/db/X/drawing-style/rule", data={"op": "delete:1:0"}).status_code == 400


def test_label_preview_renders_without_db():
    from app import app
    resp = app.test_client().post(
        "/db/X/drawing-style/label-preview", data={"content": "#Rounded%Position#End#Newline%Name"},
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "lp-frame" in body and "b104" in body and "BEAM" in body


# --- shear-stud browser (issue #4) -----------------------------------------

def _fake_shear_stud_model():
    from utils import shear_studs as ss
    built = ss.build_groups(
        standards=[{"Key": "Nelson H4L", "RunName": "Nelson H4L", "OwnerText": "DSC"}],
        materials=[{"Key": "Mild Steel", "RunName": "Mild Steel", "weight": 0.0,
                    "OwnerText": "DSC"}],
        diameters=[{"Key": 6.0, "RunName": " 6.00 mm", "Description": None}],
        distances=[{"Key": 6.0, "HoleTolerance": 0.0, "along": 12.0, "across": 9.0,
                    "Description": None}],
        relations=[{"Key": 1, "ConnectorStandard": "Nelson H4L",
                    "ConnectorMaterial": "Mild Steel", "ConnectorDiameter": 6.0}],
        stud_rows=[{
            "Standard": "Nelson H4L", "Material": "Mild Steel", "Diameter": 6.0,
            "Length": 20.0, "ScrewHeadOuterDiameter": 12.7, "HeadHeight": 4.7,
            "NumberOfCorners": 0, "Name": "Nelson H4L 6 x 20", "Weight": 0.0081,
            "OwnerText": "DSC", "Source": "Nelson H4L", "Type": 2,
        }],
    )
    issues = ss.collect_issues(built["groups"], built["issues"])
    return {
        "groups": built["groups"],
        "families": ss.family_tree(built["groups"]),
        "issues": issues,
        "global_issues": built["issues"],
        "summary": ss.summarize(built["groups"], issues),
        "options": ss.filter_options(built["groups"]),
        "diameter_keys": [6.0],
        "relation_keys": [1],
    }


def test_shear_stud_browser_route_registered():
    from app import app
    assert "shear_stud_browser" in {r.endpoint for r in app.url_map.iter_rules()}


def test_shear_stud_browser_redirects_for_other_catalogs(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "bolt")
    resp = app.test_client().get("/db/SomeBolt/shear-stud-browser")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/db/SomeBolt")


def test_shear_stud_browser_renders_model(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "shear stud")
    monkeypatch.setattr("utils.shear_studs.get_browser_model",
                        lambda database: _fake_shear_stud_model())
    resp = app.test_client().get("/db/NelsonH4L/shear-stud-browser")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Nelson H4L 6 x 20" in body
    assert "complete" in body


def test_shear_stud_browser_ignores_non_numeric_filter(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "shear stud")
    monkeypatch.setattr("utils.shear_studs.get_browser_model",
                        lambda database: _fake_shear_stud_model())
    resp = app.test_client().get("/db/NelsonH4L/shear-stud-browser?diameter=abc")
    assert resp.status_code == 200
    assert "not a number" in resp.get_data(as_text=True)


def test_shear_stud_browser_applies_length_filter(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "shear stud")
    monkeypatch.setattr("utils.shear_studs.get_browser_model",
                        lambda database: _fake_shear_stud_model())
    resp = app.test_client().get("/db/NelsonH4L/shear-stud-browser?length=99")
    assert resp.status_code == 200
    assert "No studs match the current filters." in resp.get_data(as_text=True)


def test_add_diameter_redirects_for_shear_stud_catalogs(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "shear stud")
    resp = app.test_client().get("/db/NelsonH4L/add-diameter")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/db/NelsonH4L")


# --- shear-stud clone proposal (preview only) ------------------------------

def test_shear_stud_clone_preview_route_registered():
    from app import app
    assert "shear_stud_clone_preview" in {r.endpoint for r in app.url_map.iter_rules()}


def test_shear_stud_clone_preview_redirects_for_other_catalogs(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "bolt")
    resp = app.test_client().post("/db/SomeBolt/shear-stud-browser/clone-preview", data={})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/db/SomeBolt")


def _clone_post(client, **overrides):
    data = {
        "standard": "Nelson H4L", "material": "Mild Steel",
        "source_diameter": "6", "target_diameter": "8", "lengths": "20",
        "scale_geometry": "on",
    }
    data.update(overrides)
    return client.post("/db/NelsonH4L/shear-stud-browser/clone-preview", data=data)


def test_shear_stud_clone_preview_renders_proposed_rows(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "shear stud")
    monkeypatch.setattr("utils.shear_studs.get_browser_model",
                        lambda database: _fake_shear_stud_model())
    resp = _clone_post(app.test_client())
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "preview only" in body
    assert "Nelson H4L 8 x 20" in body
    assert "ConnectorRelations" in body and "SetBolts" in body
    assert "reviewable" in body


def test_shear_stud_clone_preview_blocks_duplicate_diameter(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "shear stud")
    monkeypatch.setattr("utils.shear_studs.get_browser_model",
                        lambda database: _fake_shear_stud_model())
    resp = _clone_post(app.test_client(), target_diameter="6")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "blocked" in body
    assert "already exists" in body


def test_shear_stud_browser_renders_imperial_units(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "shear stud")
    monkeypatch.setattr("utils.shear_studs.get_browser_model",
                        lambda database: _fake_shear_stud_model())
    resp = app.test_client().get("/db/NelsonH4L/shear-stud-browser?units=in")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "≈ 1/4 in" in body
    assert "units=mm" in body and "units=in" in body


def test_shear_stud_clone_preview_uses_requested_units(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "shear stud")
    monkeypatch.setattr("utils.shear_studs.get_browser_model",
                        lambda database: _fake_shear_stud_model())
    resp = _clone_post(app.test_client(), units="in")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "≈ 1/4 in" in body
    assert "≈ 5/16 in" in body
    assert "stored values (millimetres)" in body


# --- catalog health report --------------------------------------------------

def _fake_health_report():
    from utils import health
    findings = health.sort_findings([
        health.finding("error", "diameter_orphan", "No related rows.",
                       "BoltsDiameters", "diameters"),
        health.finding("warn", "diameter_incomplete", "Missing SetBolts rows.",
                       "BoltsDiameters", "diameters"),
    ])
    return {
        "database": "SomeDb", "catalog_type": "bolt",
        "tables": [{"name": "BoltsDiameters", "rows": 2}],
        "findings": findings, "summary": health.summarize(findings),
        "sections": health.sections(findings),
    }


def test_catalog_health_route_registered():
    from app import app
    assert "catalog_health" in {r.endpoint for r in app.url_map.iter_rules()}


def test_catalog_health_renders_findings(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.health.build_report", lambda database: _fake_health_report())
    resp = app.test_client().get("/db/SomeDb/health")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Catalog health" in body
    assert "diameter_orphan" in body and "diameter_incomplete" in body
    assert "Diameters" in body
    assert "read-only" in body


def test_catalog_health_redirects_when_the_report_fails(monkeypatch):
    from app import app

    def boom(database):
        raise RuntimeError("no connection")

    monkeypatch.setattr("utils.health.build_report", boom)
    resp = app.test_client().get("/db/SomeDb/health")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/db/SomeDb")


def test_database_page_links_the_health_report(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.list_tables", lambda database: ["SetBolts"])
    monkeypatch.setattr("utils.db.get_row_count", lambda database, table: 1)
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "bolt")
    monkeypatch.setattr("utils.db.get_catalog_diameters", lambda database: [])
    resp = app.test_client().get("/db/SomeDb")
    assert resp.status_code == 200
    assert "/db/SomeDb/health" in resp.get_data(as_text=True)


# --- drawing-style sub-style usage ------------------------------------------

def _fake_usage_model():
    return {
        "database": "StyleSample",
        "orphans": {
            "total": 1,
            "tables": [{
                "table": "DetObjAppearance", "reached_from": ["DetObjReprMapItems.Appearance"],
                "rows": 2, "unreferenced": 1, "samples": [{"label": "Unused"}],
            }],
        },
        "shared_tables": ["DetObjAppearance"],
        "selected_table": "DetObjAppearance",
        "candidates": [{"label": "Visible", "token": "22001", "references": 2}],
        "selected_token": "22001",
        "report": {
            "ok": True,
            "record": {"table": "DetObjAppearance", "label": "Visible", "pk": {"Key": 22001}},
            "styles": [{
                "key": 22001, "name": "3 - Elevation View - Full", "owner": "DSC",
                "master_name": "3 - Elevation View - Full",
                "categories": {"base": 3, "sub": 9},
                "path": [{"table": "DetObjReprMapItems", "column": "Appearance", "label": "22001"},
                         {"table": "DetailStyle", "column": "Request1", "label": "3 - Elevation View - Full"}],
            }],
            "direct": [{"table": "DetObjReprMapItems", "labels": ["22001"]}],
            "truncated": False,
        },
        "row_limit": 5000,
        "truncated_rows": [],
    }


def test_drawing_style_usage_route_registered():
    from app import app
    assert "drawing_style_usage" in {r.endpoint for r in app.url_map.iter_rules()}


def test_drawing_style_usage_redirects_for_non_style(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "bolt")
    resp = app.test_client().get("/db/SomeBolt/drawing-style/usage")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/db/SomeBolt")


def test_drawing_style_usage_renders_orphans_and_used_by(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "drawing style")
    monkeypatch.setattr("utils.style_usage.build_page_model",
                        lambda database, table=None, token=None: _fake_usage_model())
    resp = app.test_client().get("/db/StyleSample/drawing-style/usage")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Unreferenced" in body or "no drawing style reaches" in body
    assert "DetObjAppearance" in body and "Visible" in body
    assert "3 - Elevation View - Full" in body
    assert "read-only" in body


def test_drawing_style_usage_redirects_when_the_model_fails(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "drawing style")

    def boom(database, table=None, token=None):
        raise RuntimeError("no relations")

    monkeypatch.setattr("utils.style_usage.build_page_model", boom)
    resp = app.test_client().get("/db/StyleSample/drawing-style/usage")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/db/StyleSample/drawing-style")
