# utils/metadata.py
"""Tracks catalog type (anchor/bolt) and Advance Steel version per attached
database. Stored as a local JSON sidecar -- NOT written into the mdf itself,
since we don't want extra tables Advance Steel's importer wouldn't expect."""

import json
import os
import threading

from config import METADATA_FILE

_lock = threading.Lock()

# Advance Steel ships these libraries; they are delivered templates, so the
# tool must treat anything attached from them as read-only (see AGENTS.md,
# "Database roles").
LIBRARY_FILES = {
    "astordetails": "delivered templates/styles library",
    "astordetailsbase": "delivered drawing-style lookup library",
    "astoraddin": "user overrides library",
    "astorbase": "delivered fasteners library",
    "astorsettings": "delivered global defaults library",
}


def library_kind(mdf_filename: str):
    """Library name when the attachment came from a delivered Astor*.mdf file."""
    base = os.path.splitext(os.path.basename(str(mdf_filename or "")))[0]
    return base.strip().lower() if base.strip().lower() in LIBRARY_FILES else None


def library_label(kind: str):
    return LIBRARY_FILES.get(str(kind or "").lower())


def _load() -> dict:
    if not os.path.exists(METADATA_FILE):
        return {}
    with open(METADATA_FILE, "r") as f:
        return json.load(f)


def _save(data: dict):
    with open(METADATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get(database: str) -> dict:
    return _load().get(database, {})


def set_meta(database: str, catalog_type: str = None, as_version: int = None,
             library: str = None):
    with _lock:
        data = _load()
        entry = data.get(database, {})
        if catalog_type is not None:
            entry["catalog_type"] = catalog_type
        if as_version is not None:
            entry["as_version"] = as_version
        if library is not None:
            entry["library"] = library
        data[database] = entry
        _save(data)


def remove(database: str):
    with _lock:
        data = _load()
        data.pop(database, None)
        _save(data)


def all_meta() -> dict:
    return _load()
