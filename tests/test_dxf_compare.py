"""DXF hand-edit diff: parser, diff, intent, style map and route (issue #15)."""

import io
import json

from utils import dxf_compare


# --------------------------------------------------------------------------
# Small ASCII DXF fixture builder
# --------------------------------------------------------------------------


def _entity(entity_type, layer, fields=(), handle=None):
    pairs = [(0, entity_type)]
    if handle:
        pairs.append((5, handle))
    pairs.append((8, layer))
    pairs.extend(fields)
    return pairs


def _line(layer, first, second, handle=None, linetype=None):
    fields = [(10, first[0]), (20, first[1]), (11, second[0]), (21, second[1])]
    if linetype:
        fields.insert(0, (6, linetype))
    return _entity("LINE", layer, fields, handle)


def _dimension(layer, definition, first, second, handle=None,
               dimstyle="STANDARD", subtype=0):
    fields = [
        (3, dimstyle), (2, "*D1"), (70, subtype),
        (10, definition[0]), (20, definition[1]),
        (13, first[0]), (23, first[1]),
        (14, second[0]), (24, second[1]),
    ]
    return _entity("DIMENSION", layer, fields, handle)


def _text(layer, point, height, content="MA1", handle=None, rotation=0):
    return _entity("TEXT", layer, [
        (10, point[0]), (20, point[1]), (40, height), (1, content),
        (50, rotation),
    ], handle)


def _circle(layer, center, radius, handle=None):
    return _entity("CIRCLE", layer, [
        (10, center[0]), (20, center[1]), (40, radius),
    ], handle)


