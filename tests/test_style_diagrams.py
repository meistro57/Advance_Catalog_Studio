"""The drawing-style figures are the page's explanation layer, so their labels
must stay tied to the row values (and stay honest about what is unverified)."""

import re

import pytest

from utils import style_diagrams as sd


def _numbers(svg, pattern):
    return [float(m) for m in re.findall(pattern, svg)]


def test_scale_bar_reports_paper_size_for_denominator():
    svg = sd.scale_bar_svg(0.125)  # 1:8
    assert "1:8" in svg
    assert 'One foot of model prints 1 1/2" wide' in svg
    assert "1'-0\"" in svg


def test_scale_bar_handles_non_clean_scale():
    svg = sd.scale_bar_svg(0.0731)
    assert "not a clean 1:N" in svg


def test_scale_bar_marks_twelve_inch_bar():
    svg = sd.scale_bar_svg(0.0625)
    for tick in ('>3"<', '>6"<', '>9"<'):
        assert tick in svg


def test_view_box_labels_extents_and_depth():
    svg = sd.view_box_svg({
        "xDelta": 609.6, "yDelta": 304.8,
        "zDeltaFront": 3.175, "zDeltaRear": 101.6,
        "xyMode": 1, "zMode": 4, "EnlargeByEnv": False,
    })
    assert 'X extend 609.6 mm (2\'-0")' in svg
    assert 'Y extend 304.8 mm (1\'-0")' in svg
    assert "in front" in svg and "behind" in svg
    assert "xy mode 1" in svg and "z mode 4" in svg
    assert "not enlarged" in svg


def test_view_box_front_and_rear_drawn_to_scale():
    svg = sd.view_box_svg({"xDelta": 100, "yDelta": 100, "zDeltaFront": 10, "zDeltaRear": 100})
    widths = _numbers(svg, r'class="sd-part" x="[\d.]+" y="78.0" width="([\d.]+)"')
    assert widths, svg
    bar = widths[0]
    assert bar > 100
    assert 'class="sd-part-dark"' in svg


def test_view_box_without_depth_says_so():
    svg = sd.view_box_svg({"xDelta": 0, "yDelta": 0, "zDeltaFront": 0, "zDeltaRear": 0})
    assert "no XY extents" in svg
    assert "no depth on either side" in svg


def test_view_box_flags_min_size_enlargement():
    svg = sd.view_box_svg({"xDelta": 50, "yDelta": 50, "zDeltaFront": 5, "zDeltaRear": 5,
                           "EnlargeByEnv": True, "MinSizeEnv": 50.8})
    assert "enlarged to minimum size 50.8 mm" in svg


def test_length_clip_off_means_no_break_lines():
    svg = sd.length_clip_svg({"X Clip": 0, "Y Clip": 1, "MinRemainingLength": 19.05,
                              "MinClipIntervalLength": 31.75, "Extension": -1.0,
                              "ClippingGap": 5.0})
    assert "X clip is off" in svg
    assert "clip line" not in svg
    assert "X clip off · Y clip on" in svg
    assert "negative sentinel" in svg


def test_length_clip_on_labels_both_distances():
    svg = sd.length_clip_svg({"X Clip": 1, "Y Clip": 0, "MinRemainingLength": 19.05,
                              "MinClipIntervalLength": 31.75, "Extension": 2.0,
                              "ClippingGap": 5.0})
    assert 'MinClipIntervalLength 31.75 mm (1 1/4")' in svg
    assert 'MinRemainingLength 19.05 mm (3/4")' in svg
    assert svg.count("clip line") == 2
    assert "ClippingGap 5 (units unverified)" in svg
    assert "Extension 2 mm" in svg


def test_dimension_direction_and_placement():
    above = sd.dimension_svg({"Direction": 0, "ArrangeAbove": True, "Number of Points": 3})
    below = sd.dimension_svg({"Direction": 0, "ArrangeAbove": False, "Number of Points": 3})
    assert "X-direction chain, 3 point(s), above" in above
    assert "X-direction chain, 3 point(s), below" in below
    assert 'class="sd-dim" x1="64.0" y1="54.0"' in above
    assert 'class="sd-dim" x1="64.0" y1="134.0"' in below
    assert above.count('class="sd-dim"') == 4


def test_dimension_vertical_chain_uses_y_titles():
    svg = sd.dimension_svg({"Direction": 1, "ArrangeAbove": True, "Number of Points": 2})
    assert "Y-direction chain" in svg


def test_dimension_uses_point_names_when_few_points():
    svg = sd.dimension_svg(
        {"Direction": 0, "ArrangeAbove": True, "Number of Points": 2},
        ["Grid | BottomExtreme-BottomExtreme", "Grid | TopExtreme-TopExtreme"],
    )
    assert "BottomExtreme-BottomExtreme" in svg
    assert "<title>Grid | TopExtreme-TopExtreme</title>" in svg


def test_dimension_falls_back_to_numbers_for_many_points():
    svg = sd.dimension_svg({"Direction": 0, "ArrangeAbove": True, "Number of Points": 6})
    assert ">3<" in svg


def test_hatch_swatch_off_state():
    svg = sd.hatch_swatch_svg({"PatternName": "", "Angle": 0, "Scale": 1})
    assert "none" in svg
    assert "pattern" not in svg


def test_hatch_swatch_uses_angle_and_pattern():
    svg = sd.hatch_swatch_svg({"PatternName": "ANSI31", "Angle": 45, "Scale": 2})
    assert "ANSI31" in svg
    assert 'patternTransform="rotate(-45.00)"' in svg


