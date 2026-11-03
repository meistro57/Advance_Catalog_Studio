"""Catalog Studio owns one SQL Server 2019 container and touches nothing else.
docker is stubbed: every command the app would run is recorded instead."""

import pytest

import config
from utils import docker_ops


class Docker:
    def __init__(self, exists=False, running=False, image=config.SCRATCH_SQL_IMAGE):
        self.exists, self.running, self.image, self.calls = exists, running, image, []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "inspect"]:
            if not self.exists:
                raise RuntimeError("No such object")
            fmt = cmd[3]
            if fmt == "{{.Config.Image}}":
                return self.image + "\n"
            if fmt == "{{.State.Running}}":
                return "true\n" if self.running else "false\n"
            return "abc\n"
        return ""


def _stub(monkeypatch, **kw):
    fake = Docker(**kw)
    monkeypatch.setattr(docker_ops, "_run", fake)
    return fake


def test_config_pins_sql_2019_on_its_own_name_and_port():
    assert config.SCRATCH_SQL_IMAGE == "mcr.microsoft.com/mssql/server:2019-latest"
    assert config.CONTAINER_NAME == "catalog-studio-sql2019"
    assert config.DB_CONFIG["port"] == config.SQL_HOST_PORT == 14330


def test_first_run_creates_the_container_bound_to_localhost(monkeypatch):
    fake = _stub(monkeypatch)
    assert docker_ops.ensure_container() == "created"
    run = fake.calls[-1]
    assert run[:2] == ["docker", "run"]
    assert "catalog-studio-sql2019" in run and config.SCRATCH_SQL_IMAGE in run
    assert "127.0.0.1:14330:1433" in run
    assert "--restart" in run and "unless-stopped" in run


def test_stopped_container_is_started_not_recreated(monkeypatch):
    fake = _stub(monkeypatch, exists=True, running=False)
    assert docker_ops.ensure_container() == "started"
    assert ["docker", "start", "catalog-studio-sql2019"] in fake.calls
    assert not any(c[:2] == ["docker", "run"] for c in fake.calls)


def test_running_container_is_left_alone(monkeypatch):
    fake = _stub(monkeypatch, exists=True, running=True)
    assert docker_ops.ensure_container() == "running"
    assert all(c[1] == "inspect" for c in fake.calls)


def test_a_same_name_container_on_another_image_is_refused(monkeypatch):
    fake = _stub(monkeypatch, exists=True, running=True, image="mcr.microsoft.com/mssql/server:2022-latest")
    with pytest.raises(RuntimeError, match="will not change it"):
        docker_ops.ensure_container()
    assert all(c[1] == "inspect" for c in fake.calls)


def test_only_the_apps_own_container_is_ever_named(monkeypatch):
    fake = _stub(monkeypatch)
    docker_ops.ensure_container()
    for cmd in fake.calls:
        names = [c for c in cmd if "sql" in c and "mssql/server" not in c and ":" not in c]
        assert all(n == "catalog-studio-sql2019" for n in names), cmd


def test_copied_files_are_made_writable(monkeypatch):
    fake = _stub(monkeypatch, exists=True, running=True)
    docker_ops.copy_into_container("/tmp/x.mdf", "x.mdf")
    assert ["docker", "exec", "-u", "root", "catalog-studio-sql2019", "chmod", "660",
            "/var/opt/mssql/attach/x.mdf"] in fake.calls


def test_start_route_needs_csrf_and_starts(monkeypatch):
    from app import app
    import app as app_module
    called = []
    monkeypatch.setattr(app_module.docker_ops, "ensure_container", lambda: called.append(1) or "started")
    client = app.test_client()
    assert client.post("/sql/start").status_code == 400
    with client.session_transaction() as sess:
        sess["_csrf"] = "tok"
    resp = client.post("/sql/start", data={"csrf_token": "tok"})
    assert resp.status_code == 302 and called == [1]


def test_dashboard_offers_the_start_button_when_stopped(monkeypatch):
    from app import app
    import app as app_module
    monkeypatch.setattr(app_module.docker_ops, "container_is_running", lambda: False)
    html = app.test_client().get("/").get_data(as_text=True)
    assert "Start SQL Server 2019" in html and "catalog-studio-sql2019" in html
    assert "never touches Advance Steel" in html


def test_ownership_uses_the_user_only(monkeypatch):
    # mssql/server:2019 has no "mssql" group; "mssql:mssql" fails there.
    fake = _stub(monkeypatch, exists=True, running=True)
    docker_ops.copy_into_container("/tmp/x.mdf", "x.mdf")
    chowns = [c for c in fake.calls if "chown" in c]
    assert chowns and all("mssql:mssql" not in c for c in chowns)
