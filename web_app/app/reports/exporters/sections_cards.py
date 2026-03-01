# app/reports/exporters/sections_cards.py
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List

from openpyxl import Workbook

from app.logger import logger
from app.database import get_terrain_connection
from app.reports.context import ReportContext

from app.queries import (
    report_sections_cards_list_sections_sql,
    report_sections_cards_detail_sql,
    report_sections_cards_sj_ids_sql,
    report_sections_cards_media_ids_sql,
)

from .utils_excel import set_basic_column_widths
from .utils_media import list_files_for_media_id
from .utils_sql import dump_table_inserts


class SectionsCardsExporter:
    export_id = "sections_cards"

    def _fetch_section_ids(self, ctx: ReportContext) -> List[int]:
        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(report_sections_cards_list_sections_sql())
                return [int(r[0]) for r in cur.fetchall()]

    def _fetch_section_detail(self, conn, sid: int) -> Dict[str, Any]:
        with conn.cursor() as cur:
            # same 4 params as in PDF detail
            cur.execute(report_sections_cards_detail_sql(), (sid, sid, sid, sid))
            row = cur.fetchone()
            if not row:
                return {}
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    def _fetch_sj_ids(self, conn, sid: int) -> List[int]:
        with conn.cursor() as cur:
            cur.execute(report_sections_cards_sj_ids_sql(), (sid,))
            return [int(r[0]) for r in cur.fetchall()]

    def _fetch_media_ids(self, conn, sid: int, kind: str) -> List[str]:
        with conn.cursor() as cur:
            cur.execute(report_sections_cards_media_ids_sql(kind), (sid,))
            return [str(r[0]).strip() for r in cur.fetchall() if r and r[0] is not None and str(r[0]).strip()]

    def to_xlsx(self, ctx: ReportContext) -> bytes:
        section_ids = self._fetch_section_ids(ctx)
        logger.info(f"[{ctx.selected_db}] Export XLSX sections_cards: {len(section_ids)} sections lang={ctx.lang}")

        wb = Workbook()
        ws = wb.active
        ws.title = "Sections"

        headers = [
            "id_section", "section_type", "description",
            "srid_txt", "ranges_txt", "sj_nr",
            "sj_ids",
            "photos_files", "drawings_files", "sketches_files", "photograms_files",
        ]
        ws.append(headers)

        with get_terrain_connection(ctx.selected_db) as conn:
            for sid in section_ids:
                s = self._fetch_section_detail(conn, sid)
                if not s:
                    continue

                sj_ids = self._fetch_sj_ids(conn, sid)

                media_files: Dict[str, str] = {}
                for kind in ("photos", "drawings", "sketches", "photograms"):
                    mids = self._fetch_media_ids(conn, sid, kind)
                    files: List[str] = []
                    for mid in mids:
                        files.extend(list_files_for_media_id(ctx, kind, mid))
                    media_files[kind] = ", ".join(files)

                ws.append([
                    s.get("id_section"),
                    s.get("section_type"),
                    s.get("description"),
                    s.get("srid_txt"),
                    s.get("ranges_txt"),
                    s.get("sj_nr"),
                    ", ".join(str(x) for x in sj_ids),
                    media_files.get("photos", ""),
                    media_files.get("drawings", ""),
                    media_files.get("sketches", ""),
                    media_files.get("photograms", ""),
                ])

        set_basic_column_widths(ws, headers)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def to_sql(self, ctx: ReportContext) -> str:
        section_ids = self._fetch_section_ids(ctx)
        logger.info(f"[{ctx.selected_db}] Export SQL sections_cards: {len(section_ids)} sections")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out: List[str] = [
            "-- ArcheoDB export: sections_cards",
            f"-- Database: {ctx.selected_db}",
            f"-- Generated: {ts}",
            "-- NOTE: data-only dump (INSERTs). No binaries included.",
            "",
            "BEGIN;",
            "",
        ]

        if not section_ids:
            out += ["COMMIT;", ""]
            return "\n".join(out)

        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                out.append(dump_table_inserts(cur, "tab_section", "WHERE id_section = ANY(%s)", (section_ids,)))
                out.append(dump_table_inserts(cur, "tab_section_geopts_binding", "WHERE ref_section = ANY(%s)", (section_ids,)))
                out.append(dump_table_inserts(cur, "tabaid_sj_section", "WHERE ref_section = ANY(%s)", (section_ids,)))

                out.append(dump_table_inserts(cur, "tabaid_section_photos", "WHERE ref_section = ANY(%s)", (section_ids,)))
                out.append(dump_table_inserts(cur, "tabaid_section_drawings", "WHERE ref_section = ANY(%s)", (section_ids,)))
                out.append(dump_table_inserts(cur, "tabaid_section_sketches", "WHERE ref_section = ANY(%s)", (section_ids,)))
                out.append(dump_table_inserts(cur, "tabaid_section_photograms", "WHERE ref_section = ANY(%s)", (section_ids,)))

        out.append("COMMIT;\n")
        return "\n".join(s for s in out if s)