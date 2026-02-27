# app/reports/exporters/objects_cards.py
from __future__ import annotations
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional
from openpyxl import Workbook

from app.logger import logger
from app.database import get_terrain_connection
from app.reports.context import ReportContext

from app.queries import (
    report_objects_cards_list_objects_sql,
    report_objects_cards_detail_sql,
    report_objects_cards_inhum_grave_sql,
    report_sj_cards_media_ids_sql,
)

from .utils_excel import set_basic_column_widths
from .utils_media import MEDIA_KINDS, list_files_for_media_id
from .utils_sql import dump_table_inserts


class ObjectsCardsExporter:
    export_id = "objects_cards"

    def _fetch_object_ids(self, ctx: ReportContext) -> List[int]:
        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(report_objects_cards_list_objects_sql())
                return [int(r[0]) for r in cur.fetchall()]

    def _fetch_object_detail(self, conn, id_object: int) -> Dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute(report_objects_cards_detail_sql(), (id_object,))
            row = cur.fetchone()
            if not row:
                return {}
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    def _fetch_inhum(self, conn, id_object: int) -> Optional[Dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(report_objects_cards_inhum_grave_sql(), (id_object,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    def _aggregate_media_files_for_object(self, ctx: ReportContext, conn, sj_ids: List[int], kind: str) -> str:
        seen = set()
        files: List[str] = []
        for sj_id in sj_ids:
            with conn.cursor() as cur:
                cur.execute(report_sj_cards_media_ids_sql(kind), (sj_id,))
                mids = [str(r[0]) for r in cur.fetchall()]
            for mid in mids:
                if mid in seen:
                    continue
                seen.add(mid)
                files.extend(list_files_for_media_id(ctx, kind, mid))
        # keep it bounded
        return ", ".join(sorted(set(files))[:300])

    # -------------------------
    # Excel
    # -------------------------
    def to_xlsx(self, ctx: ReportContext) -> bytes:
        obj_ids = self._fetch_object_ids(ctx)
        logger.info(f"[{ctx.selected_db}] Export XLSX objects_cards: {len(obj_ids)} objects lang={ctx.lang}")

        wb = Workbook()
        ws = wb.active
        ws.title = "Objects"

        headers = [
            "id_object", "object_typ", "superior_object", "notes",
            "sj_count", "sj_ids",
            "inhum_present", "inhum_preservation", "inhum_orientation_dir",
            "inhum_burial_box_type", "inhum_anthropo_present",
            "inhum_notes_grave", "inhum_bone_map",
            "photos_files", "drawings_files", "sketches_files", "photograms_files",
        ]
        ws.append(headers)

        ws_links = wb.create_sheet("Object_SJ")
        ws_links.append(["id_object", "id_sj"])

        with get_terrain_connection(ctx.selected_db) as conn:
            for oid in obj_ids:
                o = self._fetch_object_detail(conn, oid)
                if not o:
                    continue
                sj_ids = o.get("sj_ids") or []
                inhum = self._fetch_inhum(conn, oid)

                # links
                for sj_id in sj_ids:
                    ws_links.append([oid, sj_id])

                # aggregated media
                media_files = {
                    "photos": self._aggregate_media_files_for_object(ctx, conn, sj_ids, "photos"),
                    "drawings": self._aggregate_media_files_for_object(ctx, conn, sj_ids, "drawings"),
                    "sketches": self._aggregate_media_files_for_object(ctx, conn, sj_ids, "sketches"),
                    "photograms": self._aggregate_media_files_for_object(ctx, conn, sj_ids, "photograms"),
                }

                ws.append([
                    o.get("id_object"),
                    o.get("object_typ"),
                    o.get("superior_object"),
                    o.get("notes"),
                    len(sj_ids),
                    ", ".join(str(x) for x in sj_ids),

                    bool(inhum),
                    (inhum or {}).get("preservation"),
                    (inhum or {}).get("orientation_dir"),
                    (inhum or {}).get("burial_box_type"),
                    (inhum or {}).get("anthropo_present"),
                    (inhum or {}).get("notes_grave"),
                    (inhum or {}).get("bone_map"),

                    media_files["photos"],
                    media_files["drawings"],
                    media_files["sketches"],
                    media_files["photograms"],
                ])

        set_basic_column_widths(ws, headers)
        set_basic_column_widths(ws_links, ["id_object", "id_sj"])

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # -------------------------
    # SQL
    # -------------------------
    def to_sql(self, ctx: ReportContext) -> str:
        obj_ids = self._fetch_object_ids(ctx)
        logger.info(f"[{ctx.selected_db}] Export SQL objects_cards: {len(obj_ids)} objects")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out: List[str] = [
            "-- ArcheoDB export: objects_cards",
            f"-- Database: {ctx.selected_db}",
            f"-- Generated: {ts}",
            "-- NOTE: data-only dump (INSERTs). No binaries included.",
            "",
            "BEGIN;",
            "",
        ]

        if not obj_ids:
            out += ["COMMIT;", ""]
            return "\n".join(out)

        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                id_list = list(map(int, obj_ids))

                # base objects
                out.append(dump_table_inserts(cur, "tab_object", "WHERE id_object = ANY(%s)", (id_list,)))

                # inhum table
                out.append(dump_table_inserts(cur, "tab_object_inhum_grave", "WHERE id_object = ANY(%s)", (id_list,)))

                # include SJs that belong to these objects (base tab_sj; subtype tables are in sj_cards export)
                out.append(dump_table_inserts(cur, "tab_sj", "WHERE ref_object = ANY(%s)", (id_list,)))

                # include SJ media link tables so object export is “complete-ish”
                out.append(dump_table_inserts(cur, "tabaid_photo_sj", "WHERE ref_sj IN (SELECT id_sj FROM tab_sj WHERE ref_object = ANY(%s))", (id_list,)))
                out.append(dump_table_inserts(cur, "tabaid_sj_drawings", "WHERE ref_sj IN (SELECT id_sj FROM tab_sj WHERE ref_object = ANY(%s))", (id_list,)))
                out.append(dump_table_inserts(cur, "tabaid_sj_sketch", "WHERE ref_sj IN (SELECT id_sj FROM tab_sj WHERE ref_object = ANY(%s))", (id_list,)))
                out.append(dump_table_inserts(cur, "tabaid_photogram_sj", "WHERE ref_sj IN (SELECT id_sj FROM tab_sj WHERE ref_object = ANY(%s))", (id_list,)))

        out.append("COMMIT;\n")
        return "\n".join(s for s in out if s)