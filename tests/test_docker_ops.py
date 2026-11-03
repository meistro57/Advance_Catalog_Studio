"""The docker commands that move catalog files in and out of the scratch
container. No Docker daemon needed: `_run` is stubbed."""

from config import CONTAINER_ATTACH_PATH, CONTAINER_NAME
from utils import docker_ops


def _record(monkeypatch):
    calls = []
    monkeypatch.setattr(docker_ops, "_run", lambda cmd: calls.append(cmd) or "")
    return calls


def test_ensure_attach_dir_sets_the_owner_without_a_group(monkeypatch):
    """The SQL Server 2019 image has no `mssql` group, so `chown mssql:mssql`
    fails there with "invalid group". Set the owner only."""
    calls = _record(monkeypatch)
    docker_ops.ensure_attach_dir()

    assert calls[0] == ["docker", "exec", CONTAINER_NAME, "mkdir", "-p", CONTAINER_ATTACH_PATH]
    chown = [c for c in calls if "chown" in c]
    assert chown, calls
    assert chown[0][-1] == CONTAINER_ATTACH_PATH
    assert chown[0][-2] == "mssql"
    assert not any("mssql:mssql" in " ".join(c) for c in calls)


def test_copy_into_container_lands_in_the_attach_dir(monkeypatch):
    calls = _record(monkeypatch)
    docker_ops.copy_into_container("/host/A325.mdf", "A325.mdf")

    cp = [c for c in calls if c[1] == "cp"]
    assert cp == [["docker", "cp", "/host/A325.mdf",
                   f"{CONTAINER_NAME}:{CONTAINER_ATTACH_PATH}/A325.mdf"]]
    chown = [c for c in calls if "chown" in c]
    assert chown[-1][-1] == f"{CONTAINER_ATTACH_PATH}/A325.mdf"
    assert chown[-1][-2] == "mssql"
