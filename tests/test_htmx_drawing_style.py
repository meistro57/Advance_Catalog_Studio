"""The drawing-style rule actions can answer as an htmx fragment so a reorder
or delete swaps one rules block instead of reloading the page. These tests
pin the fragment contract (and the plain-form fallback)."""

from flask import render_template


def _item(order, key=22001, **overrides):
    row = {
        "Key": key, "Order": order, "ObjQualifier": 1, "GeometricRestrictions": 0,
        "Appearance": 2, "AnnotationStrategy": 3, "LineType": 1, "SimplifiedGap": 5.08,
    }
    row.update(overrides)
    names = ["Beams", "VisibleHidden", "Beam label", "Continuous"]
    return {
        "row": row,
        "token": f"tok-{order}",
        "qset_name": names[0],
        "appearance_name": names[1],
        "strategy_name": names[2],
        "linetype_name": names[3],
        "label": None,
    }


def _block():
    return {
        "uid": "22001",
        "map_key": 22001,
        "repr_map": {"row": {"Key": 22001, "RunName": "Column - Top"}, "token": "map-tok"},
        "repr_items": [_item(0), _item(1)],
        "options": {
            "ObjQualifier": [(1, "Beams"), (2, "Plates")],
            "Appearance": [(2, "VisibleHidden")],
            "AnnotationStrategy": [(3, "Beam label")],
            "LineType": [(1, "Continuous")],
        },
    }


def _client():
    from app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_csrf"] = "tok"
    return client


def test_rules_partial_contains_ladder_table_and_htmx_wiring():
    from app import app
    with app.test_request_context("/"):
        html = render_template(
            "_drawing_rules.html", database="Demo", block=_block(),
            options=_block()["options"], ftin=str,
        )
    assert 'id="repr-22001"' in html
    assert "Representation rules" in html and "Column - Top" in html
    assert html.count('class="sd-step"') == 2
    assert 'class="ord">0<' in html and 'class="ord">1<' in html
    assert 'hx-post="/db/Demo/drawing-style/rule"' in html
    assert 'hx-vals=\'{"op": "up:22001:1", "uid": "22001"}\'' in html
    # Class-relative target: one representation map can appear under several views.
    assert 'hx-target="closest .repr-block"' in html and 'hx-swap="outerHTML"' in html
    assert 'hx-target="#repr-' not in html
    assert 'hx-include="#ruleForm [name=csrf_token]"' in html
    assert '<input type="hidden" form="ruleForm" name="uid" value="22001">' in html
    assert 'hx-confirm="Delete rule 0 (Beams)?"' in html
    assert "renumber:22001:0" in html


def test_rules_partial_reports_an_error_inline():
    from app import app
    with app.test_request_context("/"):
        html = render_template(
            "_drawing_rules.html", database="Demo", block=_block(),
            options=_block()["options"], ftin=str, rule_error="Rule change failed: boom",
        )
    assert "Rule change failed: boom" in html


