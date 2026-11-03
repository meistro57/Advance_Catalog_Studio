"""Connection-recovery behaviour for detach/backup and the token-safe diameter replace."""

import pytest


class FakeCursor:
    def __init__(self, conn, fail_on=None):
        self.conn = conn
        self.fail_on = fail_on
        self.executed = conn.executed

    def execute(self, sql, params=()):
        norm = " ".join(sql.split())
        self.executed.append((norm, tuple(params or ())))
        if self.fail_on and self.fail_on in norm:
            raise RuntimeError("simulated failure")


class FakeConnection:
    def __init__(self, fail_on=None):
        self.executed = []
        self.fail_on = fail_on
        self.closed = False

    def cursor(self, as_dict=True):
        return FakeCursor(self, self.fail_on)

    def close(self):
        self.closed = True


def test_detach_restores_multi_user_when_it_fails(monkeypatch):
    from utils import db
    conn = FakeConnection(fail_on="sp_detach_db")
    monkeypatch.setattr(db, "connect", lambda database=None: (conn, conn.cursor()))

    with pytest.raises(RuntimeError):
        db.detach_database("SomeDb")

    statements = [sql for sql, _ in conn.executed]
    assert any("SET SINGLE_USER" in sql for sql in statements)
    assert any("SET MULTI_USER" in sql for sql in statements)
    assert conn.closed


def test_detach_closes_and_stays_detached_on_success(monkeypatch):
    from utils import db
    conn = FakeConnection()
    monkeypatch.setattr(db, "connect", lambda database=None: (conn, conn.cursor()))

    db.detach_database("SomeDb")

    statements = [sql for sql, _ in conn.executed]
    assert not any("SET MULTI_USER" in sql for sql in statements)
    assert conn.closed


def test_backup_closes_its_connection_when_the_backup_fails(monkeypatch):
    from utils import db
    conn = FakeConnection(fail_on="BACKUP DATABASE")
    monkeypatch.setattr(db, "connect", lambda database=None: (conn, conn.cursor()))

    with pytest.raises(RuntimeError):
        db.backup_database("SomeDb", "/var/opt/mssql/data/some.bak")

    assert conn.closed


def test_replace_diameter_in_text_respects_token_boundaries():
    from utils.db import replace_diameter_in_text

    assert replace_diameter_in_text("20.0 - 120.0 hole for 20.0", 20.0, 12.0) == \
        "12.0 - 120.0 hole for 12.0"
    assert replace_diameter_in_text("M20 x 20.0", 20.0, 12.0) == "M20 x 12.0"
    assert replace_diameter_in_text("120.05", 20.0, 12.0) == "120.05"
    assert replace_diameter_in_text("20,0 mm and 20,05", 20.0, 12.0) == "12,0 mm and 20,05"
    assert replace_diameter_in_text("", 20.0, 12.0) == ""
