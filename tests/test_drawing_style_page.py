"""The drawing-style editor renders as a menu of panes (style, each view's
setup / rules / dimensions, libraries, help) and every dimension chain gets a
plain-language card. Rendered from a synthetic tree; no SQL Server needed."""

from collections import defaultdict
import re

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


def _tree(view_keys=(22001,)):
    """One style whose views all alias representation map 900 and dimension
    strategy 300, the shape that used to emit duplicate element ids."""
    requests = []
    for view_key in view_keys:
        dims = []
        for order, (key, name, above) in enumerate([(400, "Mp X - Extreme GTA", True),
                                                    (401, "Mp X - Holes GBA", True)]):
            dims.append({
                "row": {"Key": 300, "Order": order, "RequestLinear": key},
                "token": f"item-{order}",
                "linear": {"row": _linear(key, name, above), "token": f"lin-{key}"},
                "points": ["Holes - All", "Main Part - Extreme as reference"],
                "point_keys": [500, 501],
                "point_rows": [{"row": POINTS[500], "token": "pt-500"},
                               {"row": POINTS[501], "token": "pt-501"}],
            })
        for d, e in zip(dims, dim_explain.explain_strategy(dims, POINTS, {70: "Holes"})):
            d["explain"] = e
        requests.append({
            "row": {"Key": view_key, "RunName": "Elevation" if view_key == 22001 else f"View {view_key}",
                    "Scale": 0.0625, "ObjReprMap": 900, "DimStrategy": 300},
            "token": "req-tok" if view_key == 22001 else f"req-tok-{view_key}",
            "scale_label": '3/4" = 1\'-0"', "scale_denom": 16,
            "sysbox": None, "clip": None,
            "repr_map": {"row": {"Key": 900, "RunName": "Elevation map"}, "token": "map-tok"},
            "repr_items": [],
            "dim_strategy": {"row": {"Key": 300, "RunName": "Beam elevation"}, "token": "ds-tok"},
            "dims": dims,
        })
    tree = {
        "masters": [{
            "row": {"Key": 1, "RunName": "3 - Elevation", "BaseCategory": 1, "SubCategory": 2},
            "token": "m-tok",
            "style": {"row": {"Key": 10, "RunName": "Elevation"}, "token": "s-tok",
                      "title_preview": None, "cut_title_preview": None, "requests": requests},
        }],
        "libraries": {},
        "qset_items": {},
    }
    return style_diagrams.decorate_tree(tree)


def _render(tree=None):
    from app import app
    options = defaultdict(lambda: defaultdict(list))
    with app.test_request_context("/"):
        return render_template(
            "drawing_style.html", database="Demo", tree=tree or _tree(), options=options,
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
    # Rule blocks are scoped to their view (one map can serve several views);
    # old saves still land on #req-<view>, and both sit inside a pane.
    assert 'id="rules-22001-900"' in html
    assert 'id="req-22001"' in html
    assert 'id="lib"' in html


def test_a_shared_representation_map_renders_once_per_view():
    html = _render(_tree(view_keys=(22001, 22002)))
    assert 'id="repr-22001-900"' in html and 'id="repr-22002-900"' in html
    assert 'id="rules-22001-900"' in html and 'id="rules-22002-900"' in html
    # htmx must not address a shared map by id: it swaps the block it sits in.
    assert 'hx-target="#repr-' not in html
    assert 'hx-target="closest .repr-block"' in html
    # Each block carries its own uid back to the server.
    assert 'name="uid" value="22001-900"' in html
    assert 'name="uid" value="22002-900"' in html


def test_two_views_sharing_sub_styles_emit_no_duplicate_ids():
    html = _render(_tree(view_keys=(22001, 22002)))
    ids = re.findall(r'id="([^"]+)"', html)
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    assert duplicated == []


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


def test_chain_card_numbers_use_the_dimension_plan_colours():
    """Card #n must be drawn in the colour of lane #n in the plan."""
    html = _render()
    assert 'class="dx-num" style="background:#0d6efd"' in html   # chain 1
    assert 'class="dx-num" style="background:#198754"' in html   # chain 2
    # A long strategy keeps cycling rather than running out of colours.
    many = _tree()
    for i in range(3, 9):
        cloned = dict(many["masters"][0]["style"]["requests"][0]["dims"][0])
        many["masters"][0]["style"]["requests"][0]["dims"].append(cloned)
    html_many = _render(many)
    assert 'class="dx-num" style="background:#0d6efd"' in html_many  # #7 wraps to blue


def _tree_with_arrangement():
    tree = _tree()
    tree["masters"][0]["style"]["row"]["ViewArrangeStrategy"] = 9001
    tree["masters"][0]["style"]["arrange"] = {
        "row": {"Key": 9001, "RunName": "Top or bottom - 1/4 in", "ViewDistance": 6.35,
                "ArrangeCutsInChains": True},
        "token": "arr-tok",
    }
    return tree


def test_placement_exposes_the_arrangement_strategy_and_its_fields():
    html = _render(_tree_with_arrangement())
    assert "Placement &mdash; where the views and titles go" in html or "Placement — where the views" in html
    # The style points at a shared arrangement strategy; its own fields are editable.
    assert 'name="f::DetailStyle::s-tok::ViewArrangeStrategy"' in html
    assert 'name="f::DetViewArrangeStrategy::arr-tok::ViewDistance"' in html
    assert 'name="f::DetViewArrangeStrategy::arr-tok::ArrangeCutsInChains"' in html
    assert "shared sub-style" in html


def test_placement_lists_every_style_placement_switch():
    html = _render(_tree_with_arrangement())
    for column in ("DetailOrientation", "ObjectSelectionStrategy", "ObjectPosition",
                   "TitlePosition", "CutViewTitlePosition", "FrameAppearance",
                   "AutomaticClipping"):
        assert f"::s-tok::{column}" in html, column


def test_placement_explains_that_positions_are_computed_not_stored():
    html = _render(_tree_with_arrangement())
    assert "not the positions themselves" in html
    assert "computes the layout when it builds the drawing" in html


def test_missing_arrangement_strategy_is_reported_not_invented():
    tree = _tree()
    tree["masters"][0]["style"]["row"]["ViewArrangeStrategy"] = 4242
    tree["masters"][0]["style"]["arrange"] = None
    html = _render(tree)
    assert "arrangement strategy #4242, which is not in this file" in html


def test_view_pane_shows_its_placement_numbers():
    html = _render()
    for column in ("ArrangeDir", "CompassLocation", "CompassLocationInOverviews"):
        assert f"::req-tok::{column}" in html, column
    assert "Placement in this view" in html
