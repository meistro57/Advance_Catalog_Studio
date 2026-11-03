"""Catalog comparison: pure pairing helpers plus the route."""

from utils import compare


def test_table_diff_splits_shared_and_single_sided_tables():
    diff = compare.table_diff(["A", "B", "C"], ["B", "C", "D"])
    assert diff == {"shared": ["B", "C"], "only_a": ["A"], "only_b": ["D"]}


def test_count_diff_reports_counts_and_deltas():
    rows = compare.count_diff(
        tables_a=["SetBolts", "ScrewNew", "Dropped"],
        counts_a={"SetBolts": 5, "ScrewNew": 2, "Dropped": 1},
        tables_b=["SetBolts", "ScrewNew", "Added"],
        counts_b={"SetBolts": 7, "ScrewNew": 2, "Added": 4},
    )
    by_table = {row["table"]: row for row in rows}
    assert by_table["SetBolts"] == {
        "table": "SetBolts", "a": 5, "b": 7, "delta": 2, "present": "both"}
    assert by_table["ScrewNew"]["delta"] == 0
    assert by_table["Dropped"] == {
        "table": "Dropped", "a": 1, "b": None, "delta": None, "present": "a"}
    assert by_table["Added"] == {
        "table": "Added", "a": None, "b": 4, "delta": None, "present": "b"}


def test_diameter_diff_pairs_by_key_and_keeps_orphans_visible():
    a = [
        {"key": 12.7, "run_name": " 1/2 inch", "total_related": 4, "is_orphan": False},
        {"key": 9.525, "run_name": " 3/8 inch", "total_related": 0, "is_orphan": True},
    ]
    b = [
        {"key": 12.7, "run_name": " 1/2 inch", "total_related": 6, "is_orphan": False},
        {"key": 15.875, "run_name": " 5/8 inch", "total_related": 3, "is_orphan": False},
    ]
    rows = compare.diameter_diff(a, b)
    by_key = {row["key"]: row for row in rows}
    assert by_key[12.7]["present"] == "both"
    assert (by_key[12.7]["records_a"], by_key[12.7]["records_b"]) == (4, 6)
    assert by_key[9.525]["present"] == "a" and by_key[9.525]["orphan_a"] is True
    assert by_key[15.875]["present"] == "b" and by_key[15.875]["name_a"] is None


def test_diameter_diff_ignores_unparsable_keys():
    rows = compare.diameter_diff([{"key": "not-a-number"}], [{"key": 10.0}])
    assert [row["key"] for row in rows] == [10.0]


def test_summary_counts_tables_and_diameters():
    count_rows = [
        {"table": "A", "a": 1, "b": 2, "delta": 1, "present": "both"},
        {"table": "B", "a": 1, "b": 1, "delta": 0, "present": "both"},
        {"table": "C", "a": 1, "b": None, "delta": None, "present": "a"},
        {"table": "D", "a": None, "b": 1, "delta": None, "present": "b"},
    ]
    diameter_rows = [
        {"key": 10.0, "present": "both"},
        {"key": 12.0, "present": "a"},
        {"key": 16.0, "present": "b"},
    ]
    summary = compare.summary(count_rows, diameter_rows)
    assert summary["tables_shared"] == 2 and summary["tables_changed"] == 1
    assert summary["tables_only_a"] == 1 and summary["tables_only_b"] == 1
    assert summary["diameters_both"] == 1
    assert summary["diameters_only_a"] == 1 and summary["diameters_only_b"] == 1


def test_compare_route_needs_two_known_databases(monkeypatch):
    from app import app
    monkeypatch.setattr("utils.db.list_databases", lambda: ["Alpha", "Beta"])
    client = app.test_client()
    assert client.get("/compare").status_code == 200
    assert client.get("/compare?a=Alpha").status_code == 200
    assert client.get("/compare?a=Alpha&b=Alpha").status_code == 200
    resp = client.get("/compare?a=Alpha&b=Gamma")
    assert "Pick two attached databases" in resp.get_data(as_text=True)


def test_compare_route_renders_the_comparison(monkeypatch):
    from app import app
    fake = {
        "a": {"database": "Alpha", "catalog_type": "bolt", "tables": 2, "rows": 9},
        "b": {"database": "Beta", "catalog_type": "bolt", "tables": 2, "rows": 11},
        "tables": [
            {"table": "SetBolts", "a": 5, "b": 7, "delta": 2, "present": "both"},
        ],
        "diameters": [
            {"key": 12.7, "name_a": " 1/2 inch", "name_b": " 1/2 inch",
             "records_a": 4, "records_b": 6, "orphan_a": False, "orphan_b": False,
             "present": "both"},
        ],
        "summary": {"tables_shared": 1, "tables_only_a": 0, "tables_only_b": 0,
                    "tables_changed": 1, "diameters_both": 1,
                    "diameters_only_a": 0, "diameters_only_b": 0},
    }
    monkeypatch.setattr("utils.db.list_databases", lambda: ["Alpha", "Beta"])
    monkeypatch.setattr("utils.compare.build_comparison",
                        lambda a, b: fake)
    resp = app.test_client().get("/compare?a=Alpha&b=Beta")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "SetBolts" in body and "+2" in body
    assert "1/2 inch" in body
    assert "read-only" in body
