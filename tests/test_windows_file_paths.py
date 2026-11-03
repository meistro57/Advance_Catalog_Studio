"""Advance Steel refuses an mdf whose stored file paths are Linux paths, even
with no edits (verification log A6.10: the Linux-path round trip of Mark's
railing style was refused, the Windows-path round trip of the same file
imported). The app attaches with C:\\ paths, which SQL Server on Linux maps to
the same files, and re-homes older databases before export. No SQL Server
needed: connect() is stubbed and every statement recorded."""

import pytest

from utils import db


class Cur:
    def __init__(self, files=()):
        self.files, self.sql, self._rows = list(files), [], []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if "sys.master_files" in sql:
            self._rows = [dict(r) for r in self.files]
        elif "DATABASEPROPERTYEX" in sql:
            self._rows = [{"v": 904}]
        elif "CHECKPRIMARYFILE" in sql:
            self._rows = [{"property": "Database version", "value": 904}]
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return self._rows


class Conn:
    def close(self):
        pass


def _stub(monkeypatch, files=()):
    cur = Cur(files)
    monkeypatch.setattr(db, "connect", lambda database=None: (Conn(), cur))
    return cur


def test_path_conversion_both_ways():
    assert db.container_windows_path("/var/opt/mssql/attach/x.mdf") == r"C:\var\opt\mssql\attach\x.mdf"
    assert db.container_windows_path(r"C:\var\x.mdf") == r"C:\var\x.mdf"
    assert db.container_linux_path(r"C:\var\opt\mssql\attach\x.mdf") == "/var/opt/mssql/attach/x.mdf"
    assert db.container_linux_path("/var/opt/x.mdf") == "/var/opt/x.mdf"
    with pytest.raises(ValueError):
        db.container_windows_path("relative/x.mdf")


def test_attach_uses_windows_paths(monkeypatch):
    cur = _stub(monkeypatch)
    db.attach_database("Railing", "Railing.mdf", "Railing_log.ldf")
    create = next(s for s in cur.sql if "CREATE DATABASE" in s)
    assert r"FILENAME = N'C:\var\opt\mssql\attach\Railing.mdf'" in create
    assert r"FILENAME = N'C:\var\opt\mssql\attach\Railing_log.ldf'" in create
    assert "/var/opt" not in create


def test_new_catalogs_are_born_with_windows_paths(monkeypatch):
    cur = _stub(monkeypatch)
    db.create_empty_database("NewBolts")
    create = next(s for s in cur.sql if "CREATE DATABASE" in s)
    assert r"C:\var\opt\mssql\attach\NewBolts.mdf" in create and "/var/opt" not in create


def test_physical_files_come_back_in_docker_cp_form(monkeypatch):
    _stub(monkeypatch, [
        {"type_desc": "ROWS", "physical_name": r"C:\var\opt\mssql\attach\R.mdf"},
        {"type_desc": "LOG", "physical_name": r"C:\var\opt\mssql\attach\R_log.ldf"},
    ])
    assert db.get_physical_files("R") == {"mdf": "/var/opt/mssql/attach/R.mdf",
                                          "ldf": "/var/opt/mssql/attach/R_log.ldf"}


def test_older_linux_path_databases_are_rehomed_before_export(monkeypatch):
    cur = _stub(monkeypatch, [
        {"name": "AstorDetailProcessesBLANK", "physical_name": "/var/opt/mssql/attach/mark_rail.mdf"},
        {"name": "AstorDetailProcessesBLANK_log", "physical_name": "/var/opt/mssql/attach/mark_rail_log.ldf"},
    ])
    changed = db.ensure_windows_file_paths("mark_rail")
    assert changed == ["AstorDetailProcessesBLANK", "AstorDetailProcessesBLANK_log"]
    modify = [s for s in cur.sql if "MODIFY FILE" in s]
    assert len(modify) == 2
    assert r"FILENAME = N'C:\var\opt\mssql\attach\mark_rail.mdf'" in modify[0]
    # the change only takes effect after an offline/online cycle
    tail = [s for s in cur.sql if "SET OFFLINE" in s or "SET ONLINE" in s]
    assert len(tail) == 2 and "OFFLINE" in tail[0] and "ONLINE" in tail[1]


def test_windows_path_databases_are_left_alone(monkeypatch):
    cur = _stub(monkeypatch, [
        {"name": "A", "physical_name": r"C:\var\opt\mssql\attach\A.mdf"},
        {"name": "A_log", "physical_name": r"C:\var\opt\mssql\attach\A_log.ldf"},
    ])
    assert db.ensure_windows_file_paths("A") == []
    assert not any("MODIFY FILE" in s or "OFFLINE" in s for s in cur.sql)


def test_both_export_routes_rehome_first():
    import inspect
    import app as app_module
    for fn in (app_module.export_copy, app_module.detach):
        src = inspect.getsource(fn)
        assert src.index("ensure_windows_file_paths") < src.index("get_physical_files"), fn.__name__
