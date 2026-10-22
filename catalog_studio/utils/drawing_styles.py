from __future__ import annotations

from typing import Any

from . import db


def list_styles(database: str) -> list[dict[str, Any]]:
    conn, cur = db.connect(database)
    cur.execute(
        """
        SELECT TOP 500 [Key], [RunName], [OwnerText], [Scale], [Visible], [RcpTemplate]
        FROM [AstorAddIn_DrawingStyle]
        ORDER BY [Key]
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_style_bundle(database: str, style_key: int) -> dict[str, Any] | None:
    conn, cur = db.connect(database)
    cur.execute("SELECT TOP 1 * FROM [AstorAddIn_DrawingStyle] WHERE [Key] = %s", (style_key,))
    style = cur.fetchone()
    if not style:
        conn.close()
        return None

    children = {}
    for table in (
        "AstorAddIn_DimStyle",
        "AstorAddIn_LabelStyle",
        "AstorAddIn_ObjectDisplayType",
        "AstorAddIn_Representation",
    ):
        cur.execute(f"SELECT * FROM [{table}] WHERE [StyleID] = %s", (style_key,))
        children[table] = cur.fetchall()

    conn.close()
    return {"style": style, "children": children}


def duplicate_style(database: str, style_key: int, run_name: str, owner_text: str = "DSC") -> dict[str, Any]:
    conn, cur = db.connect(database)
    cur.execute("SELECT TOP 1 * FROM [AstorAddIn_DrawingStyle] WHERE [Key] = %s", (style_key,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError("Source style not found")

    cur.execute("SELECT ISNULL(MAX([Key]), 0) + 1 AS next_key FROM [AstorAddIn_DrawingStyle]")
    new_key = int(cur.fetchone()["next_key"])

    cur.execute(
        """
        INSERT INTO [AstorAddIn_DrawingStyle]
        ([Key],[RunName],[OwnerText],[Scale],[Visible],[RcpTemplate])
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (
            new_key,
            run_name,
            owner_text,
            row.get("Scale"),
            row.get("Visible"),
            row.get("RcpTemplate"),
        ),
    )
    conn.close()
    return {"new_style_key": new_key}


def rename_style(database: str, style_key: int, run_name: str, owner_text: str = "") -> None:
    conn, cur = db.connect(database)
    if owner_text:
        cur.execute(
            "UPDATE [AstorAddIn_DrawingStyle] SET [RunName] = %s, [OwnerText] = %s WHERE [Key] = %s",
            (run_name, owner_text, style_key),
        )
    else:
        cur.execute(
            "UPDATE [AstorAddIn_DrawingStyle] SET [RunName] = %s WHERE [Key] = %s",
            (run_name, style_key),
        )
    conn.close()


def delete_style(database: str, style_key: int) -> None:
    conn, cur = db.connect(database)
    for table in (
        "AstorAddIn_DimStyle",
        "AstorAddIn_LabelStyle",
        "AstorAddIn_ObjectDisplayType",
        "AstorAddIn_Representation",
    ):
        cur.execute(f"DELETE FROM [{table}] WHERE [StyleID] = %s", (style_key,))
    cur.execute("DELETE FROM [AstorAddIn_DrawingStyle] WHERE [Key] = %s", (style_key,))
    conn.close()
