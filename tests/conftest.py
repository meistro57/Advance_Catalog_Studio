import os
import sys

# utils modules import siblings as top-level packages ("from config import ..."),
# so the catalog_studio directory must be on sys.path (same trick as running
# `python catalog_studio/app.py`, where Python prepends the script dir).
CATALOG_STUDIO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "catalog_studio"))
if CATALOG_STUDIO not in sys.path:
    sys.path.insert(0, CATALOG_STUDIO)