def test_row_from_form_parses_only_length_columns():
    items = [
        ("f::DetViewSystemAndBox::tok::xDelta", "2'-0\""),
        ("f::DetViewSystemAndBox::tok::zMode", "4"),
        ("f::DetViewLengthClip::tok::MinRemainingLength", "3/4\""),
        ("o::DetViewSystemAndBox::tok::xDelta", "609.6"),
        ("csrf_token", "abc"),
    ]
    row = sd.row_from_form("DetViewSystemAndBox", items)
    assert row == {"xDelta": pytest.approx(609.6), "zMode": "4"}


def test_row_from_form_keeps_unreadable_lengths():
    row = sd.row_from_form("DetViewSystemAndBox", [("f::DetViewSystemAndBox::t::xDelta", "junk")])
    assert row["xDelta"] == "junk"


def test_diagram_dispatch_rejects_unknown_kind():
    with pytest.raises(ValueError):
        sd.diagram("nope", {})


def test_request_diagrams_builds_every_figure():
    request = {
        "row": {"Key": 1, "Scale": 0.125},
        "sysbox": {"row": {"xDelta": 100, "yDelta": 100, "zDeltaFront": 5, "zDeltaRear": 5}},
        "clip": {"row": {"X Clip": 1, "Y Clip": 1}},
        "dims": [{"linear": {"row": {"RunName": "X chain", "Direction": 0, "Number of Points": 2}},
                  "points": ["A", "B"]}],
    }
    out = sd.request_diagrams(request)
    assert "1:8" in out["scale"]
    assert out["viewbox"] and out["clip"]
    assert out["dims"][0]["name"] == "X chain"
    assert "X-direction chain" in out["dims"][0]["svg"]


def test_decorate_tree_adds_diagrams_and_swatches():
    tree = {
        "masters": [{"style": {"requests": [
            {"row": {"Scale": 0.0625}, "dims": []},
            {"missing": 99},
        ]}}],
        "libraries": {
            "DetHatchSettings": [{"row": {"Key": 1, "PatternName": "", "Angle": 0, "Scale": 1}}],
            "DetObjAppearance": [{"row": {"Key": 2, "HatchVisible": 1, "HatchHidden": 1}}],
        },
    }
    sd.decorate_tree(tree)
    requests = tree["masters"][0]["style"]["requests"]
    assert "1:16" in requests[0]["diagrams"]["scale"]
    assert "diagrams" not in requests[1]
    assert "none" in tree["libraries"]["DetObjAppearance"][0]["hatch_visible_svg"]
    overview = tree["masters"][0]["style"]["overview_svg"]
    assert "1:16" in overview


def test_diagram_route_requires_csrf():
    from app import app
    resp = app.test_client().post("/db/SomeDb/drawing-style/diagram",
                                  data={"kind": "scale", "f::DetViewRequest::t::Scale": "0.125"})
    assert resp.status_code == 400


def test_diagram_route_redraws_from_posted_values():
    from app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_csrf"] = "tok"
    resp = client.post(
        "/db/SomeDb/drawing-style/diagram",
        data={
            "csrf_token": "tok",
            "kind": "viewbox",
            "table": "DetViewSystemAndBox",
            "f::DetViewSystemAndBox::t::xDelta": "2'-0\"",
            "f::DetViewSystemAndBox::t::zDeltaFront": "1/8\"",
            "f::DetViewSystemAndBox::t::zMode": "4",
        },
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "X extend 609.6 mm" in body
    assert "3.175 mm" in body
    assert "z mode 4" in body


def test_diagram_route_reports_unknown_kind():
    from app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_csrf"] = "tok"
    resp = client.post("/db/SomeDb/drawing-style/diagram",
                       data={"csrf_token": "tok", "kind": "nope"})
    assert resp.status_code == 200
    assert "unknown diagram" in resp.get_data(as_text=True)


def test_style_overview_lists_views_with_counts():
    svg = sd.style_overview_svg([
        {"name": "5 - MARKS Column - Top", "scale": 0.0208333333333, "rules": 49, "dims": 4},
        {"name": "5 - Column - Section", "scale": 0.125, "rules": 19, "dims": 16},
    ])
    assert "5 - MARKS Column - Top" in svg
    assert "5 - Column - Section" in svg
    assert "1:48 · 1/4\"" in svg
    assert "1:8 · 1 1/2\"" in svg
    assert ">49<" in svg and ">19<" in svg and ">16<" in svg


def test_style_overview_bars_scale_with_paper_width():
    svg = sd.style_overview_svg([
        {"name": "A", "scale": 1 / 48, "rules": 1, "dims": 0},
        {"name": "B", "scale": 1 / 24, "rules": 2, "dims": 0},
    ])
    widths = [float(w) for w in re.findall(r'class="sd-overview-bar" x="[\d.]+" y="[\d.]+" width="([\d.]+)"', svg)]
    assert len(widths) == 2
    assert widths[1] > widths[0]
    assert widths[1] / widths[0] == pytest.approx(2.0, rel=0.05)


def test_style_overview_handles_empty_style():
    svg = sd.style_overview_svg([])
    assert "no view requests" in svg


def test_style_overview_flags_unclean_scales():
    svg = sd.style_overview_svg([{"name": "Odd", "scale": 0.0731, "rules": 0, "dims": 0}])
    assert "scale not a clean 1:N" in svg


def test_style_overview_truncates_long_view_names():
    svg = sd.style_overview_svg([
        {"name": "5 - MARKS Column - Top and Bottom with extra words", "scale": 0.0625, "rules": 3, "dims": 1},
    ])
    assert "5 - MARKS Column - Top and Bo…" in svg
