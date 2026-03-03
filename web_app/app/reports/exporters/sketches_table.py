# app/reports/exporters/sketches_table.py
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List

from openpyxl import Workbook

from app.logger import logger
from app.database import get_terrain_connection
from app.reports.context import ReportContext
from app.queries import report_sketches_table_list_all_sql

from .utils_excel import set_basic_column_widths
from .utils_media import list_files_for_media_id
from .utils_sql import dump_table_inserts


class SketchesTableExporter:
    export_id = "sketches_table"

    def _fetch_rows(self, ctx: ReportContext) -> List[Dict[str, Any]]:
        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(report_sketches_table_list_all_sql())
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    def to_xlsx(self, ctx: ReportContext) -> bytes:
        rows = self._fetch_rows(ctx)
        logger.info(f"[{ctx.selected_db}] Export XLSX sketches_table: {len(rows)} sketches lang={ctx.lang}")

        wb = Workbook()
        ws = wb.active
        ws.title = "Sketches"

        headers = [
            "id_sketch", "sketch_typ", "author", "datum", "notes",
            "file_size", "checksum_sha256",
            "find_ids", "sample_ids", "polygon_names",
            "sketch_files",
        ]
        ws.append(headers)

        for s in rows:
            sid = str(s.get("id_sketch") or "").strip()
            files = ", ".join(list_files_for_media_id(ctx, "sketches", sid))

            ws.append([
                s.get("id_sketch"),
                s.get("sketch_typ"),
                s.get("author"),
                s.get("datum"),
                s.get("notes"),
                s.get("file_size"),
                s.get("checksum_sha256"),
                ", ".join(str(x) for x in (s.get("find_ids") or [])),
                ", ".join(str(x) for x in (s.get("sample_ids") or [])),
                ", ".join(str(x) for x in (s.get("polygon_names") or [])),
                files,
            ])

        set_basic_column_widths(ws, headers)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def to_sql(self, ctx: ReportContext) -> str:
        rows = self._fetch_rows(ctx)
        ids = [str(r["id_sketch"]) for r in rows if r.get("id_sketch")]
        logger.info(f"[{ctx.selected_db}] Export SQL sketches_table: {len(ids)} sketches")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out: List[str] = [
            "-- ArcheoDB export: sketches_table",
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
                out.append(dump_table_inserts(cur, "tab_sketches", "WHERE id_sketch = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_finds_sketches", "WHERE ref_sketch = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_samples_sketches", "WHERE ref_sketch = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_polygon_sketches", "WHERE ref_sketch = ANY(%s)", (ids,)))

        out.append("COMMIT;\n")
        return "\n".join(s for s in out if s)