# app/reports/exporters/sj_cards.py
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Tuple

from openpyxl import Workbook

from app.logger import logger
from app.database import get_terrain_connection
from app.reports.context import ReportContext

from app.queries import (
    report_sj_cards_list_sj_sql,
    report_sj_cards_detail_sql,
    report_sj_cards_media_ids_sql,
)

from .utils_excel import set_basic_column_widths
from .utils_media import MEDIA_KINDS, list_files_for_media_id
from .utils_sql import dump_table_inserts


class SjCardsExporter:
    export_id = "sj_cards"

    def _fetch_sj_ids(self, ctx: ReportContext) -> List[int]:
        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(report_sj_cards_list_sj_sql())
                return [int(r[0]) for r in cur.fetchall()]

    def _fetch_sj_detail(self, conn, sj_id: int) -> Dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute(report_sj_cards_detail_sql(), (sj_id,))
            row = cur.fetchone()
            if not row:
                return {}
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    def _fetch_media_ids(self, conn, sj_id: int, kind: str) -> List[str]:
        with conn.cursor() as cur:
            cur.execute(report_sj_cards_media_ids_sql(kind), (sj_id,))
            return [str(r[0]) for r in cur.fetchall()]

    # -------------------------
    # Excel
    # -------------------------
    def to_xlsx(self, ctx: ReportContext) -> bytes:
        sj_ids = self._fetch_sj_ids(ctx)
        logger.info(f"[{ctx.selected_db}] Export XLSX sj_cards: {len(sj_ids)} SJs lang={ctx.lang}")

        wb = Workbook()
        ws = wb.active
        ws.title = "SJs"

        headers = [
            "id_sj", "sj_typ", "sj_subtype",
            "author", "recorded",
            "docu_plan", "docu_vertical", "ref_object",
            "description", "interpretation",
            "strat_above", "strat_below", "strat_equal",
            # deposit
            "deposit_typ", "deposit_color", "deposit_boundary_visibility", "deposit_structure",
            "deposit_compactness", "deposit_removed",
            # negativ
            "negativ_typ", "negativ_excav_extent", "negativ_ident_niveau_cut", "negativ_shape_plan",
            "negativ_shape_sides", "negativ_shape_bottom",
            # structure
            "structure_typ", "structure_construction_typ", "structure_binder", "structure_basic_material",
            "structure_length_m", "structure_width_m", "structure_height_m",
            # media filenames (comma-separated)
            "photos_files", "drawings_files", "sketches_files", "photograms_files",
        ]
        ws.append(headers)

        with get_terrain_connection(ctx.selected_db) as conn:
            for sj_id in sj_ids:
                sj = self._fetch_sj_detail(conn, sj_id)
                if not sj:
                    continue

                media_files: Dict[str, str] = {}
                for kind in MEDIA_KINDS:
                    ids = self._fetch_media_ids(conn, sj_id, kind)
                    files: List[str] = []
                    for mid in ids:
                        files.extend(list_files_for_media_id(ctx, kind, mid))
                    media_files[kind] = ", ".join(files)

                row = [
                    sj.get("id_sj"),
                    sj.get("sj_typ"),
                    sj.get("sj_subtype"),
                    sj.get("author"),
                    sj.get("recorded"),
                    sj.get("docu_plan"),
                    sj.get("docu_vertical"),
                    sj.get("ref_object"),
                    sj.get("description"),
                    sj.get("interpretation"),
                    sj.get("strat_above"),
                    sj.get("strat_below"),
                    sj.get("strat_equal"),

                    sj.get("deposit_typ"),
                    sj.get("deposit_color"),
                    sj.get("deposit_boundary_visibility"),
                    sj.get("deposit_structure"),
                    sj.get("deposit_compactness"),
                    sj.get("deposit_removed"),

                    sj.get("negativ_typ"),
                    sj.get("negativ_excav_extent"),
                    sj.get("negativ_ident_niveau_cut"),
                    sj.get("negativ_shape_plan"),
                    sj.get("negativ_shape_sides"),
                    sj.get("negativ_shape_bottom"),

                    sj.get("structure_typ"),
                    sj.get("structure_construction_typ"),
                    sj.get("structure_binder"),
                    sj.get("structure_basic_material"),
                    sj.get("structure_length_m"),
                    sj.get("structure_width_m"),
                    sj.get("structure_height_m"),

                    media_files.get("photos", ""),
                    media_files.get("drawings", ""),
                    media_files.get("sketches", ""),
                    media_files.get("photograms", ""),
                ]
                ws.append(row)

        set_basic_column_widths(ws, headers)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # -------------------------
    # SQL
    # -------------------------
    def to_sql(self, ctx: ReportContext) -> str:
        sj_ids = self._fetch_sj_ids(ctx)
        logger.info(f"[{ctx.selected_db}] Export SQL sj_cards: {len(sj_ids)} SJs")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = [
            f"-- ArcheoDB export: sj_cards",
            f"-- Database: {ctx.selected_db}",
            f"-- Generated: {ts}",
            f"-- NOTE: data-only dump (INSERTs). No binaries included.",
            "",
            "BEGIN;",
            "",
        ]

        if not sj_ids:
            return "\n".join(header + ["COMMIT;", ""])

        id_list = list(map(int, sj_ids))

        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                out: List[str] = header[:]

                out.append(dump_table_inserts(cur, "tab_sj", "WHERE id_sj = ANY(%s)", (id_list,)))
                out.append(dump_table_inserts(cur, "tab_sj_deposit", "WHERE id_deposit = ANY(%s)", (id_list,)))
                out.append(dump_table_inserts(cur, "tab_sj_negativ", "WHERE id_negativ = ANY(%s)", (id_list,)))
                out.append(dump_table_inserts(cur, "tab_sj_structure", "WHERE id_structure = ANY(%s)", (id_list,)))

                out.append(dump_table_inserts(
                    cur,
                    "tab_sj_stratigraphy",
                    "WHERE ref_sj1 = ANY(%s) OR ref_sj2 = ANY(%s)",
                    (id_list, id_list),
                ))

                out.append(dump_table_inserts(cur, "tab_finds", "WHERE ref_sj = ANY(%s)", (id_list,)))
                out.append(dump_table_inserts(cur, "tab_samples", "WHERE ref_sj = ANY(%s)", (id_list,)))

                out.append(dump_table_inserts(cur, "tabaid_photo_sj", "WHERE ref_sj = ANY(%s)", (id_list,)))
                out.append(dump_table_inserts(cur, "tabaid_sj_drawings", "WHERE ref_sj = ANY(%s)", (id_list,)))
                out.append(dump_table_inserts(cur, "tabaid_sj_sketch", "WHERE ref_sj = ANY(%s)", (id_list,)))
                out.append(dump_table_inserts(cur, "tabaid_photogram_sj", "WHERE ref_sj = ANY(%s)", (id_list,)))

                out.append("COMMIT;\n")
                return "\n".join(s for s in out if s)