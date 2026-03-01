# app/reports/exporters/samples_table.py
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List

from openpyxl import Workbook

from app.logger import logger
from app.database import get_terrain_connection
from app.reports.context import ReportContext

from app.queries import (
    report_samples_list_all_sql,
    report_samples_media_ids_sql,
)

from .utils_excel import set_basic_column_widths
from .utils_media import list_files_for_media_id
from .utils_sql import dump_table_inserts


class SamplesTableExporter:
    export_id = "samples_table"

    def _fetch_samples(self, ctx: ReportContext) -> List[Dict[str, Any]]:
        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(report_samples_list_all_sql())
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    def _fetch_media_ids(self, conn, id_sample: int, kind: str) -> List[str]:
        with conn.cursor() as cur:
            cur.execute(report_samples_media_ids_sql(kind), (id_sample,))
            return [str(r[0]).strip() for r in cur.fetchall() if r and r[0] is not None and str(r[0]).strip()]

    def to_xlsx(self, ctx: ReportContext) -> bytes:
        samples = self._fetch_samples(ctx)
        logger.info(f"[{ctx.selected_db}] Export XLSX samples_table: {len(samples)} samples lang={ctx.lang}")

        wb = Workbook()
        ws = wb.active
        ws.title = "Samples"

        headers = [
            "id_sample", "ref_sample_type", "ref_sj",
            "ref_polygon", "ref_geopt", "description",
            "photos_files", "sketches_files",
        ]
        ws.append(headers)

        with get_terrain_connection(ctx.selected_db) as conn:
            for s in samples:
                sid = int(s["id_sample"])
                photo_ids = self._fetch_media_ids(conn, sid, "photos")
                sketch_ids = self._fetch_media_ids(conn, sid, "sketches")

                photo_files: List[str] = []
                for mid in photo_ids:
                    photo_files.extend(list_files_for_media_id(ctx, "photos", mid))

                sketch_files: List[str] = []
                for mid in sketch_ids:
                    sketch_files.extend(list_files_for_media_id(ctx, "sketches", mid))

                ws.append([
                    s.get("id_sample"),
                    s.get("ref_sample_type"),
                    s.get("ref_sj"),
                    s.get("ref_polygon"),
                    s.get("ref_geopt"),
                    s.get("description"),
                    ", ".join(sorted(set(photo_files))),
                    ", ".join(sorted(set(sketch_files))),
                ])

        set_basic_column_widths(ws, headers)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def to_sql(self, ctx: ReportContext) -> str:
        samples = self._fetch_samples(ctx)
        ids = [int(s["id_sample"]) for s in samples]
        logger.info(f"[{ctx.selected_db}] Export SQL samples_table: {len(ids)} samples")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out: List[str] = [
            "-- ArcheoDB export: samples_table",
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
                out.append(dump_table_inserts(cur, "tab_samples", "WHERE id_sample = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_samples_photos", "WHERE ref_sample = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_samples_sketches", "WHERE ref_sample = ANY(%s)", (ids,)))

        out.append("COMMIT;\n")
        return "\n".join(s for s in out if s)