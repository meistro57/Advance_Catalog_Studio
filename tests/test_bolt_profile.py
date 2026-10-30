"""The dimensioned profile is the bolt-set viewer's explanation layer, so its
geometry and labels must stay tied to the layout numbers (all in inches on
screen, millimetres in storage)."""

import re

import pytest

from utils import bolt_profile as bp


def _view(**overrides):
    view = {
        "bolt": {
            "length": 101.6, "head_height": 9.525, "head_width": 22.225,
            "diameter": 19.05, "name": "A325 TC 3/4",
        },
        "grip": {"bottom": 25.4, "thickness": 50.8},
        "components": [
            {"slot": 1, "role": "washer", "standard": "ASTM F436", "height": 3.175,
             "width": 34.925, "diameter": 19.05, "stack_bottom": 0, "stack_top": 3.175,
             "matched": True},
            {"slot": 2, "role": "nut", "standard": "ASTM A563", "height": 22.225,
             "width": 31.75, "diameter": 19.05, "stack_bottom": 3.175, "stack_top": 25.4,
             "matched": True},
            {"slot": 4, "role": "washer", "standard": "ASTM F436", "height": 3.175,
             "width": 34.925, "diameter": 19.05, "stack_bottom": 76.2, "stack_top": 79.375,
             "matched": False},
            {"slot": 5, "role": "nut", "standard": "ASTM A563", "height": 22.225,
             "width": 31.75, "diameter": 19.05, "stack_bottom": 79.375, "stack_top": 101.6,
             "matched": True},
        ],
    }
    view.update(overrides)
    return view


def _rect(svg, cls):
    match = re.search(
        rf'class="{cls}[^"]*" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg
    )
    return match and tuple(float(v) for v in match.groups())


def test_profile_draws_head_and_shank_at_one_scale():
    svg = bp.profile_svg(_view())
    head = _rect(svg, "bp-head")
    shank = _rect(svg, "bp-shank")
    assert head and shank
    head_thickness_px = head[2]
    ratio = shank[2] / head_thickness_px
    assert ratio == pytest.approx(101.6 / 9.525, rel=0.02)


def test_profile_component_widths_follow_the_stack():
    svg = bp.profile_svg(_view())
    nut = re.search(
        r'class="bp-part" x="([\d.]+)" y="[\d.]+" width="([\d.]+)"[^/]*fill="#5b6ee1"', svg
    )
    assert nut, svg[:400]
    shank = _rect(svg, "bp-shank")
    stack_px = float(nut.group(2))
    assert stack_px / shank[2] == pytest.approx(22.225 / 101.6, rel=0.05)


def test_profile_dimensions_are_reported_in_inches():
    svg = bp.profile_svg(_view())
    assert "overall 4.375 in" in svg
    assert "shank under head 4 in" in svg
    assert "grip 2 in" in svg
    assert "head 0.875 in across flats \u00d7 0.375 in high" in svg
    assert "shank \u2300 0.75 in" in svg


def test_profile_balloons_and_legend_number_every_component():
    svg = bp.profile_svg(_view())
    assert svg.count('class="bp-balloon"') == 4
    assert "1. DIN1 \u00b7 washer \u00b7 ASTM F436" in svg
    assert "4. DIN5 \u00b7 nut \u00b7 ASTM A563" in svg
    assert "h 0.125 in" in svg


def test_profile_marks_unmatched_records():
    svg = bp.profile_svg(_view())
    assert 'id="bp-hatch-1"' in svg
    assert "UNMATCHED" in svg
    assert 'class="bp-part bp-unmatched"' in svg


def test_profile_marks_schematic_thicknesses():
    view = _view()
    view["components"][0]["height"] = None
    view["components"][0]["schematic_height"] = True
    svg = bp.profile_svg(view)
    assert "schematic thickness" in svg


def test_profile_without_grip_skips_material():
    view = _view()
    view["grip"] = {"bottom": 25.4, "thickness": 0}
    svg = bp.profile_svg(view)
    assert "clamped material" not in svg
    assert "grip " not in svg


def test_profile_without_bolt_record_says_so():
    svg = bp.profile_svg({"bolt": {}, "components": [], "grip": {}})
    assert "no profile to draw" in svg


