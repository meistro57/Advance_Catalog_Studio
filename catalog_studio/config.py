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

# Seconds to wait for a login handshake with the scratch container. pymssql
# defaults to 60s, which makes every page look frozen while the container is
# stopped; failing fast lets the UI report the problem instead.
DB_LOGIN_TIMEOUT = 5

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

# SQL Server on-disk file version Advance Steel 2026 writes and can read.
# Every AS 2026 export seen so far is 904 (SQL Server 2019). Attaching a file to
# a newer server upgrades it in place (2022 = 957) and there is no downgrade:
# Advance Steel then refuses the import with "Source database is older than
# Release 5.1!". Run the scratch container on SQL Server 2019 so attach,
# edit and detach keep the file at 904. See README "Start the scratch SQL Server".
AS_SQL_FILE_VERSION = 904
AS_SQL_SERVER_LABEL = "SQL Server 2019"
SCRATCH_SQL_IMAGE = "mcr.microsoft.com/mssql/server:2019-latest"
SQL_FILE_VERSIONS = {
    852: "SQL Server 2016", 869: "SQL Server 2017", 904: "SQL Server 2019",
    957: "SQL Server 2022", 998: "SQL Server 2025",
}

METADATA_FILE = os.path.join(BASE_DIR, "catalog_metadata.json")

# Where bug reports and feature requests go; linked from the navigation bar.
ISSUES_URL = "https://github.com/meistro57/Advance_Catalog_Studio/issues"

# Pre-change .bak snapshots of scratch databases. Runtime only; git-ignored.
SNAPSHOT_DIR = os.path.join(BASE_DIR, "snapshots")
