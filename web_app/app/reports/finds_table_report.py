# app/reports/finds_table_report.py
from __future__ import annotations

import io
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.logger import logger
from app.reports.context import ReportContext
from app.database import get_terrain_connection

from app.queries import (
    report_finds_list_all_sql,
    report_finds_media_ids_sql,
)

from config import Config


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

TITLE = ParagraphStyle("FindsTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=14, leading=16)
SMALL = ParagraphStyle("FindsSmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
CELL = ParagraphStyle("FindsCell", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
HEADER = ParagraphStyle("FindsHeader", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=8, leading=10)

def _v(x: Any) -> str:
    return "—" if x is None or x == "" else str(x)

def _truncate(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    return t if len(t) <= max_chars else t[: max_chars - 1].rstrip() + "…"

def _media_base_dir(ctx: ReportContext, kind: str) -> str:
    sub = (Config.MEDIA_DIRS or {}).get(kind, "")
    if not sub:
        return ""
    return os.path.join(Config.DATA_DIR, ctx.selected_db, sub)

def _try_find_thumb(ctx: ReportContext, kind: str, media_id: str) -> str:
    base_dir = _media_base_dir(ctx, kind)
    if not base_dir:
        return ""
    mid = str(media_id).strip()
    if not mid:
        return ""
    base = os.path.join(base_dir, "thumbs", mid)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = base + ext
        if os.path.exists(p):
            return p
    if os.path.exists(base):
        return base
    return ""

def _safe_image(path: str, max_w: float, max_h: float) -> Optional[Image]:
    if not path or not os.path.exists(path):
        return None
    try:
        img = Image(path)
        iw, ih = img.imageWidth, img.imageHeight
        if not iw or not ih:
            return None
        scale = min(max_w / iw, max_h / ih)
        img.drawWidth = iw * scale
        img.drawHeight = ih * scale
        return img
    except Exception:
        return None

def _fetch_media_ids(conn, id_find: int, kind: str) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(report_finds_media_ids_sql(kind), (id_find,))
        return [str(r[0]).strip() for r in cur.fetchall() if r and r[0] is not None and str(r[0]).strip()]

def _thumb_cell(ctx: ReportContext, kind: str, ids: List[str], max_thumbs: int = 2) -> Any:
    """
    Returns a small inner table with up to N thumbnails stacked vertically.
    If none, returns "—".
    """
    ids = ids[:max_thumbs]
    if not ids:
        return Paragraph("—", CELL)

    rows: List[List[Any]] = []
    for mid in ids:
        p = _try_find_thumb(ctx, kind, mid)
        img = _safe_image(p, max_w=24*mm, max_h=24*mm) # numbers in max_w and max_h defines the dimensions of thumb in report
        if img is None:
            rows.append([Paragraph(mid, CELL)])
        else:
            rows.append([img])

    t = Table(rows, colWidths=[26*mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t

def generate_finds_table_pdf(ctx: ReportContext, payload: dict) -> bytes:
    buf = io.BytesIO()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = Paragraph(ctx.t("report.finds_table.title"), TITLE)
    subtitle = Paragraph(f"{ctx.t('common.generated_on')}: {ts} — {ctx.t('header.database')}: {ctx.selected_db}", SMALL)

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=14 * mm,
        title="Finds table",
        author=ctx.user_email or "",
    )

    with get_terrain_connection(ctx.selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(report_finds_list_all_sql())
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]

    # convert to dicts
    finds: List[Dict[str, Any]] = [dict(zip(cols, r)) for r in rows]
    logger.info(f"[{ctx.selected_db}] Finds table: {len(finds)} rows, lang={ctx.lang}")

    header_row = [
        Paragraph(ctx.t("field.find.id"), HEADER),
        Paragraph(ctx.t("field.find.type"), HEADER),
        Paragraph(ctx.t("field.find.sj"), HEADER),
        Paragraph(ctx.t("field.find.count"), HEADER),
        Paragraph(ctx.t("field.find.box"), HEADER),
        Paragraph(ctx.t("field.find.polygon"), HEADER),
        Paragraph(ctx.t("field.find.geopt"), HEADER),
        Paragraph(ctx.t("field.find.description"), HEADER),
        Paragraph(ctx.t("media.photos.title"), HEADER),
        Paragraph(ctx.t("media.sketches.title"), HEADER),
    ]

    data: List[List[Any]] = [header_row]

    with get_terrain_connection(ctx.selected_db) as conn:
        for f in finds:
            fid = int(f["id_find"])
            photo_ids = _fetch_media_ids(conn, fid, "photos")
            sketch_ids = _fetch_media_ids(conn, fid, "sketches")

            data.append([
                Paragraph(_v(f.get("id_find")), CELL),
                Paragraph(_v(f.get("ref_find_type")), CELL),
                Paragraph(_v(f.get("ref_sj")), CELL),
                Paragraph(_v(f.get("count")), CELL),
                Paragraph(_v(f.get("box")), CELL),
                Paragraph(_v(f.get("ref_polygon")), CELL),
                Paragraph(_v(f.get("ref_geopt")), CELL),
                Paragraph(_truncate(_v(f.get("description")), 180), CELL),
                _thumb_cell(ctx, "photos", photo_ids, max_thumbs=2), # max_thumbs=defines the maximum number of graph. doku in report. Change according needs.
                _thumb_cell(ctx, "sketches", sketch_ids, max_thumbs=2),
            ])

    col_widths = [
        10*mm, 28*mm, 10*mm, 12*mm, 8*mm, 18*mm, 16*mm, 40*mm, 28*mm, 28*mm # change this to fit columns width according your needs
    ]

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
    doc.build(story)
    return buf.getvalue()