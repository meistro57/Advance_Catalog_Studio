"""Smoke tests that the Flask app wires the bolt-set viewer routes and that the
viewer template renders for a bolt catalog without requiring a database."""

import pytest


def test_bolt_set_viewer_routes_registered():
    from app import app
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert "bolt_set_viewer" in endpoints
    assert "bolt_set_viewer_payload" in endpoints


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
