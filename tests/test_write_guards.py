"""Write guards: CSRF on mutating routes, and read-only delivered libraries.

No database is touched: the CSRF failure and the library block both happen
before any route reaches `utils.db`.
"""

import json

import pytest

from utils import metadata, snapshots


def _csrf(client):
    client.get("/")
    with client.session_transaction() as session:
        return session["_csrf"]


def _post(client, path, data=None):
    payload = dict(data or {})
    payload["csrf_token"] = _csrf(client)
    return client.post(path, data=payload)


# --- CSRF ------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/upload",
    "/attach",
    "/create",
    "/db/SomeDb/detach",
    "/db/SomeDb/SetBolts/abc/delete",
    "/db/SomeDb/SetBolts/abc/duplicate",
    "/db/SomeDb/SetBolts/add",
    "/db/SomeDb/SetBolts/abc/edit",
])
def test_mutating_routes_reject_a_missing_csrf_token(path):
    from app import app
    resp = app.test_client().post(path, data={})
    assert resp.status_code == 400


def test_batch_writes_reject_a_missing_csrf_token():
    from app import app
    client = app.test_client()
    assert client.post("/db/SomeDb/add-diameter",
                       data={"action": "apply", "source_dia": "10",
                             "target_dia": "12"}).status_code == 400
    assert client.post("/db/SomeDb/find-replace",
                       data={"action": "apply", "find": "x",
                             "replace": "y"}).status_code == 400


def test_read_only_previews_stay_token_free(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.preview_find_replace", lambda database, text: {})
    client = app.test_client()
    assert client.post("/db/SomeDb/find-replace",
                       data={"action": "preview", "find": "x"}).status_code == 200
    assert client.post("/db/X/drawing-style/label-preview",
                       data={"content": "%Name"}).status_code == 200


# --- delivered libraries ---------------------------------------------------

def test_library_kind_recognises_the_astor_files():
    assert metadata.library_kind("AstorDetails.mdf") == "astordetails"
    assert metadata.library_kind("/tmp/uploads/AstorBase.mdf") == "astorbase"
    assert metadata.library_kind("A325TC.mdf") is None
    assert metadata.library_kind("") is None
    assert metadata.library_label("astordetails").startswith("delivered")


def test_attach_records_library_provenance(monkeypatch):
    from app import app
    stored = {}
    monkeypatch.setattr("utils.db.attach_database", lambda *a, **k: None)
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "drawing style")
    monkeypatch.setattr("utils.docker_ops.copy_into_container", lambda *a, **k: None)
    monkeypatch.setattr("utils.metadata.set_meta",
                        lambda database, catalog_type=None, as_version=None, library=None:
                        stored.update({"database": database, "library": library}))

    resp = _post(app.test_client(), "/attach", {
        "base": "AstorDetails", "mdf": "AstorDetails.mdf", "ldf": "AstorDetails_log.ldf",
        "db_name": "AstorDetails", "as_version": "2026",
    })
    assert resp.status_code == 302
    assert stored["library"] == "astordetails"


def test_delivered_library_blocks_batch_writes(monkeypatch):
    from app import app

    applied = []
    monkeypatch.setattr("utils.metadata.get",
                        lambda database: {"library": "astordetails", "catalog_type": "bolt"})
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "bolt")
    monkeypatch.setattr("utils.db.get_catalog_diameters", lambda database: [])
    monkeypatch.setattr("utils.snapshots.create_snapshot",
                        lambda database, reason: applied.append("snapshot") or {})
    monkeypatch.setattr("utils.db.apply_clone_diameter",
                        lambda **kwargs: applied.append("apply") or {})

    resp = _post(app.test_client(), "/db/AstorDetails/add-diameter", {
        "action": "apply", "source_dia": "10", "target_dia": "12",
        "target_name": " 12.00 mm", "replace_from": "10.00", "replace_to": "12.00",
    })
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/db/AstorDetails")
    assert applied == []


def test_delivered_library_blocks_row_deletes(monkeypatch):
    from app import app
    deleted = []
    monkeypatch.setattr("utils.metadata.get",
                        lambda database: {"library": "astorbase"})
    monkeypatch.setattr("utils.db.delete_row",
                        lambda *a, **k: deleted.append(a))

    resp = _post(app.test_client(), "/db/AstorBase/SetBolts/abc/delete")
    assert resp.status_code == 302
    assert deleted == []


def test_delivered_library_allows_reads_and_export(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.metadata.get",
                        lambda database: {"library": "astordetails"})
    monkeypatch.setattr("utils.db.list_tables", lambda database: ["DetStyle"])
    monkeypatch.setattr("utils.db.get_row_count", lambda database, table: 0)
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "drawing style")
    monkeypatch.setattr("utils.db.get_catalog_diameters", lambda database: [])
    resp = app.test_client().get("/db/AstorDetails")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "read-only" in body


