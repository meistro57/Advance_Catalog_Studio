"""Anchor diameter clone: re-applying must replace the target, not duplicate it."""

import pytest


SOURCE_DIA = 10.0
TARGET_DIA = 12.0


class FakeCursor:
    def __init__(self, log):
        self.log = log
        self._rows = []
        self._row = None

    def execute(self, sql, params=()):
        norm = " ".join(sql.split())
        params = tuple(params or ())
        self.log.append((norm, params))
        self._rows = []
        self._row = None

        if norm.startswith("SELECT * FROM AnchorsName WHERE Diameter"):
            if abs(params[0] - SOURCE_DIA) < 1e-9:
                self._rows = [{"ID": 1, "Diameter": SOURCE_DIA, "Diameter1": SOURCE_DIA}]
        elif norm.startswith("SELECT * FROM AnchorsDefinition WHERE AnchorID"):
            self._rows = [{"ID": 5, "AnchorID": params[0], "PartName": " 10.00 mm x 100"}]
        elif norm.startswith("SELECT * FROM AnchorsHoleDefinition WHERE AnchorNameID"):
            self._rows = [{"ID": 7, "AnchorNameID": params[0], "HeadDiameter": 18.0}]
        elif norm.startswith("SELECT MAX(ID) AS max_id FROM AnchorsName"):
            self._row = {"max_id": 100}
        elif norm.startswith("SELECT MAX(ID) AS max_id FROM AnchorsDefinition"):
            self._row = {"max_id": 200}
        elif norm.startswith("SELECT MAX(ID) AS max_id FROM AnchorsHoleDefinition"):
            self._row = {"max_id": 300}

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self):
        self.log = []
        self.committed = False
        self.rolled_back = False

    def cursor(self, as_dict=True):
        return FakeCursor(self.log)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _patch_clone(monkeypatch):
    from utils import db

    connections = []

    def fake_open(database=None, autocommit=True):
        conn = FakeConnection()
        connections.append(conn)
        return conn

    monkeypatch.setattr(db, "_open_connection", fake_open)
    monkeypatch.setattr(db, "list_tables", lambda database: [
        "AnchorsName", "AnchorsDefinition", "AnchorsHoleDefinition", "SetNutsBolts",
    ])
    monkeypatch.setattr(db, "guess_catalog_type", lambda database: "anchor")
    monkeypatch.setattr(db, "is_identity_column", lambda database, table, column: False)
    return connections


def _apply():
    from utils import db
    return db.apply_clone_diameter(
        database="SomeAnchor",
        source_dia=SOURCE_DIA,
        target_dia=TARGET_DIA,
        target_name=" 12.00 mm",
        replace_from="10.00",
        replace_to="12.00",
    )


def _index(log, prefix):
    for i, (sql, params) in enumerate(log):
        if sql.startswith(prefix):
            return i
    raise AssertionError(f"statement not found: {prefix}")


def test_second_apply_deletes_target_before_inserting(monkeypatch):
    connections = _patch_clone(monkeypatch)

    _apply()
    first_log = connections[0].log
    assert _index(first_log, "DELETE FROM AnchorsName WHERE Diameter") < _index(
        first_log, "INSERT INTO AnchorsName")
    assert connections[0].committed and not connections[0].rolled_back

    _apply()
    second_log = connections[1].log
    hole_delete = _index(second_log, "DELETE FROM AnchorsHoleDefinition")
    def_delete = _index(second_log, "DELETE FROM AnchorsDefinition")
    anchor_delete = _index(second_log, "DELETE FROM AnchorsName WHERE Diameter")
    anchor_insert = _index(second_log, "INSERT INTO AnchorsName")
    assert hole_delete < def_delete < anchor_delete < anchor_insert
    assert connections[1].committed and not connections[1].rolled_back


def test_inserts_once_per_source_record(monkeypatch):
    connections = _patch_clone(monkeypatch)
    counts = _apply()
    log = connections[0].log
    assert counts["AnchorsName"] == 1
    assert sum(1 for sql, _ in log if sql.startswith("INSERT INTO AnchorsName")) == 1
    assert sum(1 for sql, _ in log if sql.startswith("INSERT INTO AnchorsDefinition")) == 1
    assert sum(1 for sql, _ in log if sql.startswith("INSERT INTO AnchorsHoleDefinition")) == 1


def test_same_source_and_target_is_rejected(monkeypatch):
    connections = _patch_clone(monkeypatch)
    from utils import db
    with pytest.raises(ValueError):
        db.apply_clone_diameter(
            database="SomeAnchor",
            source_dia=SOURCE_DIA,
            target_dia=SOURCE_DIA,
            target_name=" 10.00 mm",
        )
    assert connections == []


