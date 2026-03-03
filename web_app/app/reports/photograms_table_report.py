# app/reports/photograms_table_report.py
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
from app.queries import report_photograms_table_list_all_sql
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
            except Exception:
                logger.warning(f"Failed to register DejaVu fonts from {reg_path}: {e}")
    return "Helvetica", "Helvetica-Bold"


FONT_REG, FONT_BOLD = _register_unicode_fonts()
_styles = getSampleStyleSheet()

TITLE = ParagraphStyle("PhotogramsTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=14, leading=16)
SMALL = ParagraphStyle("PhotogramsSmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
CELL = ParagraphStyle("PhotogramsCell", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
HEADER = ParagraphStyle("PhotogramsHeader", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=8, leading=10)


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


def _fmt_list(vals: List[Any], max_items: int = 10) -> str:
    vals = [v for v in (vals or []) if v is not None]
    shown = vals[:max_items]
    more = max(0, len(vals) - len(shown))
    txt = ", ".join(str(x) for x in shown) if shown else "—"
    return f"{txt} (+{more})" if more else txt


def _footer(canv, doc, left_text: str, right_text: str) -> None:
    canv.saveState()
    canv.setFont(FONT_REG, 8)
    canv.setFillColor(colors.grey)
    canv.drawString(doc.leftMargin, 8 * mm, left_text)
    canv.drawRightString(doc.pagesize[0] - doc.rightMargin, 8 * mm, right_text)
    canv.restoreState()


def generate_photograms_table_pdf(ctx: ReportContext, payload: dict) -> bytes:
    buf = io.BytesIO()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer_left = f"{ctx.t('common.generated_on')}: {ts}"

    title = Paragraph(ctx.t("report.photograms_table.title"), TITLE)
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
        title="Photograms table",
        author=ctx.user_email or "",
    )

    with get_terrain_connection(ctx.selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(report_photograms_table_list_all_sql())
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]

    items: List[Dict[str, Any]] = [dict(zip(cols, r)) for r in rows]
    logger.info(f"[{ctx.selected_db}] Photograms table: {len(items)} rows, lang={ctx.lang}")

    header_row = [
        Paragraph(ctx.t("field.photogram.thumb"), HEADER),
        Paragraph(ctx.t("field.photogram.id"), HEADER),
        Paragraph(ctx.t("field.photogram.type"), HEADER),
        Paragraph(ctx.t("field.photogram.size"), HEADER),
        Paragraph(ctx.t("field.photogram.ref_sketch"), HEADER),
        Paragraph(ctx.t("field.photogram.ref_photo_from"), HEADER),
        Paragraph(ctx.t("field.photogram.ref_photo_to"), HEADER),
        Paragraph(ctx.t("field.photogram.notes"), HEADER),
        Paragraph(ctx.t("field.photogram.links_sj"), HEADER),
        Paragraph(ctx.t("field.photogram.links_section"), HEADER),
        Paragraph(ctx.t("field.photogram.links_polygon"), HEADER),
        Paragraph(ctx.t("field.photogram.geopt_ranges"), HEADER),
    ]

    data: List[List[Any]] = [header_row]

    for p in items:
        pid = _v(p.get("id_photogram"))
        thumb_path = _try_find_thumb(ctx, "photograms", pid)
        thumb = _safe_image(thumb_path, max_w=50*mm, max_h=50*mm) or Paragraph("—", CELL)

        data.append([
            thumb,
            Paragraph(pid, CELL),
            Paragraph(_v(p.get("photogram_typ")), CELL),
            Paragraph(_fmt_size(p.get("file_size")), CELL),
            Paragraph(_v(p.get("ref_sketch")), CELL),
            Paragraph(_v(p.get("ref_photo_from")), CELL),
            Paragraph(_v(p.get("ref_photo_to")), CELL),
            Paragraph(_truncate(_v(p.get("notes")), 140), CELL),
            Paragraph(_fmt_list(p.get("sj_ids") or [], 12), CELL),
            Paragraph(_fmt_list(p.get("section_ids") or [], 10), CELL),
            Paragraph(_fmt_list(p.get("polygon_names") or [], 10), CELL),
            Paragraph(_fmt_list(p.get("geopt_ranges") or [], 10), CELL),
        ])

    col_widths = [
        52*mm, 34*mm, 20*mm, 14*mm, 28*mm, 20*mm, 20*mm,
        28*mm, 10*mm, 16*mm, 18*mm, 14*mm
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

    def _on_page(canv, d):
        page_no = canv.getPageNumber()
        _footer(canv, d, footer_left, f"{ctx.t('common.page')} {page_no}")

    story: List[Any] = [title, Spacer(1, 2*mm), subtitle, Spacer(1, 4*mm), t]
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()