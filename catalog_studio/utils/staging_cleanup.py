# utils/staging_cleanup.py
"""Safe cleanup of the runtime upload staging area (issue #3).

Everything here operates strictly inside the configured upload directory:

- only catalog files (``.mdf`` / ``.ldf``) at the TOP LEVEL of ``UPLOAD_DIR``
  are candidates;
- target names are validated as plain basenames with the allowed extension,
  then resolved and re-checked against the canonical directory so traversal,
  absolute paths, symlinks escaping the staging directory, directories, and
  unexpected extensions are rejected;
- removal is recoverable: files are MOVED into a staging-trash subdirectory
  (``UPLOAD_DIR/.trash``), and only an explicit purge permanently deletes
  trash contents;
- missing files are reported, not fatal; partial failures are reported
  precisely.

This module never touches EXPORT_DIR, repository sample data, the SQL Server
container, or attached databases.
"""

import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)

CATALOG_EXTS = (".mdf", ".ldf")
TRASH_DIR_NAME = ".trash"


class StagingCleanupError(ValueError):
    """Raised for a rejected target or an unsafe operation."""


def _canonical(upload_dir: str) -> str:
    return os.path.realpath(upload_dir)


def validate_name(name: str) -> bool:
    """A valid target is a plain basename with an allowed catalog extension."""
    if not name or not isinstance(name, str):
        return False
    if name != os.path.basename(name):
        return False
    if name.startswith("."):
        return False
    if "/" in name or "\\" in name or ".." in name.split("/"):
        return False
    if not name.lower().endswith(CATALOG_EXTS):
        return False
    return True


def safe_file_path(upload_dir: str, name: str) -> str:
    """Return the resolved path for `name`, rejecting unsafe targets.

    Raises StagingCleanupError unless the file is a regular catalog file whose
    real path stays inside the canonical upload directory.
    """
    if not validate_name(name):
        raise StagingCleanupError(f"Unsafe or unsupported filename: {name!r}")
    root = _canonical(upload_dir)
    candidate = os.path.join(root, name)
    if os.path.islink(candidate):
        raise StagingCleanupError(f"Symlinks are not allowed in staging: {name!r}")
    real = os.path.realpath(candidate)
    if os.path.commonpath([root, real]) != root:
        raise StagingCleanupError(f"Path escapes the staging directory: {name!r}")
    if os.path.isdir(real):
        raise StagingCleanupError(f"Directories are not valid cleanup targets: {name!r}")
    if not os.path.isfile(real):
        # caller decides whether a missing file is an error
        return real
    return real


def list_catalog_files(upload_dir: str) -> list:
    """Top-level catalog files (regular files, allowed extensions)."""
    root = _canonical(upload_dir)
    if not os.path.isdir(root):
        return []
    names = []
    with os.scandir(root) as it:
        for entry in it:
            if entry.is_file() and entry.name.lower().endswith(CATALOG_EXTS):
                names.append(entry.name)
    return sorted(names)



def scan_upload_dir(upload_dir: str) -> dict:
    """Counts and sizes for the confirmation dialog and dashboard badges.

    Returns complete pairs (with optional .ldf), orphaned files, totals, and
    the current trash contents. Never modifies anything.
    """
    root = _canonical(upload_dir)
    files = list_catalog_files(upload_dir)
    sizes = {}
    for name in files:
        try:
            sizes[name] = os.path.getsize(os.path.join(root, name))
        except OSError:
            sizes[name] = 0

    mdfs = [n for n in files if n.lower().endswith(".mdf")]
    ldfs = [n for n in files if n.lower().endswith(".ldf")]

    pairs = []
    orphans = []
    ldf_set = set(ldfs)
    for mdf in mdfs:
        base = mdf[:-4]
        ldf = next(
            (c for c in (base + "_log.ldf", base + ".ldf") if c in ldf_set),
            None,
        )
        if ldf:
            ldf_set.discard(ldf)
            pairs.append({
                "base": base,
                "mdf": mdf,
                "ldf": ldf,
                "bytes": sizes.get(mdf, 0) + sizes.get(ldf, 0),
            })
        else:
            orphans.append(mdf)
    orphans.extend(sorted(ldf_set))  # leftover LDFs with no matching MDF

    total_bytes = sum(sizes.get(n, 0) for n in files)

    trash = _scan_trash(upload_dir)
    return {
        "upload_dir": root,
        "pairs": pairs,
        "orphans": orphans,
        "mdf_count": len(mdfs),
        "ldf_count": len(ldfs),
        "pair_count": len(pairs),
        "orphan_count": len(orphans),
        "total_bytes": total_bytes,
        "trash": trash,
    }