def test_bolt_clone_fails_closed_on_identity_columns(monkeypatch):
    from utils import db

    conns = []

    def fake_open(database=None, autocommit=True):
        conn = FakeConnection()
        conns.append(conn)
        return conn

    monkeypatch.setattr(db, "_open_connection", fake_open)
    monkeypatch.setattr(db, "list_tables", lambda database: [
        "BoltsDiameters", "ScrewNew", "SetOfBolts", "SetNutsBolts", "SetBolts",
    ])
    monkeypatch.setattr(db, "guess_catalog_type", lambda database: "bolt")
    monkeypatch.setattr(db, "get_identity_columns",
                        lambda database, table: ["RunID"] if table == "SetBolts" else [])

    with pytest.raises(RuntimeError) as excinfo:
        db.apply_clone_diameter(
            database="SomeBolt",
            source_dia=SOURCE_DIA,
            target_dia=TARGET_DIA,
            target_name=" 12.00 mm",
        )
    assert "SetBolts" in str(excinfo.value)
    assert conns and conns[0].rolled_back and not conns[0].committed
    assert not any(sql.startswith("DELETE") for sql, _ in conns[0].log)


# --- Remove diameter (issue #17) ------------------------------------------

class FakeRemoveCursor:
    def __init__(self, log, fail_on_table=None):
        self.log = log
        self.fail_on_table = fail_on_table
        self.rowcount = 0
        self._rows = []
        self._row = None

    def execute(self, sql, params=()):
        norm = " ".join(sql.split())
        params = tuple(params or ())
        self.log.append((norm, params))
        self.rowcount = 0
        self._rows = []
        self._row = None

        if self.fail_on_table and (
            f"DELETE FROM {self.fail_on_table}" in norm
            or f"DELETE FROM [{self.fail_on_table}]" in norm
        ):
            raise RuntimeError(f"simulated failure on {self.fail_on_table}")

        if norm.startswith("SELECT [Key], RunName FROM BoltsDiameters WHERE [Key]"):
            self._row = {"Key": params[0], "RunName": " 3/4 inch"}
        elif norm.startswith("SELECT COUNT(*) AS cnt FROM BoltsDiameters WHERE [Key]"):
            self._row = {"cnt": 1}
        elif norm.startswith("SELECT COUNT(*) AS cnt FROM BoltsDiameters"):
            self._row = {"cnt": 2}
        elif norm.startswith("SELECT COUNT(*) AS cnt FROM "):
            self._row = {"cnt": 3}
        elif norm.startswith("SELECT TOP 5"):
            self._rows = [{"Name": "sample", "Length": 50.0, "Weight": 0.25}]
        elif norm.startswith("DELETE FROM "):
            self.rowcount = 2

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


class FakeRemoveConnection:
    def __init__(self, fail_on_table=None):
        self.log = []
        self.fail_on_table = fail_on_table
        self.committed = False
        self.rolled_back = False

    def cursor(self, as_dict=True):
        return FakeRemoveCursor(self.log, fail_on_table=self.fail_on_table)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_apply_remove_diameter_anchor_deletes_children_before_parent(monkeypatch):
    from utils import db

    conns = []

    def fake_open(database=None, autocommit=True):
        conn = FakeRemoveConnection()
        conns.append(conn)
        return conn

    monkeypatch.setattr(db, "_open_connection", fake_open)
    monkeypatch.setattr(db, "list_tables", lambda database: [
        "BoltsDiameters", "BoltsDistances", "SetNutsBolts",
        "AnchorsName", "AnchorsDefinition", "AnchorsHoleDefinition",
    ])
    monkeypatch.setattr(db, "guess_catalog_type", lambda database: "anchor")

    counts = db.apply_remove_diameter("SomeAnchor", 19.05)
    assert conns and conns[0].committed and not conns[0].rolled_back
    log = conns[0].log
    hole_idx = _index(log, "DELETE FROM AnchorsHoleDefinition")
    def_idx = _index(log, "DELETE FROM AnchorsDefinition")
    name_idx = _index(log, "DELETE FROM AnchorsName")
    dia_idx = _index(log, "DELETE FROM BoltsDiameters")
    assert hole_idx < def_idx < name_idx < dia_idx
    assert counts["AnchorsHoleDefinition"] == 2
    assert counts["AnchorsDefinition"] == 2
    assert counts["AnchorsName"] == 2
    assert counts["BoltsDiameters"] == 2


