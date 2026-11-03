"""Advance Steel 2026 imports SQL Server 2019 files (version 904) only.
Attaching to a newer server upgrades the file for good, so attach and create
must refuse first. No SQL Server needed: connect() is stubbed."""

import pytest

from utils import db


class FakeCursor:
    def __init__(self, server, file_value):
        self.server, self.file_value, self.sql = server, file_value, []
        self._rows = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if "DATABASEPROPERTYEX" in sql:
            self._rows = [{"v": self.server}]
        elif "CHECKPRIMARYFILE" in sql:
            self._rows = [{"property": "Database name", "value": b"X"},
                          {"property": "Database version", "value": self.file_value}]
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return self._rows


class FakeConn:
    def close(self):
        pass


def _stub(monkeypatch, server, file_value):
    cur = FakeCursor(server, file_value)
    monkeypatch.setattr(db, "connect", lambda database=None: (FakeConn(), cur))
    return cur


# --- decoding what pymssql hands back ----------------------------------------

def test_decodes_every_shape_seen():
    assert db.decode_file_version(904) == 904
    assert db.decode_file_version(b"\x88\x03\x00\x00") == 904      # DATABASEPROPERTYEX on 2019
    assert db.decode_file_version(b"\xbd\x03\x00\x00") == 957      # ... on 2022
    assert db.decode_file_version(b"\xce\x88") == 904                 # DBCC CHECKPRIMARYFILE
    assert db.decode_file_version("957") == 957
    assert db.decode_file_version(None) is None


# --- the rule -----------------------------------------------------------------

def test_2019_server_and_file_are_fine():
    assert db.compatibility_problem(904, 904) is None
    assert db.compatibility_problem(904) is None


def test_2022_server_would_upgrade_a_2019_file():
    msg = db.compatibility_problem(957, 904)
    assert "SQL Server 2022" in msg and "older than Release 5.1" in msg
    assert "mssql/server:2019-latest" in msg


def test_already_upgraded_file_is_named_as_such():
    assert "already SQL Server 2022 format" in db.compatibility_problem(957, 957)
    assert "can only import version 904" in db.compatibility_problem(904, 957)


def test_older_files_are_allowed():
    assert db.compatibility_problem(904, 869) is None


# --- wired into attach and create --------------------------------------------

def test_attach_refuses_on_a_2022_server_before_attaching(monkeypatch):
    cur = _stub(monkeypatch, b"\xbd\x03\x00\x00", b"\xce\x88")
    with pytest.raises(ValueError, match="upgrades the file permanently"):
        db.attach_database("Railing", "Railing.mdf", "Railing_log.ldf")
    assert not any("CREATE DATABASE" in s for s in cur.sql)


def test_attach_goes_ahead_on_2019(monkeypatch):
    cur = _stub(monkeypatch, b"\x88\x03\x00\x00", b"\xce\x88")
    db.attach_database("Railing", "Railing.mdf", "Railing_log.ldf")
    assert any("CREATE DATABASE [Railing]" in s for s in cur.sql)
    assert any("CHECKPRIMARYFILE" in s for s in cur.sql)


def test_create_refuses_on_a_2022_server(monkeypatch):
    cur = _stub(monkeypatch, 957, None)
    with pytest.raises(ValueError):
        db.create_empty_database("NewBolts")
    assert not any("CREATE DATABASE" in s for s in cur.sql)


def test_unsafe_path_is_rejected():
    with pytest.raises(ValueError):
        db.primary_file_version("/x/it's.mdf")
