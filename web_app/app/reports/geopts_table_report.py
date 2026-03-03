# app/reports/geopts_table_report.py
from __future__ import annotations

import io
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.logger import logger
from app.reports.context import ReportContext
from app.database import get_terrain_connection

from app.queries import (
    report_geopts_list_all_sql,
    find_geopts_srid_sql,
    detect_db_srid_typmods_sql,
)


def _register_unicode_fonts() -> Tuple[str, str]:
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        (os.path.join("app", "static", "fonts", "DejaVuSans.ttf"),
         os.path.join("app", "static", "fonts", "DejaVuSans-Bold.ttf")),
        (os.path.join("web_app", "app", "static", "fonts", "DejaVuSans.ttf"),
         os.path.join("web_app", "app", "static", "fonts", "DejaVuSans-Bold.ttf")),
    ]
    for reg_path, bold_path in candidates:
        if os.path.exists(reg_path) and os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont("DejaVuSans", reg_path))
                pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold_path))
                return "DejaVuSans", "DejaVuSans-Bold"
            except Exception as e:
                logger.warning(f"Failed to register DejaVu fonts from {reg_path}: {e}")
    return "Helvetica", "Helvetica-Bold"


FONT_REG, FONT_BOLD = _register_unicode_fonts()
_styles = getSampleStyleSheet()

TITLE = ParagraphStyle("GeoTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=14, leading=16)
SMALL = ParagraphStyle("GeoSmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
CELL = ParagraphStyle("GeoCell", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
HEADER = ParagraphStyle("GeoHeader", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=8, leading=10)


def _v(x: Any) -> str:
    return "—" if x is None or x == "" else str(x)


def _detect_srid(ctx: ReportContext) -> Tuple[str, str]:
    """
    Returns (primary_srid_txt, extra_info_txt)
    """
    with get_terrain_connection(ctx.selected_db) as conn:
        with conn.cursor() as cur:
            # primary: Find_SRID on tab_geopts.pts_geom typmod
            srid = None
            try:
                cur.execute(find_geopts_srid_sql())
                srid = cur.fetchone()[0]
            except Exception:
                srid = None

            # secondary: typmod SRIDs across geometry columns
            detected: List[str] = []
            try:
                cur.execute(detect_db_srid_typmods_sql())
                detected = [str(r[0]) for r in cur.fetchall() if r and r[0]]
            except Exception:
                detected = []

    srid_txt = str(srid) if srid not in (None, 0, "0") else "—"
    extra = ""
    if detected:
        extra = ", ".join(detected)
    return srid_txt, extra

def _footer(canv, doc, left_text: str, right_text: str) -> None:
    canv.saveState()
    canv.setFont(FONT_REG, 8)
    canv.setFillColor(colors.grey)
    canv.drawString(doc.leftMargin, 8 * mm, left_text)
    canv.drawRightString(doc.pagesize[0] - doc.rightMargin, 8 * mm, right_text)
    canv.restoreState()


def generate_geopts_table_pdf(ctx: ReportContext, payload: dict) -> bytes:
    buf = io.BytesIO()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer_left = f"{ctx.t('common.generated_on')}: {ts}"

    def _on_page(canv, d):
        page_no = canv.getPageNumber()
        _footer(canv, d, footer_left, f"{ctx.t('common.page')} {page_no}")

    srid_txt, detected_txt = _detect_srid(ctx)

    title = Paragraph(ctx.t("report.geopts_table.title"), TITLE)

    srid_line = f"{ctx.t('field.geopts.srid')}: EPSG:{srid_txt}" if srid_txt != "—" else f"{ctx.t('field.geopts.srid')}: —"
    if detected_txt and detected_txt != srid_txt:
        srid_line += f" ({ctx.t('field.geopts.detected_srids')}: {detected_txt})"

    subtitle = Paragraph(
        f"{ctx.t('common.generated_on')}: {ts} — {ctx.t('header.database')}: {ctx.selected_db} — {srid_line}",
        SMALL
    )

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=14 * mm,
        title="Geopts table",
        author=ctx.user_email or "",
    )

    with get_terrain_connection(ctx.selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(report_geopts_list_all_sql())
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]

    logger.info(f"[{ctx.selected_db}] Geopts table: {len(rows)} rows, lang={ctx.lang}")

    # Header labels (fallback to raw col if missing)
    col_labels = []
    for c in cols:
        key = f"field.geopt.{c}"
        txt = ctx.t(key)
        col_labels.append(txt if txt != key else c)

    data: List[List[Any]] = [[Paragraph(x, HEADER) for x in col_labels]]

    for r in rows:
        # stringify cell values (geometry can be huge; keep it short)
        row_cells: List[Any] = []
        for v in r:
            s = _v(v)
            if len(s) > 160:
                s = s[:159] + "…"
            row_cells.append(Paragraph(s, CELL))
        data.append(row_cells)

    # Simple width heuristic: distribute with some emphasis on first columns
    # If you don't want geometry column, remove pts_geom from SQL list.
    usable_w = A4[0] - (12*mm + 12*mm)
    n = max(1, len(cols))
    col_widths = [usable_w / n] * n

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f5f5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    story: List[Any] = [title, Spacer(1, 2*mm), subtitle, Spacer(1, 4*mm), t]
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()