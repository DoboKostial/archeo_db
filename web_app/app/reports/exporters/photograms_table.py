# app/reports/exporters/photograms_table.py
from __future__ import annotations
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List
from openpyxl import Workbook
from app.logger import logger
from app.database import get_terrain_connection
from app.reports.context import ReportContext
from app.queries import report_photograms_table_list_all_sql

from .utils_excel import set_basic_column_widths
from .utils_media import list_files_for_media_id
from .utils_sql import dump_table_inserts


class PhotogramsTableExporter:
    export_id = "photograms_table"

    def _fetch_rows(self, ctx: ReportContext) -> List[Dict[str, Any]]:
        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(report_photograms_table_list_all_sql())
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    def to_xlsx(self, ctx: ReportContext) -> bytes:
        rows = self._fetch_rows(ctx)
        logger.info(f"[{ctx.selected_db}] Export XLSX photograms_table: {len(rows)} photograms lang={ctx.lang}")

        wb = Workbook()
        ws = wb.active
        ws.title = "Photograms"

        headers = [
            "id_photogram", "photogram_typ", "ref_sketch", "notes",
            "mime_type", "file_size", "checksum_sha256",
            "ref_photo_from", "ref_photo_to",
            "sj_ids", "section_ids", "polygon_names", "geopt_ranges",
            "photogram_files",
        ]
        ws.append(headers)

        for p in rows:
            pid = str(p.get("id_photogram") or "").strip()
            files = ", ".join(list_files_for_media_id(ctx, "photograms", pid))

            ws.append([
                p.get("id_photogram"),
                p.get("photogram_typ"),
                p.get("ref_sketch"),
                p.get("notes"),
                p.get("mime_type"),
                p.get("file_size"),
                p.get("checksum_sha256"),
                p.get("ref_photo_from"),
                p.get("ref_photo_to"),
                ", ".join(str(x) for x in (p.get("sj_ids") or [])),
                ", ".join(str(x) for x in (p.get("section_ids") or [])),
                ", ".join(str(x) for x in (p.get("polygon_names") or [])),
                ", ".join(str(x) for x in (p.get("geopt_ranges") or [])),
                files,
            ])

        set_basic_column_widths(ws, headers)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def to_sql(self, ctx: ReportContext) -> str:
        rows = self._fetch_rows(ctx)
        ids = [str(r["id_photogram"]) for r in rows if r.get("id_photogram")]
        logger.info(f"[{ctx.selected_db}] Export SQL photograms_table: {len(ids)} photograms")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out: List[str] = [
            "-- ArcheoDB export: photograms_table",
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
                out.append(dump_table_inserts(cur, "tab_photograms", "WHERE id_photogram = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_photogram_geopts", "WHERE ref_photogram = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_photogram_sj", "WHERE ref_photogram = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_polygon_photograms", "WHERE ref_photogram = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_section_photograms", "WHERE ref_photogram = ANY(%s)", (ids,)))

        out.append("COMMIT;\n")
        return "\n".join(s for s in out if s)