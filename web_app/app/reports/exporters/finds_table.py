# app/reports/exporters/finds_table.py
from __future__ import annotations
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List
from openpyxl import Workbook

from app.logger import logger
from app.database import get_terrain_connection
from app.reports.context import ReportContext

from app.queries import (
    report_finds_list_all_sql,
    report_finds_media_ids_sql,
)

from .utils_excel import set_basic_column_widths
from .utils_media import list_files_for_media_id
from .utils_sql import dump_table_inserts


class FindsTableExporter:
    export_id = "finds_table"

    def _fetch_finds(self, ctx: ReportContext) -> List[Dict[str, Any]]:
        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(report_finds_list_all_sql())
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    def _fetch_media_ids(self, conn, id_find: int, kind: str) -> List[str]:
        with conn.cursor() as cur:
            cur.execute(report_finds_media_ids_sql(kind), (id_find,))
            return [str(r[0]).strip() for r in cur.fetchall() if r and r[0] is not None and str(r[0]).strip()]

    def to_xlsx(self, ctx: ReportContext) -> bytes:
        finds = self._fetch_finds(ctx)
        logger.info(f"[{ctx.selected_db}] Export XLSX finds_table: {len(finds)} finds lang={ctx.lang}")

        wb = Workbook()
        ws = wb.active
        ws.title = "Finds"

        headers = [
            "id_find", "ref_find_type", "ref_sj", "count", "box",
            "ref_polygon", "ref_geopt", "description",
            "photos_files", "sketches_files",
        ]
        ws.append(headers)

        with get_terrain_connection(ctx.selected_db) as conn:
            for f in finds:
                fid = int(f["id_find"])
                photo_ids = self._fetch_media_ids(conn, fid, "photos")
                sketch_ids = self._fetch_media_ids(conn, fid, "sketches")

                photo_files: List[str] = []
                for mid in photo_ids:
                    photo_files.extend(list_files_for_media_id(ctx, "photos", mid))

                sketch_files: List[str] = []
                for mid in sketch_ids:
                    sketch_files.extend(list_files_for_media_id(ctx, "sketches", mid))

                ws.append([
                    f.get("id_find"),
                    f.get("ref_find_type"),
                    f.get("ref_sj"),
                    f.get("count"),
                    f.get("box"),
                    f.get("ref_polygon"),
                    f.get("ref_geopt"),
                    f.get("description"),
                    ", ".join(sorted(set(photo_files))),
                    ", ".join(sorted(set(sketch_files))),
                ])

        set_basic_column_widths(ws, headers)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def to_sql(self, ctx: ReportContext) -> str:
        finds = self._fetch_finds(ctx)
        ids = [int(f["id_find"]) for f in finds]
        logger.info(f"[{ctx.selected_db}] Export SQL finds_table: {len(ids)} finds")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out: List[str] = [
            "-- ArcheoDB export: finds_table",
            f"-- Database: {ctx.selected_db}",
            f"-- Generated: {ts}",
            "-- NOTE: data-only dump (INSERTs). No binaries and DDL included.",
            "",
            "BEGIN;",
            "",
        ]

        if not ids:
            out += ["COMMIT;", ""]
            return "\n".join(out)

        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                out.append(dump_table_inserts(cur, "tab_finds", "WHERE id_find = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_finds_photos", "WHERE ref_find = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_finds_sketches", "WHERE ref_find = ANY(%s)", (ids,)))

        out.append("COMMIT;\n")
        return "\n".join(s for s in out if s)