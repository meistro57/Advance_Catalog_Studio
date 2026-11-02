"""Unit tests for pre-change database snapshots (data-safety rule).

No SQL Server or Docker needed: the backup and docker copy are patched, so the
naming, manifest and failure behaviour are exercised directly.
"""

import datetime
import json
import os

import pytest

from utils import snapshots


FIXED_NOW = datetime.datetime(2026, 11, 2, 12, 30, 45, tzinfo=datetime.timezone.utc)


def test_snapshot_filename_is_timestamped_and_sluggish():
    assert snapshots.snapshot_filename("A325TC_mark", "add diameter 12 mm", FIXED_NOW) == \
        "A325TC_mark_20261102T123045Z_add-diameter-12-mm.bak"


def test_snapshot_filename_sanitises_and_limits_the_reason():
    name = snapshots.snapshot_filename("DB", "  find/replace 'x'  " * 5, FIXED_NOW)
    assert name.startswith("DB_20261102T123045Z_")
    assert "/" not in name and "'" not in name and " " not in name
    assert len(name.split("_", 2)[2]) <= len("find-replace-x") * 5


def test_snapshot_filename_without_reason_uses_manual():
    assert snapshots.snapshot_filename("DB", "", FIXED_NOW) == \
        "DB_20261102T123045Z_manual.bak"


def test_create_snapshot_rejects_an_invalid_database_name(monkeypatch):
    with pytest.raises(ValueError):
        snapshots.create_snapshot("bad name; drop", "x")


def test_create_snapshot_backs_up_copies_and_writes_a_manifest(monkeypatch, tmp_path):
    calls = {}

    def fake_backup(database, container_path, label="x"):
        calls["backup"] = (database, container_path, label)

    def fake_copy(container_path, host_path):
        calls["copy"] = (container_path, host_path)
        os.makedirs(os.path.dirname(host_path), exist_ok=True)
        with open(host_path, "wb") as handle:
            handle.write(b"B" * 32)

    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setattr("utils.db.backup_database", fake_backup)
    monkeypatch.setattr("utils.db.guess_catalog_type", lambda database: "bolt")
    monkeypatch.setattr("utils.docker_ops.copy_out_of_container", fake_copy)
    monkeypatch.setattr("utils.docker_ops.remove_in_container", lambda path: None)

    info = snapshots.create_snapshot("A325TC_mark", "add diameter 12 mm", FIXED_NOW)

    assert calls["backup"][0] == "A325TC_mark"
    assert calls["backup"][1].endswith("A325TC_mark_20261102T123045Z_add-diameter-12-mm.bak")
    assert calls["copy"][0] == calls["backup"][1]
    assert info["filename"].endswith(".bak")
    assert info["size_bytes"] == 32
    manifest = json.loads(open(info["manifest"], encoding="utf-8").read())
    assert manifest["database"] == "A325TC_mark"
    assert manifest["catalog_type"] == "bolt"
    assert manifest["reason"] == "add diameter 12 mm"
    assert "COPY_ONLY" in manifest["note"]


def test_create_snapshot_propagates_a_backup_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))

    def fail(*args, **kwargs):
        raise RuntimeError("BACKUP failed")

    monkeypatch.setattr("utils.db.backup_database", fail)
    with pytest.raises(RuntimeError, match="BACKUP failed"):
        snapshots.create_snapshot("A325TC_mark", "x", FIXED_NOW)
    assert not list(tmp_path.rglob("*.json"))


def test_create_snapshot_propagates_a_copy_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setattr("utils.db.backup_database", lambda *a, **k: None)

    def fail_copy(*args, **kwargs):
        raise RuntimeError("docker cp failed")

    monkeypatch.setattr("utils.docker_ops.copy_out_of_container", fail_copy)
    with pytest.raises(RuntimeError, match="docker cp failed"):
        snapshots.create_snapshot("A325TC_mark", "x", FIXED_NOW)


