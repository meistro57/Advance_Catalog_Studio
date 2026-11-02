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