def test_apply_remove_diameter_bolt_rolls_back_on_error(monkeypatch):
    from utils import db

    conns = []

    def fake_open(database=None, autocommit=True):
        conn = FakeRemoveConnection(fail_on_table="ScrewNew")
        conns.append(conn)
        return conn

    monkeypatch.setattr(db, "_open_connection", fake_open)
    monkeypatch.setattr(db, "list_tables", lambda database: [
        "BoltsDiameters", "BoltsDistances", "ScrewNew",
        "SetOfBolts", "SetNutsBolts", "SetBolts",
    ])
    monkeypatch.setattr(db, "guess_catalog_type", lambda database: "bolt")

    with pytest.raises(RuntimeError):
        db.apply_remove_diameter("SomeBolt", 19.05)
    assert conns and conns[0].rolled_back and not conns[0].committed


def test_remove_diameter_rejects_unsupported_catalog_types(monkeypatch):
    from utils import db

    monkeypatch.setattr(db, "guess_catalog_type", lambda database: "shear stud")
    with pytest.raises(ValueError):
        db.preview_remove_diameter("SomeStud", 19.05)
    with pytest.raises(ValueError):
        db.apply_remove_diameter("SomeStud", 19.05)


def test_remove_diameter_route_preview_and_apply(monkeypatch):
    from app import app
    from utils import db

    conns = []
    snapshots_taken = []

    def fake_open(database=None, autocommit=True):
        conn = FakeRemoveConnection()
        conns.append(conn)
        return conn

    monkeypatch.setattr(db, "_open_connection", fake_open)
    monkeypatch.setattr(db, "list_tables", lambda database: [
        "BoltsDiameters", "BoltsDistances", "ScrewNew",
        "SetOfBolts", "SetNutsBolts", "SetBolts",
    ])
    monkeypatch.setattr(db, "guess_catalog_type", lambda database: "bolt")
    monkeypatch.setattr(db, "get_catalog_diameters", lambda database: [
        {"key": 19.05, "run_name": " 3/4 inch", "token": "3/4", "total_related": 12, "is_orphan": False},
    ])
    monkeypatch.setattr("utils.metadata.get", lambda database: {"catalog_type": "bolt"})
    monkeypatch.setattr(
        "utils.snapshots.create_snapshot",
        lambda database, reason: snapshots_taken.append((database, reason)) or {"filename": "snap.bak"},
    )

    client = app.test_client()
    get_resp = client.get("/db/SomeBolt/remove-diameter?diameter=19.05")
    assert get_resp.status_code == 200
    body = get_resp.get_data(as_text=True)
    assert "Removal Preview" in body
    assert "Remove Diameter (" in body

    with client.session_transaction() as sess:
        token = sess["_csrf"]

    post_resp = client.post(
        "/db/SomeBolt/remove-diameter",
        data={"csrf_token": token, "diameter": "19.05", "action": "apply"},
    )
    assert post_resp.status_code == 302
    assert post_resp.headers["Location"].endswith("/db/SomeBolt")
    assert snapshots_taken == [("SomeBolt", "remove diameter 19.05 mm")]


def test_remove_diameter_route_aborts_if_snapshot_fails(monkeypatch):
    from app import app
    from utils import db

    applied = []
    monkeypatch.setattr(db, "guess_catalog_type", lambda database: "bolt")
    monkeypatch.setattr(db, "get_catalog_diameters", lambda database: [
        {"key": 19.05, "run_name": " 3/4 inch", "token": "3/4", "total_related": 12, "is_orphan": False},
    ])
    monkeypatch.setattr(db, "preview_remove_diameter", lambda database, dia: {
        "diameter": 19.05, "run_name": " 3/4 inch", "catalog_type": "bolt",
        "tables": {"BoltsDiameters": {"count": 1, "samples": []}},
        "total_rows": 1, "remaining_diameters": 1, "warnings": [],
    })
    monkeypatch.setattr(db, "apply_remove_diameter", lambda *a, **k: applied.append(True))
    monkeypatch.setattr("utils.metadata.get", lambda database: {"catalog_type": "bolt"})

    def fail_snap(database, reason):
        raise RuntimeError("disk full")

    monkeypatch.setattr("utils.snapshots.create_snapshot", fail_snap)

    client = app.test_client()
    client.get("/")
    with client.session_transaction() as sess:
        token = sess["_csrf"]

    resp = client.post(
        "/db/SomeBolt/remove-diameter",
        data={"csrf_token": token, "diameter": "19.05", "action": "apply"},
    )
    assert resp.status_code == 200
    assert "Pre-change snapshot failed, so nothing was removed" in resp.get_data(as_text=True)
    assert applied == []