def _dxf(entities, layers=None, insunits=4, measurement=1,
         dimstyles=(("STANDARD", 2.5, 3.5), ("AS_STANDARD", 2.5, 3.5))):
    layers = layers or (
        ("AS_CONTOUR", 7), ("AS_HIDDEN", 8), ("AS_CENTER", 6),
        ("AS_DIM", 2), ("AS_TEXT", 4), ("DIM", 3), ("TEXT", 5), ("0", 7),
    )
    pairs = [
        (0, "SECTION"), (2, "HEADER"),
        (9, "$ACADVER"), (1, "AC1032"),
        (9, "$INSUNITS"), (70, insunits),
        (9, "$MEASUREMENT"), (70, measurement),
        (0, "ENDSEC"),
        (0, "SECTION"), (2, "TABLES"),
        (0, "TABLE"), (2, "LAYER"), (70, len(layers)),
    ]
    for name, colour in layers:
        pairs.extend([(0, "LAYER"), (2, name), (70, 0), (62, colour),
                      (6, "CONTINUOUS")])
    pairs.append((0, "ENDTAB"))
    pairs.extend([(0, "TABLE"), (2, "DIMSTYLE"), (70, len(dimstyles))])
    for name, arrow, text_height in dimstyles:
        pairs.extend([(0, "DIMSTYLE"), (2, name), (70, 0), (41, arrow),
                      (140, text_height), (43, 1.0), (44, 1.0),
                      (147, 0.5), (40, 1.0)])
    pairs.append((0, "ENDTAB"))
    pairs.extend([(0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES")])
    for entity in entities:
        pairs.extend(entity)
    pairs.extend([(0, "ENDSEC"), (0, "EOF")])
    return "\n".join(f"{code}\n{value}" for code, value in pairs) + "\n"


def _report(before, after, **kwargs):
    return dxf_compare.build_report(before, after, **kwargs)


# --------------------------------------------------------------------------
# Reading and classification
# --------------------------------------------------------------------------


def test_reads_units_layers_blocks_and_entity_geometry():
    document = dxf_compare.read_dxf(_dxf([
        _line("AS_CONTOUR", (0, 0), (100, 0), handle="A1"),
        _line("AS_CENTER", (50, -10), (50, 10), handle="A2"),
        _dimension("AS_DIM", (50, -20), (0, 0), (100, 0), handle="A3",
                   dimstyle="AS_STANDARD"),
        _dimension("DIM", (50, -40), (0, 0), (100, 0), handle="A4"),
        _text("AS_TEXT", (10, 10), 3.5, handle="A5"),
        _circle("AS_CONTOUR", (0, 0), 10, handle="A6"),
        _line("0", (0, 0), (10, 10), handle="A7"),
        _entity("LINE", "0", [
            (1001, "AS_DETAIL"), (10, 0), (20, 0), (11, 5), (21, 5),
        ], handle="A8"),
    ]))
    assert document["units"] == {"code": 4, "name": "millimetres", "metric": True}
    assert document["acadver"] == "AC1032"
    assert set(document["layers"]) >= {"AS_CONTOUR", "DIM", "0"}
    assert document["dimstyles"]["AS_STANDARD"]["arrow_size"] == 2.5
    assert document["dimstyles"]["AS_STANDARD"]["text_height"] == 3.5

    entities = {entity["handle"]: entity for entity in document["entities"]}
    contour = entities["A1"]
    assert (contour["kind"], contour["origin"]) == ("contour", "generated")
    assert contour["orientation"]["bucket"] == "horizontal"
    assert contour["length"] == 100.0

    axis = entities["A2"]
    assert axis["kind"] == "axis" and axis["origin"] == "generated"

    generated_dimension = entities["A3"]
    assert generated_dimension["kind"] == "dimension"
    assert generated_dimension["origin"] == "generated"
    assert generated_dimension["anchor"] == [50.0, -20.0]
    assert generated_dimension["span"] == 100.0
    assert generated_dimension["dimstyle"] == "AS_STANDARD"
    assert generated_dimension["subtype"] == 0

    hand_dimension = entities["A4"]
    assert hand_dimension["origin"] == "hand"
    assert hand_dimension["origin_basis"] == "plain AutoCAD object on a non-AS layer"

    label = entities["A5"]
    assert label["kind"] == "label" and label["origin"] == "generated"
    assert label["height"] == 3.5

    circle = entities["A6"]
    assert circle["orientation"]["bucket"] == "round"
    assert circle["bbox"]["min"] == [-10.0, -10.0]
    assert circle["bbox"]["max"] == [10.0, 10.0]

    assert entities["A7"]["origin"] == "unknown"
    assert entities["A7"]["origin_basis"] == "no AS marker on layer 0"
    assert entities["A8"]["origin"] == "generated"
    assert entities["A8"]["origin_basis"] == "AS XDATA"


def test_polyline_vertices_are_merged_into_one_entity():
    vertices = [
        (0, "POLYLINE"), (8, "AS_CONTOUR"), (70, 1),
        (0, "VERTEX"), (8, "AS_CONTOUR"), (10, 0), (20, 0),
        (0, "VERTEX"), (8, "AS_CONTOUR"), (10, 100), (20, 0),
        (0, "VERTEX"), (8, "AS_CONTOUR"), (10, 100), (20, 50),
        (0, "VERTEX"), (8, "AS_CONTOUR"), (10, 0), (20, 50),
        (0, "SEQEND"),
    ]
    document = dxf_compare.read_dxf(_dxf([vertices]))
    assert len(document["entities"]) == 1
    polyline = document["entities"][0]
    assert polyline["type"] == "POLYLINE"
    assert polyline["closed"] is True
    assert polyline["points"] == [[0.0, 0.0], [100.0, 0.0],
                                  [100.0, 50.0], [0.0, 50.0]]
    assert polyline["orientation"]["bucket"] == "horizontal"


def test_binary_dxf_is_rejected():
    try:
        dxf_compare.read_dxf(b"AutoCAD Binary DXF\r\n\x1a\x00")
    except dxf_compare.DxfError as exc:
        assert "binary" in str(exc).lower()
    else:
        raise AssertionError("binary DXF should be refused")


def test_short_or_malformed_dxf_is_rejected():
    for source in ("", "0\nSECTION\nnot-a-code\n1\n"):
        try:
            dxf_compare.read_dxf(source)
        except dxf_compare.DxfError:
            continue
        raise AssertionError(f"expected DxfError for {source!r}")


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------


def _outline():
    return [
        _line("AS_CONTOUR", (0, 0), (100, 0)),
        _line("AS_CONTOUR", (0, 10), (100, 10)),
        _line("AS_CONTOUR", (0, 20), (100, 20)),
    ]


def test_diff_reports_added_removed_moved_changed_and_unchanged():
    before = _dxf(_outline() + [_text("TEXT", (0, 80), 2.5)])
    after = _dxf([
        _line("AS_CONTOUR", (0, 0), (100, 0)),          # unchanged
        _line("AS_CONTOUR", (0, 30), (100, 30)),        # moved from y=10
        _line("AS_CONTOUR", (0, 200), (100, 200)),      # added
        _text("TEXT", (0, 80), 5.0),                    # changed height
    ])
    diff = dxf_compare.diff_documents(
        dxf_compare.read_dxf(before), dxf_compare.read_dxf(after))
    assert diff["counts"] == {
        "unchanged": 1, "changed": 1, "moved": 1, "added": 1, "removed": 1}
    moved = diff["moved"][0]
    assert moved["after"]["anchor"][1] == 30.0
    assert diff["added"][0]["anchor"][1] == 200.0
    # two identical horizontal lines moved past each other: which one is the
    # source is not recoverable, only that one line moved and one disappeared.
    assert diff["removed"][0]["anchor"][1] in {10.0, 20.0}
    changed = diff["changed"][0]
    assert [change["field"] for change in changed["changes"]] == ["text height"]


def test_dimension_values_are_not_reported_as_changes():
    before = _dxf([
        _line("AS_CONTOUR", (0, 0), (100, 0)),
        _dimension("AS_DIM", (50, -20), (0, 0), (100, 0)),
    ])
    after = _dxf([
        _line("AS_CONTOUR", (0, 0), (100, 0)),
        # same dimension line, different text override: value is ignored
        _entity("DIMENSION", "AS_DIM", [
            (3, "STANDARD"), (2, "*D1"), (70, 0),
            (10, 50), (20, -20), (13, 0), (23, 0), (14, 100), (24, 0),
            (1, "<> TYP"),
        ]),
    ])
    report = _report(before, after)
    assert report["summary"]["added"] == 0
    assert report["summary"]["removed"] == 0
    assert report["summary"]["changed"] == 0


# --------------------------------------------------------------------------
# Intent and grouping
# --------------------------------------------------------------------------


def _railing_before():
    return _dxf([
        _line("AS_CONTOUR", (0, 0), (1000, 0)),
        _line("AS_CONTOUR", (0, 0), (1000, 500)),
        _line("AS_CONTOUR", (0, 0), (0, 500)),
        _line("AS_CONTOUR", (1000, 0), (1000, 500)),
        _dimension("AS_DIM", (500, -100), (0, 0), (1000, 0),
                   dimstyle="AS_STANDARD"),
    ])


def _railing_after():
    return _dxf([
        _line("AS_CONTOUR", (0, 0), (1000, 0)),
        _line("AS_CONTOUR", (0, 0), (1000, 500)),
        _line("AS_CONTOUR", (0, 0), (0, 500)),
        _line("AS_CONTOUR", (1000, 0), (1000, 500)),
        _dimension("AS_DIM", (500, -100), (0, 0), (1000, 0),
                   dimstyle="AS_STANDARD"),
        _dimension("DIM", (150, -300), (0, 0), (300, 0)),
        _dimension("DIM", (500, -300), (300, 0), (700, 0)),
        _dimension("DIM", (850, -300), (700, 0), (1000, 0)),
    ])


def test_added_dimension_chain_is_grouped_and_explained():
    report = _report(_railing_before(), _railing_after())
    dimension_edits = [edit for edit in report["edits"]
                       if edit["kind"] == "dimension" and edit["action"] == "added"]
    assert len(dimension_edits) == 1
    edit = dimension_edits[0]
    assert edit["count"] == 3
    assert edit["origin"] == "hand"
    assert edit["intent"]["what"] == "dimension chain of 3 segments"
    assert edit["intent"]["side"]["text"] == "below the view"
    assert "runs horizontally" in edit["intent"]["direction"]["text"]
    assert "the assembly extreme" in edit["intent"]["feature"]["labels"]
    assert "a generated contour on layer AS_CONTOUR" in edit["intent"]["feature"]["labels"]
    assert "below the view" in edit["intent"]["summary"]
    assert edit["style"]["can_style"] is True
    assert edit["style"]["category"] == "dimension strategy"
    assert "DetViewDimStrategyItems" in edit["style"]["tables"]
    assert "Add a new request" in edit["style"]["suggestion"]


def test_label_text_height_is_reported_as_not_a_style_change():
    before = _dxf([_text("TEXT", (0, 0), 2.5)])
    after = _dxf([_text("TEXT", (0, 0), 5.0)])
    report = _report(before, after)
    edit = report["edits"][0]
    assert edit["kind"] == "label" and edit["action"] == "changed"
    assert edit["style"]["can_style"] is False
    assert edit["style"]["category"] == "drawing defaults"
    assert report["not_style"][0]["aspect"] == "text height"
    assert "drawing defaults" in report["not_style"][0]["reason"]
    assert "drawing default" in edit["style"]["suggestion"]


def test_dimension_style_change_is_reported_as_not_a_style_change():
    before = _dxf([
        _line("AS_CONTOUR", (0, 0), (100, 0)),
        _dimension("AS_DIM", (50, -20), (0, 0), (100, 0),
                   dimstyle="AS_STANDARD"),
    ])
    after = _dxf([
        _line("AS_CONTOUR", (0, 0), (100, 0)),
        _dimension("AS_DIM", (50, -20), (0, 0), (100, 0),
                   dimstyle="STANDARD"),
    ])
    report = _report(before, after)
    edit = report["edits"][0]
    assert edit["kind"] == "dimension" and edit["action"] == "changed"
    assert edit["style"]["can_style"] is False
    assert report["not_style"][0]["aspect"] == "dimension style"


def test_dimstyle_definition_change_is_a_drawing_default():
    entities = [
        _line("AS_CONTOUR", (0, 0), (100, 0)),
        _dimension("AS_DIM", (50, -20), (0, 0), (100, 0),
                   dimstyle="AS_STANDARD"),
    ]
    before = _dxf(entities, dimstyles=(("AS_STANDARD", 2.5, 3.5),))
    after = _dxf(entities, dimstyles=(("AS_STANDARD", 4.0, 3.5),))
    report = _report(before, after)
    assert report["summary"]["edits"] == 0
    assert report["drawing_defaults"][0]["field"] == "arrow size"
    assert report["drawing_defaults"][0]["before"] == 2.5
    assert report["drawing_defaults"][0]["after"] == 4.0
    assert any(item["edit"] is None and item["aspect"].endswith("arrow size")
               for item in report["not_style"])


def test_layer_colour_change_is_a_drawing_default():
    entities = [_line("AS_CONTOUR", (0, 0), (100, 0))]
    before = _dxf(entities, layers=(("AS_CONTOUR", 7),))
    after = _dxf(entities, layers=(("AS_CONTOUR", 1),))
    report = _report(before, after)
    assert report["summary"]["edits"] == 0
    assert report["drawing_defaults"][0]["field"] == "colour"
    assert report["drawing_defaults"][0]["before"] == 7
    assert report["drawing_defaults"][0]["after"] == 1


def test_colour_only_change_is_not_a_style_change():
    before = _dxf([_line("AS_CONTOUR", (0, 0), (100, 0))])
    after = _dxf([_entity("LINE", "AS_CONTOUR", [
        (62, 1), (10, 0), (20, 0), (11, 100), (21, 0)])])
    report = _report(before, after)
    edit = report["edits"][0]
    assert edit["style"]["can_style"] is False
    assert edit["style"]["category"] == "drawing defaults"


def test_exploded_dimension_on_a_dimension_layer_maps_to_the_strategy():
    before = _dxf([_line("AS_DIM", (0, -10), (100, -10))])
    after = _dxf([
        _line("AS_DIM", (0, -10), (100, -10)),
        _line("DIM", (0, -30), (100, -30)),
    ])
    report = _report(before, after)
    edit = report["edits"][0]
    assert edit["kind"] == "dimension geometry"
    assert edit["origin"] == "hand"
    assert edit["style"]["category"] == "dimension strategy"
    assert "DetViewDimStrategyItems" in edit["style"]["tables"]


def test_title_frame_lines_are_not_a_style_change():
    before = _dxf([
        _line("AS_CONTOUR", (0, 0), (100, 0)),
        _line("FRAME", (0, -100), (100, -100)),
    ])
    after = _dxf([
        _line("AS_CONTOUR", (0, 0), (100, 0)),
    ])
    report = _report(before, after)
    edit = report["edits"][0]
    assert edit["kind"] == "frame"
    assert edit["style"]["can_style"] is False
    assert edit["style"]["category"] == "drawing defaults"
    assert report["not_style"][0]["aspect"] == "title frame"


# --------------------------------------------------------------------------
# Scale
# --------------------------------------------------------------------------


def _scaled(point, center=(125.0, 50.0), factor=0.5):
    return [center[0] + (point[0] - center[0]) * factor,
            center[1] + (point[1] - center[1]) * factor]


def _two_rectangles(transform=lambda point: point):
    def p(point):
        return transform(point)

    return [
        _line("AS_CONTOUR", p((0, 0)), p((100, 0))),
        _line("AS_CONTOUR", p((100, 0)), p((100, 100))),
        _line("AS_CONTOUR", p((100, 100)), p((0, 100))),
        _line("AS_CONTOUR", p((0, 100)), p((0, 0))),
        _line("AS_HIDDEN", p((200, 0)), p((250, 0))),
        _line("AS_HIDDEN", p((250, 0)), p((250, 50))),
        _line("AS_HIDDEN", p((250, 50)), p((200, 50))),
        _line("AS_HIDDEN", p((200, 50)), p((200, 0))),
    ]


STYLE_MODEL = {
    "masters": [{
        "row": {"RunName": "Railing"},
        "style": {
            "row": {"RunName": "Marks 6 - Railing"},
            "requests": [{
                "short_name": "Front",
                "scale_denom": 8,
                "scale_label": '1:8 (1 1/2" = 1\'-0")',
                "row": {"Key": 10},
            }],
        },
    }],
}


def test_uniform_size_change_is_detected_and_normalised_out_of_the_diff():
    report = _report(_dxf(_two_rectangles()), _dxf(_two_rectangles(_scaled)),
                     style_model=STYLE_MODEL)
    assert report["scale"]["changed"] is True
    assert abs(report["scale"]["factor"] - 0.5) < 1e-9
    assert report["scale"]["layers_compared"] == 2
    assert report["scale"]["consistent"] == 1.0
    assert report["summary"]["added"] == 0
    assert report["summary"]["removed"] == 0
    assert report["summary"]["moved"] == 0
    assert report["summary"]["changed"] == 0
    proposal = report["scale"]["proposals"][0]
    assert proposal["old_scale"] == 0.125
    assert proposal["new_label"] == "1:16"


def test_different_units_stop_the_scale_comparison():
    report = _report(_dxf(_two_rectangles(), insunits=4),
                     _dxf(_two_rectangles(_scaled), insunits=1))
    assert report["scale"]["changed"] is None
    assert "different drawing units" in report["scale"]["reason"]
    assert any("different units" in warning for warning in report["warnings"])


def test_same_size_drawings_do_not_report_a_scale_change():
    report = _report(_dxf(_two_rectangles()), _dxf(_two_rectangles()))
    assert report["scale"]["changed"] is False
    assert report["scale"]["factor"] is None


# --------------------------------------------------------------------------
# Style index and matching
# --------------------------------------------------------------------------


def _explanation():
    return {
        "name": "X view - Railing Posts",
        "summary": ("Measures the system line of the posts. The chain runs along X, "
                    "placed below the view."),
        "direction": {"text": "runs along X"},
        "placement": [{"text": "Placed below the view."}],
        "points": [{"sentence": "the system line of the posts"},
                   {"sentence": "the assembly extreme of the assembly"}],
        "dim_type": {"value": 2, "text": "chained (relative) linear dimension (type #2)"},
    }


def test_flatten_dimension_requests_indexes_the_style_tree():
    model = {
        "masters": [{
            "row": {"RunName": "Railing"},
            "style": {
                "row": {"RunName": "Marks 6 - Railing"},
                "requests": [{
                    "short_name": "Front",
                    "row": {"Key": 10},
                    "dims": [{
                        "row": {"Key": 30, "Order": 1},
                        "linear": {"row": {"Key": 40}},
                        "explain": _explanation(),
                        "points": [],
                        "point_keys": [],
                    }],
                }],
            },
        }],
    }
    index = dxf_compare.flatten_dimension_requests(model)
    assert len(index) == 1
    entry = index[0]
    assert entry["style"] == "Marks 6 - Railing"
    assert entry["view"] == "Front"
    assert entry["name"] == "X view - Railing Posts"
    assert entry["row"]["Key"] == 30
    assert entry["linear"]["Key"] == 40
    assert entry["type"] == 2
    assert "posts" in entry["tokens"]
    assert "extreme" in entry["tokens"]


def test_search_requests_prefers_direction_side_and_type():
    index = [
        {
            "style": "S", "view": "Front", "name": "X view - Railing Posts",
            "summary": "Measures the post system lines, below the view.",
            "direction": "runs along X",
            "placement": ["Placed below the view."],
            "type": 2,
            "type_text": "chained (type #2)",
            "tokens": {"railing", "posts", "system", "line", "assembly",
                       "extreme", "below"},
            "row": {"Key": 30}, "linear": {"Key": 40},
        },
        {
            "style": "S", "view": "Side", "name": "Y view - Rail heights",
            "summary": "Measures the rail heights, above the view.",
            "direction": "runs along X",
            "placement": ["Placed above the view."],
            "type": 1,
            "type_text": "dimension type #1",
            "tokens": {"rail", "heights", "above", "extreme"},
            "row": {"Key": 31}, "linear": {"Key": 41},
        },
    ]
    intent = {
        "direction": {"text": "runs horizontally"},
        "side": {"text": "below the view"},
        "feature": {"labels": ["the assembly extreme"]},
        "what": "dimension chain of 3 segments",
    }
    matches = dxf_compare.search_requests(index, intent)
    assert matches[0]["name"] == "X view - Railing Posts"
    assert matches[0]["score"] > matches[1]["score"]


def _style_graph(two_styles=True):
    rows = {
        "DetailStyle": [
            {"Key": 1, "RunName": "Railing", "Request1": 10},
        ] + ([{"Key": 2, "RunName": "Stairs", "Request1": 10}] if two_styles else []),
        "DetailMasterTable": [
            {"RunName": "Railing master", "StyleKey": 1},
        ] + ([{"RunName": "Stairs master", "StyleKey": 2}] if two_styles else []),
        "DetViewRequest": [{"Key": 10, "RunName": "Front", "DimStrategy": 20}],
        "DetViewDimStrategyNew": [{"Key": 20, "Items": 20}],
        "DetViewDimStrategyItems": [
            {"Key": 20, "Order": 1, "RequestLinear": 40},
        ],
        "DetViewDimRequestLinear": [
            {"Key": 40, "RunName": "X view - Railing Posts"},
        ],
    }
    return {
        "rows_by_table": rows,
        "pk_by_table": {table: ["Key"] for table in rows},
        "tables_present": set(rows),
    }


def test_map_edit_flags_a_sub_style_shared_by_two_styles():
    index = [{
        "style": "Railing", "view": "Front", "name": "X view - Railing Posts",
        "summary": "Measures the post system lines, below the view.",
        "direction": "runs along X",
        "placement": ["Placed below the view."],
        "type": 2, "type_text": "chained (type #2)",
        "tokens": {"railing", "posts", "system", "below", "extreme"},
        "row": {"Key": 20}, "linear": {"Key": 40},
    }]
    edit = {
        "kind": "dimension", "action": "changed",
        "intent": {
            "direction": {"text": "runs horizontally"},
            "side": {"text": "below the view"},
            "feature": {"labels": ["the assembly extreme"]},
            "what": "dimension chain of 3 segments",
        },
        "changes": [{"field": "layer", "from": "DIM", "to": "AS_DIM",
                     "style_owned": True}],
    }
    mapped = dxf_compare.map_edit(edit, request_index=index,
                                  style_graph=_style_graph(two_styles=True))
    assert mapped["matches"][0]["shared_with"]
    assert mapped["shared"][0]["styles"][0]["name"] == "Railing"
    assert "row" not in mapped["matches"][0]


def test_report_with_style_matches_is_json_serialisable():
    model = {
        "masters": [{
            "row": {"RunName": "Railing"},
            "style": {
                "row": {"RunName": "Marks 6 - Railing"},
                "requests": [{
                    "short_name": "Front",
                    "row": {"Key": 10},
                    "dims": [{
                        "row": {"Key": 20, "Order": 1},
                        "linear": {"row": {"Key": 40}},
                        "explain": _explanation(),
                        "points": [],
                        "point_keys": [],
                    }],
                }],
            },
        }],
    }
    report = _report(_railing_before(), _railing_after(), style_model=model)
    dimension_edits = [edit for edit in report["edits"]
                       if edit["kind"] == "dimension" and edit["action"] == "added"]
    assert dimension_edits
    assert dimension_edits[0]["style"]["matches"]
    match = dimension_edits[0]["style"]["matches"][0]
    assert "row" not in match and "linear" not in match
    point_matches = dimension_edits[0]["style"]["point_matches"]
    assert point_matches
    assert any("extreme" in (point["sentence"] or "").lower()
               for point in point_matches)
    json.dumps(report)


def test_request_library_returns_nothing_when_the_database_is_unavailable(monkeypatch):
    def unavailable(database):
        raise RuntimeError("container is stopped")

    monkeypatch.setattr("utils.db.list_tables", unavailable)
    assert dxf_compare.load_request_library("Nope") == []


# --------------------------------------------------------------------------
# Report and route
# --------------------------------------------------------------------------


def test_report_is_json_serialisable():
    report = _report(_railing_before(), _railing_after())
    payload = json.dumps(report)
    assert "dimension chain" in payload
    assert "limitations" in report


def test_detail_diff_route_renders_and_returns_json(monkeypatch):
    from app import app

    monkeypatch.setattr("utils.db.list_databases", lambda: [])
    monkeypatch.setattr("utils.docker_ops.container_is_running", lambda: True)
    client = app.test_client()
    assert client.get("/detail-diff").status_code == 200

    client.get("/detail-diff")
    with client.session_transaction() as session:
        token = session["_csrf"]

    def post(before, after, **extra):
        data = {
            "csrf_token": token,
            "before": (io.BytesIO(before.encode()), "before.dxf"),
            "after": (io.BytesIO(after.encode()), "after.dxf"),
        }
        data.update(extra)
        return client.post("/detail-diff", data=data,
                           content_type="multipart/form-data")

    page = post(_railing_before(), _railing_after())
    assert page.status_code == 200
    assert b"Detail diff" in page.data
    assert b"dimension chain of 3 segments" in page.data

    payload = post(_railing_before(), _railing_after(), format="json")
    assert payload.status_code == 200
    body = payload.get_json()
    assert body["summary"]["edits"] >= 1
    assert body["edits"][0]["intent"]["summary"]


def test_detail_diff_route_renders_style_matches(monkeypatch):
    from app import app

    model = {
        "masters": [{
            "row": {"RunName": "Railing"},
            "style": {
                "row": {"RunName": "Marks 6 - Railing"},
                "requests": [{
                    "short_name": "Front",
                    "row": {"Key": 10},
                    "dims": [{
                        "row": {"Key": 20, "Order": 1},
                        "linear": {"row": {"Key": 40}},
                        "explain": _explanation(),
                        "points": [],
                        "point_keys": [],
                    }],
                }],
            },
        }],
    }
    monkeypatch.setattr("utils.db.list_databases", lambda: ["Styles"])
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "drawing style")
    monkeypatch.setattr("utils.docker_ops.container_is_running", lambda: True)
    monkeypatch.setattr("utils.drawing_styles.style_tree", lambda database: model)
    monkeypatch.setattr("utils.dxf_compare.load_request_library", lambda database: [])
    monkeypatch.setattr("utils.style_usage.load_graph",
                        lambda database: _style_graph(two_styles=False))
    client = app.test_client()
    client.get("/detail-diff")
    with client.session_transaction() as session:
        token = session["_csrf"]
    response = client.post("/detail-diff", data={
        "csrf_token": token,
        "style_db": "Styles",
        "before": (io.BytesIO(_railing_before().encode()), "before.dxf"),
        "after": (io.BytesIO(_railing_after().encode()), "after.dxf"),
    }, content_type="multipart/form-data")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "style can do this" in body
    assert "Reusable point rules" in body
    assert "X view - Railing Posts" in body


def test_detail_diff_route_reports_bad_uploads(monkeypatch):
    from app import app

    monkeypatch.setattr("utils.db.list_databases", lambda: [])
    monkeypatch.setattr("utils.docker_ops.container_is_running", lambda: True)
    client = app.test_client()
    client.get("/detail-diff")
    with client.session_transaction() as session:
        token = session["_csrf"]

    missing = client.post("/detail-diff", data={"csrf_token": token})
    assert missing.status_code == 200
    assert b"Choose a before DXF and an after DXF" in missing.data

    wrong_type = client.post("/detail-diff", data={
        "csrf_token": token,
        "before": (io.BytesIO(b"x"), "before.txt"),
        "after": (io.BytesIO(b"x"), "after.dxf"),
    }, content_type="multipart/form-data")
    assert wrong_type.status_code == 200
    assert b"is not a .dxf file" in wrong_type.data

    binary = client.post("/detail-diff", data={
        "csrf_token": token,
        "before": (io.BytesIO(b"AutoCAD Binary DXF\r\n\x1a\x00"), "before.dxf"),
        "after": (io.BytesIO(_railing_after().encode()), "after.dxf"),
    }, content_type="multipart/form-data")
    assert binary.status_code == 200
    assert b"binary DXF" in binary.data


def test_detail_diff_route_requires_csrf():
    from app import app

    response = app.test_client().post("/detail-diff", data={})
    assert response.status_code == 400
