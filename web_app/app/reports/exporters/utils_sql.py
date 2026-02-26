# app/reports/exporters/utils_sql.py
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Tuple


def sql_quote(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, datetime):
        return "'" + v.isoformat(sep=" ", timespec="seconds") + "'"
    s = str(v)
    s = s.replace("\\", "\\\\").replace("'", "''")
    return f"'{s}'"


def dump_table_inserts(cur, table: str, where_sql: str, params: Tuple[Any, ...]) -> str:
    """
    Dump rows from table as INSERT statements using SELECT * column order.
    """
    cur.execute(f"SELECT * FROM {table} {where_sql};", params)
    rows = cur.fetchall()
    if not rows:
        return ""

    cols = [d[0] for d in cur.description]
    cols_sql = ", ".join(cols)

    out_lines: List[str] = []
    for r in rows:
        values_sql = ", ".join(sql_quote(v) for v in r)
        out_lines.append(f"INSERT INTO {table} ({cols_sql}) VALUES ({values_sql});")
    return "\n".join(out_lines) + "\n"


def dump_table_inserts_columns(cur, table: str, columns: List[str], where_sql: str, params: Tuple[Any, ...]) -> str:
    """
    Dump rows from table as INSERT statements for explicit columns (allows excluding geometry, blobs, etc).
    """
    cols_sql = ", ".join(columns)
    cur.execute(f"SELECT {cols_sql} FROM {table} {where_sql};", params)
    rows = cur.fetchall()
    if not rows:
        return ""

    out_lines: List[str] = []
    for r in rows:
        values_sql = ", ".join(sql_quote(v) for v in r)
        out_lines.append(f"INSERT INTO {table} ({cols_sql}) VALUES ({values_sql});")
    return "\n".join(out_lines) + "\n"