def test_rule_action_answers_htmx_with_the_block(monkeypatch):
    import app as app_module
    block = _block()
    monkeypatch.setattr(app_module.drawing_styles, "repr_block", lambda *a, **k: block)
    monkeypatch.setattr(app_module.drawing_styles, "move_repr_item", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "_style_relations_or_none", lambda database: None)

    client = _client()
    resp = client.post("/db/Demo/drawing-style/rule",
                       data={"op": "up:22001:1", "uid": "22001-22001", "csrf_token": "tok"},
                       headers={"HX-Request": "true"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<html" not in body
    assert 'id="repr-22001"' in body
    assert "hx-swap-oob" in body


def test_rule_action_without_htmx_still_redirects(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module.drawing_styles, "compact_repr_orders", lambda *a, **k: None)
    client = _client()
    resp = client.post("/db/Demo/drawing-style/rule",
                       data={"op": "renumber:22001:0", "csrf_token": "tok"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("#pane-rules-22001")


def test_rule_action_redirects_to_the_view_that_sent_it(monkeypatch):
    """The no-JS fallback must land on the rules screen of the sending view, not
    on a shared map's anchor (which may belong to another view)."""
    import app as app_module
    monkeypatch.setattr(app_module.drawing_styles, "compact_repr_orders", lambda *a, **k: None)
    client = _client()
    resp = client.post("/db/Demo/drawing-style/rule",
                       data={"op": "renumber:900:0", "uid": "22002-900", "csrf_token": "tok"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("#pane-rules-22002")


def test_rule_action_ignores_a_forged_uid(monkeypatch):
    """A uid is echoed into element ids, so anything but digits and one dash is
    dropped instead of reaching the template."""
    import app as app_module
    seen = {}

    def fake_repr_block(database, map_key, relations=None, uid=None):
        seen["uid"] = uid
        block = _block()
        block["uid"] = uid or str(map_key)
        return block

    monkeypatch.setattr(app_module.drawing_styles, "repr_block", fake_repr_block)
    monkeypatch.setattr(app_module.drawing_styles, "move_repr_item", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "_style_relations_or_none", lambda database: None)
    client = _client()
    resp = client.post("/db/Demo/drawing-style/rule",
                       data={"op": "up:22001:1", "uid": '"><script>', "csrf_token": "tok"},
                       headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert seen["uid"] is None
    assert '<script>' not in resp.get_data(as_text=True)


def test_rule_action_error_is_flashed_and_shown(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module.drawing_styles, "repr_block", lambda *a, **k: _block())
    monkeypatch.setattr(app_module, "_style_relations_or_none", lambda database: None)
    client = _client()
    resp = client.post("/db/Demo/drawing-style/rule",
                       data={"op": "bogus:22001:0", "csrf_token": "tok"},
                       headers={"HX-Request": "true"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Rule change failed" in body
    assert "hx-swap-oob" in body


def test_rule_action_requires_csrf():
    from app import app
    resp = app.test_client().post("/db/Demo/drawing-style/rule",
                                  data={"op": "up:1:0"},
                                  headers={"HX-Request": "true"})
    assert resp.status_code == 400


def test_save_answers_htmx_with_flash_only(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module.drawing_styles, "apply_field_edits",
                        lambda database, edits: (1, []))
    client = _client()
    resp = client.post("/db/Demo/drawing-style/save",
                       data={"csrf_token": "tok", "f::DetailStyle::t::RunName": "New"},
                       headers={"HX-Request": "true"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<html" not in body
    assert "beforeend:#flashHost" in body
    assert "Saved 1 field(s)" in body


def test_save_without_htmx_redirects(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module.drawing_styles, "apply_field_edits",
                        lambda database, edits: (1, []))
    client = _client()
    resp = client.post("/db/Demo/drawing-style/save",
                       data={"csrf_token": "tok", "f::DetailStyle::t::RunName": "New",
                             "anchor": "req-22001"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("#req-22001")


def test_page_uses_the_vendored_htmx_copy():
    import os

    from app import app

    template = open(os.path.join(app.root_path, "templates", "drawing_style.html")).read()
    assert "vendor/htmx/htmx.min.js" in template
    vendor = os.path.join(app.root_path, "static", "vendor", "htmx", "htmx.min.js")
    assert os.path.getsize(vendor) > 20000


def test_library_panels_are_menu_screens_not_tabs():
    """The libraries are separate menu screens now, so the tab strip (and its
    collapse behaviour) is gone; the menu drives one pane at a time."""
    import os

    from app import app

    template = open(os.path.join(app.root_path, "templates", "drawing_style.html")).read()
    assert 'data-bs-toggle="tab"' not in template
    assert 'data-bs-toggle="collapse"' not in template
    assert 'data-pane="pane-lib-labels"' in template
    assert 'id="pane-lib-labels"' in template
