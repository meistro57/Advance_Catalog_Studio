# config.py
"""Configuration for Catalog Studio — ingest/edit/export Advance Steel
component-catalog mdf exports (anchors, bolts, etc.) against a disposable
SQL Server container. Never touches your live Advance Steel install."""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")

# The scratch SQL Server container (same one from tonight's manual session).
CONTAINER_NAME = "hilti-scratch-sql"
CONTAINER_ATTACH_PATH = "/var/opt/mssql/attach"

DB_CONFIG = {
    "server": "127.0.0.1",
    "port": 1433,
    "user": "sa",
    "password": "Scratch2026!Pw",
}

SECRET_KEY = "catalog-studio-dev-key"  # only used for flash messages, local tool

# Max upload size (mdf/ldf pairs can run a few hundred MB for larger catalogs)
MAX_CONTENT_LENGTH = 500 * 1024 * 1024

# Advance Steel version this tool is validated against. Schema shapes have
# already been observed to differ across versions (see integrity_check.py in
# FastenSuite expecting BoltDefinition/AutoLength, which these mdf exports
# don't have) -- so every database we touch gets tagged with the version it
# targets. Only 2026 is supported/tested right now; add more as they're
# verified rather than assuming compatibility.
ADVANCE_STEEL_VERSION = 2026
SUPPORTED_AS_VERSIONS = {2026}

METADATA_FILE = os.path.join(BASE_DIR, "catalog_metadata.json")
