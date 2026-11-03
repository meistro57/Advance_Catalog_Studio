"""Unit tests for the read-only style usage / orphan analyzer.

The fixtures are the observed containment chain in miniature (one or two
styles), so the walk, the orphan scan and the truncation guards are testable
without a database.
"""

from utils import style_usage as su


# --- fixtures ---------------------------------------------------------------

PK = {
    "DetailStyle": ["Key"],
    "DetailMasterTable": ["Key", "BaseCategory", "SubCategory", "StyleKey"],
    "DetViewRequest": ["Key"],
    "DetViewRequestCategories": ["Key"],
    "DetObjReprMapsNew": ["Key"],
    "DetObjReprMapItems": ["Key", "Order"],
    "DetObjAppearance": ["Key"],
    "DetObjAnnotationStrategy": ["Key"],
    "DetAnnotationType": ["Key"],
    "DetViewDimStrategyNew": ["Key"],
    "DetViewDimStrategyItems": ["Key", "Order"],
    "DetViewDimRequestLinear": ["Key"],
    "DetViewDimPointSelection": ["Key"],
    "DetObjQualifierSet": ["Key"],
    "Linetypes": ["Key"],
}


def style(key=1, name="Style A", request1=10):
    return {"Key": key, "RunName": name, "Request1": request1,
            "Request2": 0, "Request3": 0, "Request4": 0,
            "ViewArrangeStrategy": 0, "Request5": 0, "OwnerText": "DSC"}


def master(key=1, style_key=1, name="Style A", base=3, sub=9):
    return {"Key": key, "StyleKey": style_key, "RunName": name,
            "BaseCategory": base, "SubCategory": sub, "OwnerText": "DSC"}


def request(key=10, name="View 1", map_key=100, dim_key=300):
    return {"Key": key, "RunName": name, "ObjReprMap": map_key,
            "DimStrategy": dim_key, "SystemAndBox": 0, "LengthclipXY": 0}


def rmap(key=100, name="Map 1"):
    return {"Key": key, "RunName": name, "Items": key}


def ritem(map_key=100, order=0, appearance=1000, strategy=5000, qualifier=0,
          linetype=0):
    return {"Key": map_key, "Order": order, "Appearance": appearance,
            "AnnotationStrategy": strategy, "ObjQualifier": qualifier,
            "LineType": linetype, "Description": f"rule {order}"}


def appearance(key=1000, name="Visible"):
    return {"Key": key, "RunName": name, "HatchVisible": 0, "HatchHidden": 0,
            "GridReference": 0}


def annot_strategy(key=5000, name="Mark & Name", annot_type=9000):
    return {"Key": key, "RunName": name, "AnnotationType": annot_type,
            "ArrangerStrategy": 0, "Group": 0}


def annot_type(key=9000, name="Mark", content="%Name"):
    return {"Key": key, "RunName": name, "Content": content}


def dim_strategy(key=300, name="Chain"):
    return {"Key": key, "RunName": name, "Items": key}


def dim_item(strategy_key=300, order=0, linear=400):
    return {"Key": strategy_key, "Order": order, "RequestLinear": linear,
            "Description": f"dim {order}"}


def dim_linear(key=400, name="X chain", points=(500,)):
    row = {"Key": key, "RunName": name}
    for i in range(1, 16):
        row[f"Point{i}"] = points[i - 1] if i <= len(points) else 0
    return row


def dim_point(key=500, name="Point A"):
    return {"Key": key, "RunName": name, "Objects": 0}


def base_graph():
    return {
        "DetailStyle": [style()],
        "DetailMasterTable": [master()],
        "DetViewRequest": [request()],
        "DetObjReprMapsNew": [rmap()],
        "DetObjReprMapItems": [ritem(order=0), ritem(order=1)],
        "DetObjAppearance": [appearance()],
        "DetObjAnnotationStrategy": [annot_strategy()],
        "DetAnnotationType": [annot_type()],
        "DetViewDimStrategyNew": [dim_strategy()],
        "DetViewDimStrategyItems": [dim_item()],
        "DetViewDimRequestLinear": [dim_linear()],
        "DetViewDimPointSelection": [dim_point()],
    }


def pk_for(rows):
    return {table: PK.get(table, ["Key"]) for table in rows}


def run_usage(rows, table, values, **kwargs):
    return su.usage(rows, pk_for(rows), table, list(values), **kwargs)


# --- labels and identity ----------------------------------------------------

def test_row_label_prefers_name_columns():
    assert su.row_label({"RunName": "Visible", "Description": "x"}) == "Visible"
    assert su.row_label({"Description": "rule 3"}) == "rule 3"
    assert su.row_label({"Key": 42, "Order": 1}, "T") == "T Key 42, Order 1"


def test_row_label_handles_an_empty_row():
    assert su.row_label({}, "T") == "T"


def test_node_identity_uses_the_whole_primary_key():
    row = {"Key": 100, "Order": 2}
    assert su.node("DetObjReprMapItems", row, PK) == ("DetObjReprMapItems", (100, 2))


# --- upward walk ------------------------------------------------------------

def test_appearance_reaches_the_style_through_the_rule_chain():
    result = run_usage(base_graph(), "DetObjAppearance", [1000])
    assert result["ok"]
    assert [s["name"] for s in result["styles"]] == ["Style A"]
    path = [step["table"] for step in result["styles"][0]["path"]]
    assert path == ["DetObjReprMapItems", "DetObjReprMapsNew", "DetViewRequest",
                    "DetailStyle"]


