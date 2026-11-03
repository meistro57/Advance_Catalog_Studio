"""Exporting a copy without detaching.

The point is the iterate loop: export -> import into Advance Steel -> change
something -> export again. The database has to survive the export, its files
have to be as clean as a detach would leave them, and a failed copy must not
leave it offline. No SQL Server: the connection and docker calls are stubbed.
"""

import io
import pathlib
import zipfile

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


def _statements(conn):
    return [sql for sql, _ in conn.executed]


def test_offline_database_closes_files_then_returns_online(monkeypatch):
    from utils import db
    conn = FakeConnection()
    monkeypatch.setattr(db, "connect", lambda database=None: (conn, conn.cursor()))

    with db.offline_database("SomeDb"):
        assert any("SET OFFLINE" in sql for sql in _statements(conn))

    statements = _statements(conn)
    assert any("SET OFFLINE WITH ROLLBACK IMMEDIATE" in sql for sql in statements)
    # Detach is what the copy exists to avoid.
    assert not any("sp_detach_db" in sql for sql in statements)
    assert "ALTER DATABASE [SomeDb] SET ONLINE;" in statements
    assert conn.closed


def test_offline_database_still_returns_online_when_the_copy_fails(monkeypatch):
    from utils import db
    conn = FakeConnection()
    monkeypatch.setattr(db, "connect", lambda database=None: (conn, conn.cursor()))

    with pytest.raises(RuntimeError):
        with db.offline_database("SomeDb"):
            raise RuntimeError("copy failed")

    assert "ALTER DATABASE [SomeDb] SET ONLINE;" in _statements(conn)
    assert conn.closed


def test_offline_database_rejects_an_unsafe_name():
    from utils import db
    with pytest.raises(ValueError):
        with db.offline_database("bad name; DROP DATABASE x"):
            pass


def _client_with_csrf():
    from app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_csrf"] = "tok"
    return client


def _stub_pipeline(monkeypatch, tmp_path, payload=(b"mdf-bytes", b"ldf-bytes")):
    """Pretend the copy happens: write the given bytes into the destination."""
    import contextlib

    import app as app_module
    from utils import db

    copies = []
    offline_calls = []

    monkeypatch.setattr(db, "ensure_windows_file_paths", lambda database: [])
    monkeypatch.setattr(db, "get_physical_files", lambda database: {
        "mdf": "/var/opt/mssql/attach/SomeDb.mdf",
        "ldf": "/var/opt/mssql/attach/SomeDb_log.ldf",
    })

    @contextlib.contextmanager
    def fake_offline(database):
        offline_calls.append(database)
        yield

    def fake_copy(src, dest):
        data = payload[0] if dest.endswith(".mdf") else payload[1]
        pathlib.Path(dest).write_bytes(data)
        copies.append((src, dest))

    monkeypatch.setattr(db, "offline_database", fake_offline)
    monkeypatch.setattr(db, "detach_database", lambda database: pytest.fail("must not detach"))
    monkeypatch.setattr(app_module.docker_ops, "copy_out_of_container", fake_copy)
    monkeypatch.setattr(app_module.config, "EXPORT_DIR", str(tmp_path))
    return copies, offline_calls


def test_export_copy_downloads_the_pair_as_a_zip(monkeypatch, tmp_path):
    copies, offline_calls = _stub_pipeline(monkeypatch, tmp_path)
    client = _client_with_csrf()

    resp = client.post("/db/SomeDb/export-copy",
                       data={"csrf_token": "tok", "return_to": "/db/SomeDb"})

    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    assert 'attachment; filename=SomeDb.zip' in resp.headers["Content-Disposition"]
    assert offline_calls == ["SomeDb"]
    assert copies == [
        ("/var/opt/mssql/attach/SomeDb.mdf", str(tmp_path / "SomeDb.mdf")),
        ("/var/opt/mssql/attach/SomeDb_log.ldf", str(tmp_path / "SomeDb_log.ldf")),
    ]

    with zipfile.ZipFile(io.BytesIO(resp.data)) as archive:
        assert sorted(archive.namelist()) == ["SomeDb.mdf", "SomeDb_log.ldf"]
        assert archive.read("SomeDb.mdf") == b"mdf-bytes"
        assert archive.read("SomeDb_log.ldf") == b"ldf-bytes"


def test_export_copy_also_leaves_the_pair_in_exports(monkeypatch, tmp_path):
    """The zip is a convenience; the dashboard links keep working from disk."""
    _stub_pipeline(monkeypatch, tmp_path)
    client = _client_with_csrf()
    client.post("/db/SomeDb/export-copy", data={"csrf_token": "tok"})

    assert (tmp_path / "SomeDb.mdf").is_file()
    assert (tmp_path / "SomeDb_log.ldf").is_file()


def test_export_copy_failure_returns_to_the_page_that_asked(monkeypatch):
    import contextlib

    import app as app_module
    from utils import db

    monkeypatch.setattr(db, "ensure_windows_file_paths", lambda database: [])
    monkeypatch.setattr(db, "get_physical_files", lambda database: {"mdf": "a", "ldf": "b"})

    @contextlib.contextmanager
    def fake_offline(database):
        yield

    monkeypatch.setattr(db, "offline_database", fake_offline)
    monkeypatch.setattr(app_module.docker_ops, "copy_out_of_container",
                        lambda src, dest: (_ for _ in ()).throw(RuntimeError("copy failed")))

    client = _client_with_csrf()
    resp = client.post("/db/SomeDb/export-copy",
                       data={"csrf_token": "tok", "return_to": "/db/SomeDb/drawing-style"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/db/SomeDb/drawing-style")


def test_export_copy_failure_ignores_a_forged_return_to(monkeypatch):
    from utils import db

    monkeypatch.setattr(db, "ensure_windows_file_paths", lambda database: [])
    monkeypatch.setattr(db, "get_physical_files", lambda database: {})

    client = _client_with_csrf()
    resp = client.post("/db/SomeDb/export-copy",
                       data={"csrf_token": "tok", "return_to": "https://example.com/"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/db/SomeDb")


def test_export_copy_requires_csrf():
    client = _client_with_csrf()
    assert client.post("/db/SomeDb/export-copy").status_code == 400


def test_export_copy_rejects_an_unsafe_database_name():
    client = _client_with_csrf()
    assert client.post("/db/bad%20name/export-copy",
                       data={"csrf_token": "tok"}).status_code in (302, 400, 404)
