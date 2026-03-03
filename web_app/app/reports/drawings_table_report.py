# app/reports/drawings_table_report.py
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
from app.queries import report_drawings_table_list_all_sql
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

TITLE = ParagraphStyle("DrawTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=14, leading=16)
SMALL = ParagraphStyle("DrawSmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
CELL = ParagraphStyle("DrawCell", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
HEADER = ParagraphStyle("DrawHeader", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=8, leading=10)


def _v(x: Any) -> str:
    return "—" if x is None or x == "" else str(x)


def _truncate(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    return t if len(t) <= max_chars else t[: max_chars - 1].rstrip() + "…"


def _fmt_list(vals: List[Any], max_items: int = 12) -> str:
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
    if v < 1024 * 1024:
        return f"{v/1024:.1f} KB"
    return f"{v/(1024*1024):.1f} MB"


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


def _footer(canv, doc, left_text: str, right_text: str) -> None:
    canv.saveState()
    canv.setFont(FONT_REG, 8)
    canv.setFillColor(colors.grey)
    canv.drawString(doc.leftMargin, 8 * mm, left_text)
    canv.drawRightString(doc.pagesize[0] - doc.rightMargin, 8 * mm, right_text)
    canv.restoreState()


def generate_drawings_table_pdf(ctx: ReportContext, payload: dict) -> bytes:
    buf = io.BytesIO()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer_left = f"{ctx.t('common.generated_on')}: {ts}"

    title = Paragraph(ctx.t("report.drawings_table.title"), TITLE)
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
        title="Drawings table",
        author=ctx.user_email or "",
    )

    with get_terrain_connection(ctx.selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(report_drawings_table_list_all_sql())
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]

    items: List[Dict[str, Any]] = [dict(zip(cols, r)) for r in rows]
    logger.info(f"[{ctx.selected_db}] Drawings table: {len(items)} rows, lang={ctx.lang}")

    header_row = [
        Paragraph(ctx.t("field.drawing.thumb"), HEADER),
        Paragraph(ctx.t("field.drawing.id"), HEADER),
        Paragraph(ctx.t("field.drawing.author"), HEADER),
        Paragraph(ctx.t("field.drawing.date"), HEADER),
        Paragraph(ctx.t("field.drawing.size"), HEADER),
        Paragraph(ctx.t("field.drawing.notes"), HEADER),
        Paragraph(ctx.t("field.drawing.links_sj"), HEADER),
        Paragraph(ctx.t("field.drawing.links_section"), HEADER),
    ]

    data: List[List[Any]] = [header_row]

    for d in items:
        did = _v(d.get("id_drawing"))
        thumb_path = _try_find_thumb(ctx, "drawings", did)
        thumb = _safe_image(thumb_path, max_w=54*mm, max_h=54*mm) or Paragraph("—", CELL)

        data.append([
            thumb,
            Paragraph(did, CELL),
            Paragraph(_v(d.get("author")), CELL),
            Paragraph(_v(d.get("datum")), CELL),
            Paragraph(_fmt_size(d.get("file_size")), CELL),
            Paragraph(_truncate(_v(d.get("notes")), 180), CELL),
            Paragraph(_fmt_list(d.get("sj_ids") or [], 18), CELL),
            Paragraph(_fmt_list(d.get("section_ids") or [], 12), CELL),
        ])

    col_widths = [
        60*mm, 44*mm, 32*mm, 20*mm, 18*mm, 44*mm, 18*mm, 18*mm
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

    def _on_page(canv, ddoc):
        page_no = canv.getPageNumber()
        _footer(canv, ddoc, footer_left, f"{ctx.t('common.page')} {page_no}")

    story: List[Any] = [title, Spacer(1, 2*mm), subtitle, Spacer(1, 4*mm), t]
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()