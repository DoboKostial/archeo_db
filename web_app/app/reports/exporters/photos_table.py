# app/reports/exporters/photos_table.py
from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Any, Dict, List

from openpyxl import Workbook

from app.logger import logger
from app.database import get_terrain_connection
from app.reports.context import ReportContext
from app.queries import report_photos_table_list_all_sql

from .utils_excel import set_basic_column_widths
from .utils_media import list_files_for_media_id
from .utils_sql import dump_table_inserts


class PhotosTableExporter:
    export_id = "photos_table"

    @staticmethod
    def _exif_to_text(exif_val: Any) -> str:
        """
        Convert exif_json (jsonb) to a safe Excel cell string.
        psycopg may return dict/list; we store JSON text.
        """
        if exif_val is None or exif_val == "":
            return ""
        if isinstance(exif_val, str):
            return exif_val
        try:
            return json.dumps(exif_val, ensure_ascii=False)
        except Exception:
            return str(exif_val)

    def _fetch_rows(self, ctx: ReportContext) -> List[Dict[str, Any]]:
        with get_terrain_connection(ctx.selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(report_photos_table_list_all_sql())
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    # -------------------------
    # Excel
    # -------------------------
    @staticmethod
    def _dt_to_excel(dt: Any):
        """
        openpyxl does not accept tz-aware datetimes.
        Convert to naive UTC datetime (tzinfo removed).
        If not datetime, return as-is.
        """
        try:
            # datetime has attribute tzinfo
            if dt is None:
                return None
            if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                # normalize to UTC, then drop tzinfo
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            # safest fallback: stringify
            return str(dt)
    

    def to_xlsx(self, ctx: ReportContext) -> bytes:
        rows = self._fetch_rows(ctx)
        logger.info(f"[{ctx.selected_db}] Export XLSX photos_table: {len(rows)} photos lang={ctx.lang}")

        wb = Workbook()
        ws = wb.active
        ws.title = "Photos"

        headers = [
            "id_photo", "photo_typ", "datum", "author", "notes",
            "mime_type", "file_size", "checksum_sha256",
            "shoot_datetime", "gps_lat", "gps_lon", "gps_alt",
            "exif_json", "photo_centroid_wkt",
            "sj_ids", "section_ids", "polygon_names", "find_ids", "sample_ids",
            "photo_files",
        ]
        ws.append(headers)

        for p in rows:
            pid = str(p.get("id_photo") or "").strip()
            photo_files = ", ".join(list_files_for_media_id(ctx, "photos", pid))

            exif_txt = self._exif_to_text(p.get("exif_json"))

            ws.append([
                p.get("id_photo"),
                p.get("photo_typ"),
                p.get("datum"),
                p.get("author"),
                p.get("notes"),
                p.get("mime_type"),
                p.get("file_size"),
                p.get("checksum_sha256"),
                self._dt_to_excel(p.get("shoot_datetime")),
                p.get("gps_lat"),
                p.get("gps_lon"),
                p.get("gps_alt"),
                exif_txt,
                p.get("photo_centroid_wkt"),

                ", ".join(str(x) for x in (p.get("sj_ids") or [])),
                ", ".join(str(x) for x in (p.get("section_ids") or [])),
                ", ".join(str(x) for x in (p.get("polygon_names") or [])),
                ", ".join(str(x) for x in (p.get("find_ids") or [])),
                ", ".join(str(x) for x in (p.get("sample_ids") or [])),

                photo_files,
            ])

        set_basic_column_widths(ws, headers)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # -------------------------
    # SQL
    # -------------------------
    def to_sql(self, ctx: ReportContext) -> str:
        rows = self._fetch_rows(ctx)
        ids = [str(r["id_photo"]) for r in rows if r.get("id_photo")]
        logger.info(f"[{ctx.selected_db}] Export SQL photos_table: {len(ids)} photos")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out: List[str] = [
            "-- ArcheoDB export: photos_table",
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
                out.append(dump_table_inserts(cur, "tab_photos", "WHERE id_photo = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_photo_sj", "WHERE ref_photo = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_section_photos", "WHERE ref_photo = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_polygon_photos", "WHERE ref_photo = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_finds_photos", "WHERE ref_photo = ANY(%s)", (ids,)))
                out.append(dump_table_inserts(cur, "tabaid_samples_photos", "WHERE ref_photo = ANY(%s)", (ids,)))

        out.append("COMMIT;\n")
        return "\n".join(s for s in out if s)