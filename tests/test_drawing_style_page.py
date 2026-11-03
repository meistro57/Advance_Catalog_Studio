"""The drawing-style editor renders as a menu of panes (style, each view's
setup / rules / dimensions, libraries, help) and every dimension chain gets a
plain-language card. Rendered from a synthetic tree; no SQL Server needed."""

from collections import defaultdict

from flask import render_template

from utils import dim_explain, style_diagrams


def _linear(key, name, above=True, direction=0):
    row = {"Key": key, "RunName": name, "Direction": direction, "ArrangeAbove": above,
           "ArrangeGlobally": True, "OneChainPerObjectInPoints1": False,
           "GroupRelatedDimensions": False, "AllowCombine": True,
           "AutomaticallySeparate": False, "Group": 1, "LabelContents": "",
           "Number of Points": 2, "Point1": 500, "Point2": 501}
    for i in range(3, 16):
        row[f"Point{i}"] = 0
    return row


POINTS = {
    500: {"Key": 500, "RunName": "Holes - All", "Objects": 70},
    501: {"Key": 501, "RunName": "Main Part - Extreme as reference", "Objects": 0},
}


def _tree():
    dims = []
    for order, (key, name, above) in enumerate([(400, "Mp X - Extreme GTA", True),
                                                (401, "Mp X - Holes GBA", True)]):
        dims.append({
            "row": {"Key": 300, "Order": order, "RequestLinear": key},
            "token": f"item-{order}",
            "linear": {"row": _linear(key, name, above), "token": f"lin-{key}"},
            "points": ["Holes - All", "Main Part - Extreme as reference"],
            "point_keys": [500, 501],
            "point_rows": [{"row": POINTS[500], "token": "pt-500"}, {"row": POINTS[501], "token": "pt-501"}],
        })
    for d, e in zip(dims, dim_explain.explain_strategy(dims, POINTS, {70: "Holes"})):
        d["explain"] = e
    request = {
        "row": {"Key": 22001, "RunName": "Elevation", "Scale": 0.0625, "ObjReprMap": 900, "DimStrategy": 300},
        "token": "req-tok", "scale_label": '3/4" = 1\'-0"', "scale_denom": 16,
        "sysbox": None, "clip": None,
        "repr_map": {"row": {"Key": 900, "RunName": "Elevation map"}, "token": "map-tok"},
        "repr_items": [],
        "dim_strategy": {"row": {"Key": 300, "RunName": "Beam elevation"}, "token": "ds-tok"},
        "dims": dims,
    }
    tree = {
        "masters": [{
            "row": {"Key": 1, "RunName": "3 - Elevation", "BaseCategory": 1, "SubCategory": 2},
            "token": "m-tok",
            "style": {"row": {"Key": 10, "RunName": "Elevation"}, "token": "s-tok",
                      "title_preview": None, "cut_title_preview": None, "requests": [request]},
        }],
        "libraries": {},
        "qset_items": {},
    }
    return style_diagrams.decorate_tree(tree)


def _render():
    from app import app
    options = defaultdict(lambda: defaultdict(list))
    with app.test_request_context("/"):
        return render_template(
            "drawing_style.html", database="Demo", tree=_tree(), options=options,
            report={"dangling": [], "notes": [], "checked": 5}, meta={},
            scale_choices=[(0.0625, '3/4" = 1\'-0"')], length_cols={}, ftin=lambda v: None,
            scale_denom=lambda v: 16, label_tokens=["Name"], label_escapes=["c"],
            label_commands=["#Newline"],
        )


def test_page_is_split_into_menu_panes():
    html = _render()
    for pane in ("pane-style-1", "pane-view-22001", "pane-rules-22001", "pane-dims-22001",
                 "pane-lib-labels", "pane-lib-strat", "pane-lib-app", "pane-lib-sets", "pane-guide-dims"):
        assert f'id="{pane}"' in html, pane
        assert f'data-pane="{pane}"' in html, pane
    assert html.count('class="ds-pane"') == 9


def test_old_anchors_still_exist_for_redirects():
    html = _render()
    # rule actions redirect to #rules-<map>; old saves to #req-<view>; both land inside a pane
    assert 'id="rules-900"' in html
    assert 'id="req-22001"' in html
    assert 'id="lib"' in html


def test_every_chain_gets_a_plain_language_card():
    html = _render()
    assert html.count('class="dx-chain"') == 2
    assert "Measures the hole centers. The chain runs along X, placed above the view." in html
    assert "The overall size of the main part" in html  # reference point, capitalised in the card
    assert 'class="badge bg-light text-dark border ms-1 dx-code"' in html and ">GTA<" in html


def test_name_code_mismatch_shows_a_warning():
    html = _render()
    # "GBA" says Bottom, but the stored switch says above
    assert "GBA disagrees with the stored switches: B (ArrangeAbove)" in html


def test_each_chain_figure_reads_only_its_own_inputs():
    html = _render()
    assert 'data-block="#chain-22001-1"' in html and 'data-block="#chain-22001-2"' in html
    assert 'id="chain-22001-1"' in html


def test_edit_links_return_to_the_dimensions_pane():
    html = _render()
    assert "/db/Demo/DetViewDimPointSelection/pt-500/edit?return_to=/db/Demo/drawing-style%23pane-dims-22001" in html
    assert "/db/Demo/DetViewDimRequestLinear/lin-400/edit?return_to=/db/Demo/drawing-style%23pane-dims-22001" in html


def test_menu_flags_views_with_dimension_warnings():
    html = _render()
    assert 'title="chains with warnings">&#9888; 1<' in html


def test_save_still_posts_one_form_for_all_panes():
    html = _render()
    assert html.count('id="styleForm"') == 1
    start, end = html.index('id="styleForm"'), html.index("</form>", html.index('id="saveBar"'))
    form = html[start:end]
    assert 'id="pane-dims-22001"' in form and 'id="pane-lib-sets"' in form
