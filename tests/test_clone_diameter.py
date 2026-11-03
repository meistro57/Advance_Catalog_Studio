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
