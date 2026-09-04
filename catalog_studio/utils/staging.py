# utils/staging.py
"""Manages the uploads/ and exports/ folders — pairing mdf+ldf files and
suggesting a clean database name from the filename."""

import os
import re

from config import UPLOAD_DIR, EXPORT_DIR


def list_staged_pairs():
    """Return [{base, mdf, ldf}] for every .mdf in uploads/, paired with a
    same-basename .ldf if one exists."""
    files = os.listdir(UPLOAD_DIR)
    mdfs = [f for f in files if f.lower().endswith(".mdf")]
    pairs = []
    for mdf in sorted(mdfs):
        base = mdf[:-4]
        ldf_candidate = base + "_log.ldf"
        ldf = ldf_candidate if ldf_candidate in files else None
        if ldf is None:
            alt = base + ".ldf"
            ldf = alt if alt in files else None
        pairs.append({"base": base, "mdf": mdf, "ldf": ldf})
    return pairs


def suggest_db_name(base: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "", base)
    return name or "Catalog"


def list_exports():
    return sorted(os.listdir(EXPORT_DIR))
