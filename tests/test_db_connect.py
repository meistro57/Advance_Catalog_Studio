"""Connection-plumbing tests: the app must fail fast when the scratch SQL
Server container is stopped instead of blocking for pymssql's 60s default
(which made every page look hung)."""

import pytest

import config
import utils.db as db


class _FakeCursor:
    def __init__(self, as_dict=False):
        self.as_dict = as_dict


class _FakeConnection:
    def __init__(self):
        self.closed = False

    def cursor(self, as_dict=False):
        return _FakeCursor(as_dict)

    def close(self):
        self.closed = True


@pytest.fixture
def captured_connect(monkeypatch):
    captured = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return _FakeConnection()

    monkeypatch.setattr(db.pymssql, "connect", fake_connect)
    return captured


def test_connect_passes_login_timeout(captured_connect):
    conn, cur = db.connect("SomeDb")
    assert captured_connect["login_timeout"] == config.DB_LOGIN_TIMEOUT
    assert captured_connect["database"] == "SomeDb"
    assert captured_connect["autocommit"] is True
    assert cur.as_dict is True


def test_open_connection_passes_login_timeout(captured_connect):
    db._open_connection(database="SomeDb", autocommit=False)
    assert captured_connect["login_timeout"] == config.DB_LOGIN_TIMEOUT
    assert captured_connect["autocommit"] is False


def test_login_timeout_is_short():
    assert 0 < config.DB_LOGIN_TIMEOUT <= 10


def test_index_skips_database_when_container_down(monkeypatch):
    from app import app

    monkeypatch.setattr("app.docker_ops.container_is_running", lambda: False)

    def boom(*args, **kwargs):
        raise AssertionError("list_databases must not be called when container is down")

    monkeypatch.setattr("app.db.list_databases", boom)

    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"is not running" in resp.data