def test_style_result_carries_the_picker_name_and_categories():
    style_row = run_usage(base_graph(), "DetObjAppearance", [1000])["styles"][0]
    assert style_row["master_name"] == "Style A"
    assert style_row["categories"] == {"base": 3, "sub": 9}
    assert style_row["owner"] == "DSC"


def test_label_formula_reaches_the_style_through_the_strategy():
    result = run_usage(base_graph(), "DetAnnotationType", [9000])
    path = [step["table"] for step in result["styles"][0]["path"]]
    assert path == ["DetObjAnnotationStrategy", "DetObjReprMapItems",
                    "DetObjReprMapsNew", "DetViewRequest", "DetailStyle"]


def test_dimension_point_reaches_the_style_through_the_strategy_chain():
    result = run_usage(base_graph(), "DetViewDimPointSelection", [500])
    path = [step["table"] for step in result["styles"][0]["path"]]
    assert path == ["DetViewDimRequestLinear", "DetViewDimStrategyItems",
                    "DetViewDimStrategyNew", "DetViewRequest", "DetailStyle"]


def test_one_record_used_by_two_styles_reports_both():
    rows = base_graph()
    rows["DetailMasterTable"].append(master(key=2, style_key=2, name="Style B", base=4))
    rows["DetailStyle"].append(style(key=2, name="Style B", request1=20))
    rows["DetViewRequest"].append(request(key=20, name="View 2", map_key=200, dim_key=0))
    rows["DetObjReprMapsNew"].append(rmap(key=200, name="Map 2"))
    rows["DetObjReprMapItems"].append(ritem(map_key=200, order=0, appearance=1000,
                                            strategy=0))
    result = run_usage(rows, "DetObjAppearance", [1000])
    assert [s["name"] for s in result["styles"]] == ["Style A", "Style B"]
    assert any(d["table"] == "DetObjReprMapItems" for d in result["direct"])


def test_unused_record_reports_no_styles():
    rows = base_graph()
    rows["DetObjAppearance"].append(appearance(key=2000, name="Unused"))
    result = run_usage(rows, "DetObjAppearance", [2000])
    assert result["ok"]
    assert result["styles"] == []


def test_composite_key_rules_are_distinct_nodes():
    result = run_usage(base_graph(), "DetObjReprMapItems", [100, 1])
    assert result["styles"][0]["name"] == "Style A"
    assert result["record"]["pk"] == {"Key": 100, "Order": 1}


def test_missing_record_is_reported():
    result = run_usage(base_graph(), "DetObjAppearance", [999999])
    assert not result["ok"]
    assert "No row" in result["error"]


def test_depth_cap_marks_the_result_truncated():
    result = run_usage(base_graph(), "DetObjAppearance", [1000], max_depth=1)
    assert result["ok"]
    assert result["styles"] == []
    assert result["truncated"]


def test_blank_reference_values_are_skipped():
    rows = base_graph()
    rows["DetObjReprMapItems"] = [ritem(0, appearance=0)]
    result = run_usage(rows, "DetObjAppearance", [1000])
    assert result["styles"] == []


# --- orphan scan ------------------------------------------------------------

def test_base_graph_has_no_orphans():
    report = su.orphan_report(base_graph(), pk_for(base_graph()))
    assert report["total"] == 0


def test_unreferenced_library_rows_are_reported():
    rows = base_graph()
    rows["DetObjAppearance"].append(appearance(key=2000, name="Unused"))
    rows["DetAnnotationType"].append(annot_type(key=9100, name="Spare"))
    report = su.orphan_report(rows, pk_for(rows), sample=1)
    tables = {t["table"]: t for t in report["tables"]}
    assert tables["DetObjAppearance"]["unreferenced"] == 1
    assert tables["DetAnnotationType"]["unreferenced"] == 1
    assert tables["DetObjAppearance"]["samples"][0]["label"] == "Unused"
    assert report["total"] == 2


def test_orphan_scan_ignores_root_tables():
    rows = base_graph()
    rows["DetailStyle"].append(style(key=2, name="Unused style", request1=0))
    report = su.orphan_report(rows, pk_for(rows))
    assert all(t["table"] not in su.ROOT_TABLES for t in report["tables"])


def test_orphan_scan_says_which_edges_reach_a_table():
    rows = base_graph()
    rows["DetObjAppearance"].append(appearance(key=2000, name="Unused"))
    report = su.orphan_report(rows, pk_for(rows))
    row = next(t for t in report["tables"] if t["table"] == "DetObjAppearance")
    assert "DetObjReprMapItems.Appearance" in row["reached_from"]


# --- edge table sanity ------------------------------------------------------

def test_ascent_edges_are_unique():
    assert len(su.ASCENT_EDGES) == len(set(su.ASCENT_EDGES))


def test_ascent_edges_cover_the_observed_chain():
    tables = su.edge_tables()
    for table in ("DetailStyle", "DetailMasterTable", "DetViewRequest",
                  "DetObjReprMapsNew", "DetObjReprMapItems", "DetObjAppearance",
                  "DetObjAnnotationStrategy", "DetAnnotationType",
                  "DetViewDimStrategyNew", "DetViewDimStrategyItems",
                  "DetViewDimRequestLinear", "DetViewDimPointSelection"):
        assert table in tables