def test_profile_without_components_still_draws_the_bolt():
    view = _view(components=[])
    svg = bp.profile_svg(view)
    assert "overall 4.375 in" in svg
    assert 'class="bp-balloon"' not in svg


def test_profile_truncates_long_names():
    view = _view()
    view["bolt"]["name"] = "A" * 90
    svg = bp.profile_svg(view)
    assert "A" * 59 + "…" in svg
    assert "A" * 61 not in svg


def test_profile_ignores_broken_stack_values():
    view = _view()
    view["components"].append({"slot": 9, "role": "nut", "stack_bottom": None, "stack_top": 5})
    svg = bp.profile_svg(view)
    assert svg.count('class="bp-balloon"') == 4


def test_sanitize_layout_keeps_known_fields_only():
    clean = bp.sanitize_layout({
        "csrf_token": "secret",
        "bolt": {"length": 100, "head_height": 10, "head_width": 20, "diameter": 10,
                 "name": "n" * 200, "owner": "drop me"},
        "grip": {"bottom": 10, "thickness": 30, "top": 40},
        "components": [
            {"slot": 1, "role": "nut", "standard": "S" * 100, "stack_bottom": 0,
             "stack_top": 10, "matched": True, "evil": "<script>"},
        ],
    })
    assert clean["bolt"] == {"length": 100.0, "head_height": 10.0, "head_width": 20.0,
                             "diameter": 10.0, "name": "n" * 64}
    assert clean["grip"] == {"bottom": 10.0, "thickness": 30.0}
    assert clean["components"][0]["standard"] == "S" * 32
    assert "evil" not in clean["components"][0]
    assert "csrf_token" not in str(clean["bolt"])


def test_sanitize_layout_caps_component_count():
    components = [{"slot": i, "role": "nut", "stack_bottom": i, "stack_top": i + 1} for i in range(40)]
    clean = bp.sanitize_layout({"components": components})
    assert len(clean["components"]) == bp.MAX_COMPONENTS


def test_sanitize_layout_drops_non_numeric_numbers():
    clean = bp.sanitize_layout({
        "bolt": {"length": "abc", "head_height": "nan", "head_width": None, "diameter": "10"},
        "grip": {"bottom": "inf", "thickness": 5},
        "components": "not-a-list",
    })
    assert clean["bolt"] == {"length": None, "head_height": None, "head_width": None,
                             "diameter": 10.0, "name": ""}
    assert clean["grip"] == {"bottom": None, "thickness": 5.0}
    assert clean["components"] == []


def test_sanitized_layout_renders():
    payload = bp.sanitize_layout(_view())
    svg = bp.profile_svg(payload)
    assert "overall 4.375 in" in svg


def test_sketch_route_requires_csrf():
    from app import app
    resp = app.test_client().post("/db/SomeDb/bolt-set-viewer/sketch", json={"bolt": {"length": 100}})
    assert resp.status_code == 400


def test_sketch_route_renders_posted_layout():
    from app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_csrf"] = "tok"
    payload = bp.sanitize_layout(_view())
    payload["csrf_token"] = "tok"
    resp = client.post("/db/SomeDb/bolt-set-viewer/sketch", json=payload)
    assert resp.status_code == 200
    assert resp.mimetype == "image/svg+xml"
    body = resp.get_data(as_text=True)
    assert "overall 4.375 in" in body
    assert 'id="bp-hatch-1"' in body


def test_viewer_template_has_every_element_id_the_script_uses():
    import os
    import re

    from flask import render_template

    from app import app

    with app.test_request_context("/"):
        html = render_template(
            "bolt_set_viewer.html",
            database="Demo",
            csrf_token="tok",
            combos=[{"standard": "S", "set": "Mu2S", "material": "M", "diameter": 9.525}],
        )
    assert 'window.BOLT_CSRF = "tok"' in html
    assert 'id="componentTable"' in html and "<tbody>" in html
    script = open(os.path.join(app.root_path, "static", "js", "bolt-set-viewer.js")).read()
    ids = set(re.findall(r"\$\('([A-Za-z0-9_]+)'\)", script))
    missing = sorted(i for i in ids if f'id="{i}"' not in html)
    assert missing == []
