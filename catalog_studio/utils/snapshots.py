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