# --- snapshot retention route ----------------------------------------------

def test_prune_route_requires_csrf(monkeypatch, tmp_path):
    from app import app
    monkeypatch.setattr("utils.snapshots.config.SNAPSHOT_DIR", str(tmp_path))
    assert app.test_client().post("/db/SomeDb/snapshots/prune",
                                  data={"keep": "2"}).status_code == 400


def test_prune_route_keeps_the_newest_snapshots(monkeypatch, tmp_path):
    from app import app
    monkeypatch.setattr("utils.snapshots.config.SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setattr("utils.db.list_tables", lambda database: [])
    monkeypatch.setattr("utils.db.get_row_count", lambda database, table: 0)
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "bolt")
    monkeypatch.setattr("utils.db.get_catalog_diameters", lambda database: [])

    directory = tmp_path / "SomeDb"
    directory.mkdir()
    names = [f"SomeDb_2026110{day}T000000Z_run.bak" for day in range(1, 5)]
    for name in names:
        (directory / name).write_bytes(b"S" * 8)
        (directory / (name + ".json")).write_text(json.dumps({
            "filename": name, "reason": "run", "database": "SomeDb",
        }))

    resp = _post(app.test_client(), "/db/SomeDb/snapshots/prune", {"keep": "2"})

    assert resp.status_code == 302
    remaining = sorted(p.name for p in directory.iterdir() if p.suffix == ".bak")
    assert remaining == names[2:]
    assert snapshots.snapshot_files("SomeDb")


# --- health report downloads ----------------------------------------------

def _fake_health_report():
    return {
        "database": "SomeDb",
        "catalog_type": "bolt",
        "tables": [{"name": "SetBolts", "rows": 3}],
        "findings": [
            {"severity": "error", "area": "diameters", "code": "orphan_diameter",
             "message": "10.0 mm has no related rows", "table": "BoltsDiameters",
             "context": {}},
            {"severity": "warn", "area": "hardware", "code": "missing_nut",
             "message": "no nut for this set", "table": None, "context": {}},
        ],
        "summary": {"errors": 1, "warnings": 1, "notes": 0, "total": 2},
        "sections": [],
    }


def test_health_json_download(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.health.build_report", lambda database: _fake_health_report())
    resp = app.test_client().get("/db/SomeDb/health.json")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert resp.headers["Content-Disposition"] == 'attachment; filename="SomeDb-health.json"'
    payload = json.loads(resp.get_data(as_text=True))
    assert payload["summary"]["total"] == 2
    assert payload["findings"][0]["code"] == "orphan_diameter"


def test_health_csv_download(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.health.build_report", lambda database: _fake_health_report())
    resp = app.test_client().get("/db/SomeDb/health.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert resp.headers["Content-Disposition"] == 'attachment; filename="SomeDb-health.csv"'
    lines = resp.get_data(as_text=True).strip().splitlines()
    assert lines[0] == "severity,area,code,table,message"
    assert lines[1].startswith("error,diameters,orphan_diameter,BoltsDiameters,")
    assert lines[2].startswith("warn,hardware,missing_nut,,")


def test_health_download_rejects_an_invalid_database_name():
    from app import app
    resp = app.test_client().get("/db/bad%20name/health.json")
    assert resp.status_code == 400  # invalid identifier, refused before SQL


def test_health_download_reports_a_build_failure(monkeypatch):
    from app import app
    def boom(database):
        raise RuntimeError("container down")
    monkeypatch.setattr("utils.health.build_report", boom)
    resp = app.test_client().get("/db/SomeDb/health.json")
    assert resp.status_code == 503


# --- the invariant, checked against the live URL map -----------------------

READ_ONLY_POST_ENDPOINTS = {
    "shear_stud_clone_preview",
    "drawing_style_label_preview",
    "bolt_set_viewer_sketch",
}


def test_every_writing_post_route_requires_csrf():
    import re

    from app import app

    client = app.test_client()
    for rule in app.url_map.iter_rules():
        if "POST" not in (rule.methods or set()):
            continue
        if rule.endpoint in READ_ONLY_POST_ENDPOINTS:
            continue
        path = re.sub(r"<[^>]+>", "x", rule.rule)
        data = {"action": "apply"} if rule.endpoint in {"find_replace", "add_diameter"} else {}
        resp = client.post(path, data=data)
        assert resp.status_code == 400, f"{rule.endpoint} accepted a POST without a token"


def test_read_only_post_routes_are_listed_and_documented():
    from pathlib import Path
    doc = (Path(__file__).resolve().parent.parent / "docs" / "csrf-audit.md").read_text()
    for endpoint in READ_ONLY_POST_ENDPOINTS:
        assert endpoint in doc
