"""Find & replace: one transaction, and legacy text columns are cast."""

import pytest


COLUMNS = [
    {"TABLE_NAME": "SetBolts", "COLUMN_NAME": "Name", "DATA_TYPE": "nvarchar"},
    {"TABLE_NAME": "Notes", "COLUMN_NAME": "Body", "DATA_TYPE": "ntext"},
    {"TABLE_NAME": "SetBolts", "COLUMN_NAME": "OwnerText", "DATA_TYPE": "varchar"},
]


class FakeCursor:
    def __init__(self, conn, fail_on=None):
        self.conn = conn
        self.fail_on = fail_on
        self._rows = []
        self._row = None
        self.rowcount = 0

    def execute(self, sql, params=()):
        norm = " ".join(sql.split())
        self.conn.log.append((norm, tuple(params or ())))
        self._rows = []
        self._row = None
        if "INFORMATION_SCHEMA.COLUMNS" in norm:
            self._rows = COLUMNS
            return
        if norm.startswith("SELECT COUNT(*)"):
            self._row = {"cnt": 0 if "[Notes]" in norm else 4}
            return
        if norm.startswith("UPDATE"):
            if self.fail_on and self.fail_on in norm:
                raise RuntimeError("ntext is invalid for argument 1 of replace function")
            self.rowcount = 2

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, fail_on=None):
        self.log = []
        self.fail_on = fail_on
        self.committed = False
        self.rolled_back = False

    def cursor(self, as_dict=True):
        return FakeCursor(self, self.fail_on)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _patch(monkeypatch, fail_on=None, apply_path=True):
    from utils import db
    conn = FakeConnection(fail_on=fail_on)
    if apply_path:
        monkeypatch.setattr(db, "_open_connection", lambda database=None, autocommit=True: conn)
    else:
        monkeypatch.setattr(db, "connect", lambda database: (conn, conn.cursor()))
    return conn


def test_apply_is_one_transaction(monkeypatch):
    from utils import db
    conn = _patch(monkeypatch)
    result = db.apply_find_replace("SomeDb", "10.0", "12.0")
    assert conn.committed and not conn.rolled_back
    assert result == {"SetBolts.Name": 2, "Notes.Body": 2, "SetBolts.OwnerText": 2}
    updates = [sql for sql, _ in conn.log if sql.startswith("UPDATE")]
    assert len(updates) == 3


def test_legacy_ntext_is_cast_for_replace_and_like(monkeypatch):
    from utils import db
    conn = _patch(monkeypatch)
    db.apply_find_replace("SomeDb", "10.0", "12.0", )
    update = next(sql for sql, _ in conn.log if sql.startswith("UPDATE [Notes]"))
    assert "CAST([Body] AS nvarchar(max))" in update
    assert "REPLACE(CAST([Body] AS nvarchar(max))" in update


def test_failure_rolls_back_and_re_raises(monkeypatch):
    from utils import db
    conn = _patch(monkeypatch, fail_on="UPDATE [Notes]")
    with pytest.raises(RuntimeError):
        db.apply_find_replace("SomeDb", "10.0", "12.0")
    assert conn.rolled_back and not conn.committed


def test_preview_uses_one_connection_and_casts_legacy_types(monkeypatch):
    from utils import db
    conn = _patch(monkeypatch, apply_path=False)
    result = db.preview_find_replace("SomeDb", "10.0")
    assert result == {"SetBolts.Name": 4, "SetBolts.OwnerText": 4}
    selects = [sql for sql, _ in conn.log if sql.startswith("SELECT COUNT(*)")]
    assert len(selects) == 3
    assert "CAST([Body] AS nvarchar(max)) LIKE" in selects[1]
    assert conn.log[0][0].startswith("SELECT TABLE_NAME")
