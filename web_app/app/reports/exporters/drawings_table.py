# app/reports/exporters/drawings_table.py
from __future__ import annotations
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List
from openpyxl import Workbook

from app.logger import logger
from app.database import get_terrain_connection
from app.reports.context import ReportContext
from app.queries import report_drawings_table_list_all_sql

from .utils_excel import set_basic_column_widths
from .utils_media import list_files_for_media_id
from .utils_sql import dump_table_inserts


class DrawingsTableExporter:
    export_id = "drawings_table"

    def _fetch_rows(self, ctx: ReportContext) -> List[Dict[str, Any]]:
        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(report_drawings_table_list_all_sql())
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    def to_xlsx(self, ctx: ReportContext) -> bytes:
        rows = self._fetch_rows(ctx)
        logger.info(f"[{ctx.selected_db}] Export XLSX drawings_table: {len(rows)} drawings lang={ctx.lang}")

        wb = Workbook()
        ws = wb.active
        ws.title = "Drawings"

        headers = [
            "id_drawing", "author", "datum", "notes",
            "file_size", "checksum_sha256",
            "sj_ids", "section_ids",
            "drawing_files",
        ]
        ws.append(headers)

        for d in rows:
            did = str(d.get("id_drawing") or "").strip()
            files = ", ".join(list_files_for_media_id(ctx, "drawings", did))

            ws.append([
                d.get("id_drawing"),
                d.get("author"),
                d.get("datum"),
                d.get("notes"),
                d.get("file_size"),
                d.get("checksum_sha256"),
                ", ".join(str(x) for x in (d.get("sj_ids") or [])),
                ", ".join(str(x) for x in (d.get("section_ids") or [])),
                files,
            ])

        set_basic_column_widths(ws, headers)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def to_sql(self, ctx: ReportContext) -> str:
        rows = self._fetch_rows(ctx)
        ids = [str(r["id_drawing"]) for r in rows if r.get("id_drawing")]
        logger.info(f"[{ctx.selected_db}] Export SQL drawings_table: {len(ids)} drawings")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out: List[str] = [
            "-- ArcheoDB export: drawings_table",
            f"-- Database: {ctx.selected_db}",
            f"-- Generated: {ts}",
            "-- NOTE: data-only dump (INSERTs). No binaries included.",
            "",
            "BEGIN;",
            "",
        ]
        if not ids:
            out += ["COMMIT;", ""]
            return "\n".join(out)

        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                out.append(dump_table_inserts(cur, "tab_drawings", "WHERE id_drawing = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_sj_drawings", "WHERE ref_drawing = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_section_drawings", "WHERE ref_drawing = ANY(%s)", (ids,)))

        out.append("COMMIT;\n")
        return "\n".join(s for s in out if s)