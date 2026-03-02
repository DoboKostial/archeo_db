# app/reports/photos_table_report.py
from __future__ import annotations

import io
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.logger import logger
from app.reports.context import ReportContext
from app.database import get_terrain_connection
from app.queries import report_photos_table_list_all_sql
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

TITLE = ParagraphStyle("PhotosTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=14, leading=16)
SMALL = ParagraphStyle("PhotosSmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
CELL = ParagraphStyle("PhotosCell", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
HEADER = ParagraphStyle("PhotosHeader", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=8, leading=10)


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

    # try "<id>.<ext>"
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".tiff"):
        p = base + ext
        if os.path.exists(p):
            return p

    # IMPORTANT fallback (this is what often fixes "<id>.jpg" IDs)
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
            logger.warning(f"[{os.path.basename(path)}] image has zero size")
            return None
        scale = min(max_w / iw, max_h / ih)
        img.drawWidth = iw * scale
        img.drawHeight = ih * scale
        return img
    except Exception as e:
        # key diagnostic: if thumb is PDF/SVG/TIFF, ReportLab often fails here
        logger.warning(f"Cannot load thumb as image: {path} ({e})")
        return None


def _fmt_list(vals: List[Any], max_items: int = 10) -> str:
    vals = [v for v in (vals or []) if v is not None]
    shown = vals[:max_items]
    more = max(0, len(vals) - len(shown))
    txt = ", ".join(str(x) for x in shown) if shown else "—"
    return f"{txt} (+{more})" if more else txt

def _fmt_size(n: Any) -> str:
    try:
        v = int(n)
    except Exception:
        return "—"
    if v < 1024:
        return f"{v} B"
    if v < 1024*1024:
        return f"{v/1024:.1f} KB"
    return f"{v/(1024*1024):.1f} MB"


def generate_photos_table_pdf(ctx: ReportContext, payload: dict) -> bytes:
    buf = io.BytesIO()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = Paragraph(ctx.t("report.photos_table.title"), TITLE)
    subtitle = Paragraph(
        f"{ctx.t('common.generated_on')}: {ts} — {ctx.t('header.database')}: {ctx.selected_db}",
        SMALL
    )

    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=14 * mm,
        title="Photos table",
        author=ctx.user_email or "",
    )

    with get_terrain_connection(ctx.selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(report_photos_table_list_all_sql())
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]

    photos: List[Dict[str, Any]] = [dict(zip(cols, r)) for r in rows]
    logger.info(f"[{ctx.selected_db}] Photos table: {len(photos)} rows, lang={ctx.lang}")

    header_row = [
        Paragraph(ctx.t("field.photo.thumb"), HEADER),
        Paragraph(ctx.t("field.photo.id"), HEADER),
        Paragraph(ctx.t("field.photo.type"), HEADER),
        Paragraph(ctx.t("field.photo.date"), HEADER),
        Paragraph(ctx.t("field.photo.author"), HEADER),
        Paragraph(ctx.t("field.photo.notes"), HEADER),
        Paragraph(ctx.t("field.photo.file_size"), HEADER),
        Paragraph(ctx.t("field.photo.links_sj"), HEADER),
        Paragraph(ctx.t("field.photo.links_section"), HEADER),
        Paragraph(ctx.t("field.photo.links_polygon"), HEADER),
        Paragraph(ctx.t("field.photo.links_find"), HEADER),
        Paragraph(ctx.t("field.photo.links_sample"), HEADER),
    ]

    data: List[List[Any]] = [header_row]

    for p in photos:
        pid = _v(p.get("id_photo"))
        thumb_path = _try_find_thumb(ctx, "photos", pid)
        thumb = _safe_image(thumb_path, max_w=34*mm, max_h=28*mm) or Paragraph("—", CELL)

        data.append([
            thumb,
            Paragraph(pid, CELL),
            Paragraph(_v(p.get("photo_typ")), CELL),
            Paragraph(_v(p.get("datum")), CELL),
            Paragraph(_v(p.get("author")), CELL),
            Paragraph(_truncate(_v(p.get("notes")), 140), CELL),
            Paragraph(_fmt_size(p.get("file_size")), CELL),
            Paragraph(_fmt_list(p.get("sj_ids") or [], 12), CELL),
            Paragraph(_fmt_list(p.get("section_ids") or [], 10), CELL),
            Paragraph(_fmt_list(p.get("polygon_names") or [], 8), CELL),
            Paragraph(_fmt_list(p.get("find_ids") or [], 10), CELL),
            Paragraph(_fmt_list(p.get("sample_ids") or [], 10), CELL),
        ])

    col_widths = [
        36*mm, 28*mm, 18*mm, 24*mm, 26*mm, 28*mm, 14*mm, 18*mm, 18*mm, 18*mm, 18*mm, 18*mm
    ]

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f5f5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    story: List[Any] = [title, Spacer(1, 2*mm), subtitle, Spacer(1, 4*mm), t]
    doc.build(story)
    return buf.getvalue()