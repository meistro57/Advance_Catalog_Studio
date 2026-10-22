"""Generic table-browsing/edit support for arbitrary SQL Server schemas.

Used by the Drawing Styles module but intentionally schema-agnostic.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from utils import db


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    data_type: str
    max_length: int | None
    is_nullable: bool


@dataclass
class PendingEdit:
    table: str
    pk: dict[str, Any]
    changes: dict[str, Any]


class ChangeLog:
    """Small in-memory pending edit log with undo support."""

    def __init__(self):
        self._items: list[PendingEdit] = []

    def add(self, item: PendingEdit) -> None:
        self._items.append(item)

    def undo_last(self) -> PendingEdit | None:
        if not self._items:
            return None
        return self._items.pop()

    def as_list(self) -> list[PendingEdit]:
        return list(self._items)

    def clear(self) -> None:
        self._items.clear()


def list_tables_with_counts(database: str) -> list[dict[str, Any]]:
    tables = db.list_tables(database)
    return [{"name": t, "row_count": db.get_row_count(database, t)} for t in tables]


def get_primary_key_columns(database: str, table: str) -> list[str]:
    conn, cur = db.connect(database)
    cur.execute(
        """
        SELECT c.name, ic.key_ordinal
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        JOIN sys.tables t ON t.object_id = i.object_id
        WHERE t.name = %s AND i.is_primary_key = 1
        ORDER BY ic.key_ordinal
        """,
        (table,),
    )
    rows = cur.fetchall()
    conn.close()
    if rows:
        return [r["name"] for r in rows]
    cols = [c["COLUMN_NAME"] for c in db.get_columns(database, table)]
    return ["ID"] if "ID" in cols else []


def get_column_specs(database: str, table: str) -> list[ColumnSpec]:
    conn, cur = db.connect(database)
    cur.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table,),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        ColumnSpec(
            name=r["COLUMN_NAME"],
            data_type=r["DATA_TYPE"],
            max_length=r["CHARACTER_MAXIMUM_LENGTH"],
            is_nullable=(r["IS_NULLABLE"] == "YES"),
        )
        for r in rows
    ]


def _escape_like(value: str) -> str:
    return value.replace("[", "[[]").replace("%", "[%]").replace("_", "[_]")


def fetch_table_page(
    database: str,
    table: str,
    page: int,
    page_size: int,
    sort_col: str | None,
    sort_dir: str,
    search: str,
) -> dict[str, Any]:
    specs = get_column_specs(database, table)
    col_names = [c.name for c in specs]
    pk_cols = get_primary_key_columns(database, table)

    order_col = sort_col if sort_col in col_names else (pk_cols[0] if pk_cols else col_names[0])
    order_dir = "DESC" if (sort_dir or "").upper() == "DESC" else "ASC"

    search_cols = [c.name for c in specs if c.data_type in {"nvarchar", "varchar", "nchar", "char", "text", "ntext"}]
    where = ""
    params: list[Any] = []
    if search and search_cols:
        clauses = [f"CAST([{c}] AS NVARCHAR(MAX)) LIKE %s" for c in search_cols]
        where = " WHERE " + " OR ".join(clauses)
        params.extend([f"%{_escape_like(search)}%"] * len(search_cols))

    conn, cur = db.connect(database)
    cur.execute(f"SELECT COUNT(*) AS cnt FROM [{table}]" + where, tuple(params))
    total = int(cur.fetchone()["cnt"])

    page = max(1, int(page or 1))
    page_size = min(200, max(10, int(page_size or 50)))
    offset = (page - 1) * page_size
    cur.execute(
        f"""
        SELECT * FROM [{table}]
        {where}
        ORDER BY [{order_col}] {order_dir}
        OFFSET %s ROWS FETCH NEXT %s ROWS ONLY
        """,
        tuple(params + [offset, page_size]),
    )
    rows = cur.fetchall()
    conn.close()

    return {
        "columns": col_names,
        "column_specs": specs,
        "pk_columns": pk_cols,
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size) if page_size else 1),
        "sort_col": order_col,
        "sort_dir": order_dir,
        "search": search,
    }


def coerce_and_validate(raw: str | None, spec: ColumnSpec):
    if raw is None:
        raw = ""
    if raw == "":
        if spec.is_nullable:
            return None
        if spec.data_type == "bit":
            return 0
        raise ValueError(f"{spec.name} is required")

    val = raw.strip() if isinstance(raw, str) else raw
    t = spec.data_type
    if t in {"int", "bigint", "smallint", "tinyint"}:
        return int(val)
    if t in {"float", "real", "decimal", "numeric", "money", "smallmoney"}:
        return float(val)
    if t == "bit":
        lowered = str(val).strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return 1
        if lowered in {"0", "false", "no", "off"}:
            return 0
        raise ValueError(f"{spec.name} must be 0/1/true/false")

    if isinstance(val, str) and spec.max_length and spec.max_length > 0 and len(val) > spec.max_length:
        raise ValueError(f"{spec.name} exceeds max length {spec.max_length}")
    return val


def apply_updates_by_pk(database: str, table: str, pk: dict[str, Any], updates: dict[str, Any]) -> None:
    if not pk:
        raise ValueError("Primary key values are required")
    if not updates:
        return
    set_clause = ", ".join(f"[{c}] = %s" for c in updates.keys())
    where_clause = " AND ".join(f"[{c}] = %s" for c in pk.keys())
    params = list(updates.values()) + list(pk.values())

    conn, cur = db.connect(database)
    cur.execute(f"UPDATE [{table}] SET {set_clause} WHERE {where_clause}", tuple(params))
    conn.close()


def fetch_row_by_pk(database: str, table: str, pk: dict[str, Any]) -> dict[str, Any] | None:
    if not pk:
        return None
    where_clause = " AND ".join(f"[{c}] = %s" for c in pk.keys())
    params = list(pk.values())
    conn, cur = db.connect(database)
    cur.execute(f"SELECT TOP 1 * FROM [{table}] WHERE {where_clause}", tuple(params))
    row = cur.fetchone()
    conn.close()
    return row


def sanitize_export_basename(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip())
    clean = clean.strip(".-_")
    return clean or "catalog-export"