def _scan_trash(upload_dir: str) -> dict:
    trash_root = os.path.join(_canonical(upload_dir), TRASH_DIR_NAME)
    count = 0
    total = 0
    if os.path.isdir(trash_root):
        for dirpath, _dirnames, filenames in os.walk(trash_root):
            for fname in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, fname))
                    count += 1
                except OSError:
                    pass
    return {"count": count, "bytes": total}


def _trash_subdir(upload_dir: str) -> str:
    trash_root = os.path.join(_canonical(upload_dir), TRASH_DIR_NAME)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    sub = os.path.join(trash_root, f"{stamp}-{uuid.uuid4().hex[:8]}")
    os.makedirs(sub, exist_ok=True)
    return sub


def move_to_trash(upload_dir: str, names: list) -> dict:
    """Move the given staged file names into the staging trash.

    `names` are plain filenames of top-level catalog files (normally derived
    from scan_upload_dir on the server). Returns a precise result:
    {"moved": [name], "missing": [name], "rejected": [{name, reason}]}.
    """
    result = {"moved": [], "missing": [], "rejected": []}
    if not names:
        return result
    target_names = [n for n in names if validate_name(n)]
    for name in names:
        if name not in target_names:
            result["rejected"].append({"name": name, "reason": "invalid filename"})
    root = _canonical(upload_dir)
    dest = _trash_subdir(upload_dir)
    for name in target_names:
        try:
            path = safe_file_path(upload_dir, name)
        except StagingCleanupError as exc:
            result["rejected"].append({"name": name, "reason": str(exc)})
            continue
        if not os.path.exists(path):
            result["missing"].append(name)
            continue
        size = os.path.getsize(path)
        os.replace(path, os.path.join(dest, name))
        result["moved"].append(name)
        logger.info(
            "staging cleanup: moved %s (%.1f KiB) to trash %s",
            name, size / 1024.0, os.path.relpath(dest, root),
        )
    return result


def purge_trash(upload_dir: str) -> dict:
    """Permanently empty the staging trash. Returns {"purged": n, "bytes": x}."""
    root = _canonical(upload_dir)
    trash_root = os.path.join(root, TRASH_DIR_NAME)
    real_trash = os.path.realpath(trash_root)
    if not os.path.isdir(real_trash):
        return {"purged": 0, "bytes": 0}
    if os.path.commonpath([root, real_trash]) != root:
        raise StagingCleanupError("Trash directory is outside the staging area.")
    purged = 0
    total = 0
    with os.scandir(real_trash) as it:
        for entry in list(it):
            real = os.path.realpath(entry.path)
            if os.path.commonpath([real_trash, real]) != real_trash:
                logger.warning("staging cleanup: refusing to purge %s", entry.name)
                continue
            if entry.is_dir() and not entry.is_symlink():
                for dirpath, _dn, fnames in os.walk(real):
                    for fname in fnames:
                        try:
                            total += os.path.getsize(os.path.join(dirpath, fname))
                        except OSError:
                            pass
                shutil_rmtree(real)
            else:
                try:
                    total += os.path.getsize(real)
                    os.remove(real)
                except OSError:
                    logger.warning("staging cleanup: could not purge %s", entry.name)
                    continue
            purged += 1
    logger.info("staging cleanup: purged trash (removed %s entries, %.1f KiB)", purged, total / 1024.0)
    return {"purged": purged, "bytes": total}


def shutil_rmtree(path: str):
    # local import keeps the module otherwise free of filesystem helpers
    import shutil
    shutil.rmtree(path)
