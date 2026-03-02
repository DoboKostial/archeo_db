# app/reports/exporters/geopts_table.py
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List

from openpyxl import Workbook

from app.logger import logger
from app.database import get_terrain_connection
from app.reports.context import ReportContext

from app.queries import (
    report_geopts_list_all_sql,
)

from .utils_excel import set_basic_column_widths
from .utils_sql import dump_table_inserts


class GeoptsTableExporter:
    export_id = "geopts_table"

    def to_xlsx(self, ctx: ReportContext) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "Geopts"

        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(report_geopts_list_all_sql())
                rows = cur.fetchall()
                headers = [d[0] for d in cur.description]

        ws.append(headers)
        for r in rows:
            ws.append(list(r))

        set_basic_column_widths(ws, headers)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def to_sql(self, ctx: ReportContext) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out = [
            "-- ArcheoDB export: geopts_table",
            f"-- Database: {ctx.selected_db}",
            f"-- Generated: {ts}",
            "-- NOTE: data-only dump (INSERTs). No binaries included.",
            "",
            "BEGIN;",
            "",
        ]

        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                out.append(dump_table_inserts(cur, "tab_geopts", "", ()))

        out.append("COMMIT;\n")
        return "\n".join(s for s in out if s)