# utils/snapshots.py
"""Consistent pre-change snapshots before batch mutations.

Data-safety rule: no batch write (diameter clone, find & replace, and later the
style/stud write paths) runs until a `COPY_ONLY` backup of the scratch database
exists on disk. The snapshot is written by SQL Server inside the container, so
it is transactionally consistent even while the database is attached, then
copied to `catalog_studio/snapshots/<database>/` with a JSON manifest.

This is a safety net for the disposable scratch database, not an Advance Steel
feature: the exported `.mdf` / `.ldf` pair remains the deliverable. Snapshots
are runtime files and are git-ignored.
"""

import datetime
import json
import os
import re

import config
from utils import db, docker_ops

CONTAINER_BACKUP_DIR = config.CONTAINER_ATTACH_PATH
REASON_LIMIT = 40


def snapshot_filename(database: str, reason: str, now=None):
    """`<database>_<UTC timestamp>_<reason slug>.bak`."""
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(reason or "")).strip("-.")[:REASON_LIMIT]
    return f"{database}_{stamp}_{slug or 'manual'}.bak"


def snapshot_dir(database: str):
    return os.path.join(config.SNAPSHOT_DIR, database)


def create_snapshot(database: str, reason: str, now=None):
    """Back up the database and copy the .bak next to a manifest.

    Raises on any failure; callers must not continue with the mutation.
    """
    if not db.valid_identifier(database):
        raise ValueError("Invalid database name.")
    filename = snapshot_filename(database, reason, now)
    container_path = f"{CONTAINER_BACKUP_DIR}/{filename}"
    label = f"Catalog Studio: {str(reason or 'pre-change')}"

    db.backup_database(database, container_path, label)
    directory = snapshot_dir(database)
    os.makedirs(directory, exist_ok=True)
    host_path = os.path.join(directory, filename)
    docker_ops.copy_out_of_container(container_path, host_path)
    try:
        docker_ops.remove_in_container(container_path)
    except Exception:
        # The host copy is the artifact that matters; a leftover .bak in the
        # container is harmless.
        pass

    size = os.path.getsize(host_path)
    try:
        catalog_type = db.guess_catalog_type(database)
    except Exception:
        catalog_type = None
    manifest = {
        "database": database,
        "reason": reason,
        "filename": filename,
        "container_path": container_path,
        "size_bytes": size,
        "catalog_type": catalog_type,
        "created_utc": (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(),
        "note": "COPY_ONLY backup of the disposable scratch database, taken "
                "before a batch mutation. Restore with RESTORE DATABASE ... "
                "FROM DISK if a change has to be undone.",
    }
    manifest_path = os.path.join(directory, filename + ".json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    return {"ok": True, "path": host_path, "filename": filename,
            "manifest": manifest_path, "size_bytes": size,
            "reason": reason, "created_utc": manifest["created_utc"]}


def list_snapshots(database: str):
    """Newest-first snapshots for a database, from their manifests."""
    directory = snapshot_dir(database)
    if not os.path.isdir(directory):
        return []
    found = []
    for name in sorted(os.listdir(directory), reverse=True):
        if not name.endswith(".bak.json"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as handle:
                found.append(json.load(handle))
        except (OSError, ValueError):
            continue
    return found


# --------------------------------------------------------------------------
# Retention (issue: keep the newest N, prune the rest with an explicit action)
# --------------------------------------------------------------------------

DEFAULT_KEEP = 5
RESTORE_DIR = "/var/opt/mssql/data"


def _host_paths(database: str, filename: str):
    """Absolute .bak and manifest paths for one snapshot, never leaving the dir."""
    name = os.path.basename(str(filename or ""))
    if not name.endswith(".bak"):
        raise ValueError("Not a snapshot filename.")
    directory = os.path.realpath(snapshot_dir(database))
    backup = os.path.realpath(os.path.join(directory, name))
    manifest = os.path.realpath(os.path.join(directory, name + ".json"))
    if os.path.dirname(backup) != directory or os.path.dirname(manifest) != directory:
        raise ValueError("Snapshot path escapes the snapshot directory.")
    return backup, manifest


def snapshot_files(database: str):
    """Every snapshot on disk, newest first, including ones without a manifest."""
    directory = snapshot_dir(database)
    if not os.path.isdir(directory):
        return []
    found = []
    for name in sorted(os.listdir(directory), reverse=True):
        if not name.endswith(".bak"):
            continue
        path = os.path.join(directory, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        manifest_path = path + ".json"
        manifest = None
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, encoding="utf-8") as handle:
                    manifest = json.load(handle)
            except (OSError, ValueError):
                manifest = None
        found.append({
            "filename": name,
            "size_bytes": size,
            "reason": (manifest or {}).get("reason"),
            "created_utc": (manifest or {}).get("created_utc"),
            "has_manifest": manifest is not None,
        })
    return found


def delete_snapshot(database: str, filename: str):
    """Remove one snapshot pair. Only names that exist on disk are accepted."""
    known = {item["filename"] for item in snapshot_files(database)}
    name = os.path.basename(str(filename or ""))
    if name not in known:
        raise ValueError("Unknown snapshot.")
    backup, manifest = _host_paths(database, name)
    size = os.path.getsize(backup)
    os.remove(backup)
    if os.path.exists(manifest):
        os.remove(manifest)
    return {"filename": name, "bytes_freed": size}


def prune_snapshots(database: str, keep: int = DEFAULT_KEEP):
    """Keep the newest `keep` snapshots, delete the rest. Explicit action only."""
    if keep < 1:
        raise ValueError("Keep at least one snapshot.")
    snapshots_on_disk = snapshot_files(database)
    stale = snapshots_on_disk[keep:]
    removed = []
    for item in stale:
        removed.append(delete_snapshot(database, item["filename"]))
    return {
        "kept": min(len(snapshots_on_disk), keep),
        "removed": removed,
        "bytes_freed": sum(item["bytes_freed"] for item in removed),
    }


def restore_plan(database: str, filename: str, container_dir: str = RESTORE_DIR):
    """What an operator needs to restore a snapshot by hand.

    Snapshots are copied out of the container and the in-container .bak is
    removed, so a restore starts by copying the file back in. The statements
    are documentation for a manual run -- this module never executes them.
    """
    if not db.valid_identifier(database):
        raise ValueError("Invalid database name.")
    known = {item["filename"] for item in snapshot_files(database)}
    name = os.path.basename(str(filename or ""))
    if name not in known:
        raise ValueError("Unknown snapshot.")
    backup, _ = _host_paths(database, name)
    container_path = f"{container_dir.rstrip('/')}/{name}"
    return {
        "filename": name,
        "host_path": backup,
        "container_path": container_path,
        "docker_command": f"docker cp {backup} {config.CONTAINER_NAME}:{container_path}",
        "statements": [
            f"ALTER DATABASE [{database}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;",
            f"RESTORE DATABASE [{database}] FROM DISK = N'{container_path}' WITH REPLACE;",
            f"ALTER DATABASE [{database}] SET MULTI_USER;",
        ],
    }