def test_list_snapshots_reads_manifests_newest_first(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    directory = tmp_path / "DB"
    directory.mkdir()
    for stamp in ("20260101T000000Z", "20260202T000000Z"):
        (directory / f"DB_{stamp}_x.bak.json").write_text(
            json.dumps({"filename": f"DB_{stamp}_x.bak"}), encoding="utf-8")
    (directory / "junk.txt").write_text("ignore", encoding="utf-8")
    found = snapshots.list_snapshots("DB")
    assert [f["filename"] for f in found] == [
        "DB_20260202T000000Z_x.bak", "DB_20260101T000000Z_x.bak"]


def test_list_snapshots_is_empty_without_a_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path / "missing"))
    assert snapshots.list_snapshots("DB") == []


# --- retention --------------------------------------------------------------

def _write_snapshot(tmp_path, database, filename, size=16, reason="batch"):
    directory = tmp_path / database
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(b"S" * size)
    manifest = {
        "database": database,
        "reason": reason,
        "filename": filename,
        "created_utc": "2026-11-02T00:00:00+00:00",
    }
    (directory / (filename + ".json")).write_text(json.dumps(manifest))
    return path


def test_snapshot_files_lists_newest_first(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    _write_snapshot(tmp_path, "DB", "DB_20260101T000000Z_older.bak")
    _write_snapshot(tmp_path, "DB", "DB_20261102T000000Z_newer.bak")
    names = [item["filename"] for item in snapshots.snapshot_files("DB")]
    assert names == ["DB_20261102T000000Z_newer.bak", "DB_20260101T000000Z_older.bak"]
    assert snapshots.snapshot_files("MISSING") == []


def test_snapshot_files_tolerates_a_missing_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    directory = tmp_path / "DB"
    directory.mkdir()
    (directory / "DB_20260101T000000Z_manual.bak").write_bytes(b"S")
    [item] = snapshots.snapshot_files("DB")
    assert item["has_manifest"] is False and item["reason"] is None


def test_prune_keeps_the_newest_n_and_deletes_the_rest(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    names = [f"DB_2026110{day}T000000Z_run.bak" for day in range(1, 8)]
    for name in names:
        _write_snapshot(tmp_path, "DB", name, size=10)

    result = snapshots.prune_snapshots("DB", keep=3)

    assert result["kept"] == 3
    assert [item["filename"] for item in result["removed"]] == list(reversed(names[:4]))
    assert result["bytes_freed"] == 40
    remaining = [item["filename"] for item in snapshots.snapshot_files("DB")]
    assert remaining == list(reversed(names[4:]))
    directory = tmp_path / "DB"
    assert not (directory / (names[0] + ".json")).exists()


def test_prune_is_a_no_op_when_within_the_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    _write_snapshot(tmp_path, "DB", "DB_20261101T000000Z_run.bak")
    result = snapshots.prune_snapshots("DB", keep=5)
    assert result == {"kept": 1, "removed": [], "bytes_freed": 0}


def test_prune_requires_keeping_at_least_one(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        snapshots.prune_snapshots("DB", keep=0)


def test_delete_snapshot_rejects_names_outside_the_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    _write_snapshot(tmp_path, "DB", "DB_20261101T000000Z_run.bak")
    with pytest.raises(ValueError):
        snapshots.delete_snapshot("DB", "../../evil.bak")
    assert snapshots.snapshot_files("DB")


def test_restore_plan_documents_the_manual_restore(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    _write_snapshot(tmp_path, "DB", "DB_20261101T000000Z_run.bak")
    plan = snapshots.restore_plan("DB", "DB_20261101T000000Z_run.bak")

    assert plan["container_path"] == "/var/opt/mssql/data/DB_20261101T000000Z_run.bak"
    assert "docker cp" in plan["docker_command"]
    assert plan["statements"][0].startswith("ALTER DATABASE [DB] SET SINGLE_USER")
    assert "RESTORE DATABASE [DB] FROM DISK" in plan["statements"][1]
    assert plan["statements"][2].endswith("SET MULTI_USER;")


def test_restore_plan_rejects_unknown_and_invalid_names(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshots.config, "SNAPSHOT_DIR", str(tmp_path))
    _write_snapshot(tmp_path, "DB", "DB_20261101T000000Z_run.bak")
    with pytest.raises(ValueError):
        snapshots.restore_plan("DB", "other.bak")
    with pytest.raises(ValueError):
        snapshots.restore_plan("bad name", "DB_20261101T000000Z_run.bak")
