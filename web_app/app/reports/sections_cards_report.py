# app/reports/sections_cards_report.py
from __future__ import annotations

import io
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.logger import logger
from app.reports.context import ReportContext
from app.database import get_terrain_connection

from app.queries import (
    report_sections_cards_list_sections_sql,
    report_sections_cards_detail_sql,
    report_sections_cards_sj_ids_sql,
    report_sections_cards_media_ids_sql,
)

from config import Config


def _register_unicode_fonts() -> Tuple[str, str]:
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
         "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"),
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
TITLE = ParagraphStyle("SecTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=14, leading=16)
HEADER_SMALL = ParagraphStyle("SecHeaderSmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=9, leading=11, textColor=colors.grey)
SECTION_TITLE = ParagraphStyle("SecSectionTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=10, leading=12)
LABEL = ParagraphStyle("SecLabel", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10, textColor=colors.grey)
VALUE = ParagraphStyle("SecValue", parent=_styles["Normal"], fontName=FONT_REG, fontSize=9, leading=11)
SMALL = ParagraphStyle("SecSmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
CAPTION = ParagraphStyle("SecCaption", parent=_styles["Normal"], fontName=FONT_REG, fontSize=7, leading=9, textColor=colors.grey, alignment=1)

BG_ORANGE = colors.HexColor("#fff3e0")
BG_GREY = colors.HexColor("#f5f5f5")
BG_BLUE = colors.HexColor("#e8f1ff")


def _v(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, bool):
        return "✓" if x else "—"
    return str(x)


def _truncate(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    return t if len(t) <= max_chars else t[: max_chars - 1].rstrip() + "…"


def _parse_db_label(selected_db: str) -> Tuple[str, str]:
    if "_" in (selected_db or ""):
        p, rest = selected_db.split("_", 1)
        return p, rest
    return (selected_db or ""), (selected_db or "")


def _footer(canv, doc, left_text: str, right_text: str) -> None:
    canv.saveState()
    canv.setFont(FONT_REG, 8)
    canv.setFillColor(colors.grey)
    canv.drawString(doc.leftMargin, 8 * mm, left_text)
    canv.drawRightString(A4[0] - doc.rightMargin, 8 * mm, right_text)
    canv.restoreState()


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


def _top4_and_more(ids_desc: List[str]) -> Tuple[List[str], int]:
    top = ids_desc[:4]
    more = max(0, len(ids_desc) - len(top))
    return top, more


def _fetch_section_detail(conn, sid: int) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(report_sections_cards_detail_sql(), (sid, sid, sid, sid))
        row = cur.fetchone()
        if not row:
            return {}
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def _fetch_sj_ids(conn, sid: int) -> List[int]:
    with conn.cursor() as cur:
        cur.execute(report_sections_cards_sj_ids_sql(), (sid,))
        return [int(r[0]) for r in cur.fetchall()]


def _fetch_media_ids(conn, sid: int, kind: str) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(report_sections_cards_media_ids_sql(kind), (sid,))
        return [str(r[0]).strip() for r in cur.fetchall() if r and r[0] is not None and str(r[0]).strip()]


def _page_header(ctx: ReportContext) -> Table:
    action_prefix, db_label = _parse_db_label(ctx.selected_db)
    left = Paragraph(ctx.t("header.sections_list.title"), TITLE)
    mid = Paragraph(f"{ctx.t('header.action')}: {action_prefix}", HEADER_SMALL)
    right = Paragraph(f"{ctx.t('header.database')}: {db_label}", HEADER_SMALL)

    t = Table([[left, mid, right]], colWidths=[95 * mm, 45 * mm, 50 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.lightgrey),
    ]))
    return t


def _section1_orange(ctx: ReportContext, s: Dict[str, Any]) -> Table:
    row1 = Table([[
        Paragraph(ctx.t("field.section.id"), LABEL), Paragraph(_v(s.get("id_section")), VALUE),
        Paragraph(ctx.t("field.section.type"), LABEL), Paragraph(_v(s.get("section_type")) or "—", VALUE),
    ]], colWidths=[22*mm, 24*mm, 22*mm, 122*mm])

    row2 = Table([[
        Paragraph(ctx.t("field.section.srid"), LABEL), Paragraph(_v(s.get("srid_txt")) or "—", VALUE),
        Paragraph(ctx.t("field.section.sj_nr"), LABEL), Paragraph(_v(s.get("sj_nr")), VALUE),
    ]], colWidths=[22*mm, 74*mm, 22*mm, 72*mm])

    outer = Table([[row1], [row2]], colWidths=[A4[0] - 24*mm])
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_ORANGE),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return outer


def _section2_grey(ctx: ReportContext, s: Dict[str, Any]) -> Table:
    desc = _truncate(_v(s.get("description")), 520) or "—"
    ranges = _truncate(_v(s.get("ranges_txt")), 520) or "—"

    row1 = Table([[Paragraph(ctx.t("field.section.description"), LABEL), Paragraph(desc, VALUE)]],
                 colWidths=[28*mm, 162*mm])
    row2 = Table([[Paragraph(ctx.t("field.section.ranges"), LABEL), Paragraph(ranges, VALUE)]],
                 colWidths=[28*mm, 162*mm])

    outer = Table([[row1], [row2]], colWidths=[A4[0] - 24*mm])
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_GREY),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return outer


def _section3_blue(ctx: ReportContext, sj_ids: List[int]) -> Table:
    shown = sj_ids[:25]
    more = max(0, len(sj_ids) - len(shown))
    sj_txt = ", ".join(str(x) for x in shown) if shown else "—"
    more_txt = f"+ {more} {ctx.t('common.more')}" if more else ""

    row1 = Table([[Paragraph(ctx.t("field.section.sj_list"), LABEL), Paragraph(sj_txt, VALUE)]],
                 colWidths=[28*mm, 162*mm])
    row2 = Table([[Paragraph("", LABEL), Paragraph(more_txt, SMALL)]],
                 colWidths=[28*mm, 162*mm])

    outer = Table([[row1], [row2]], colWidths=[A4[0] - 24*mm])
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return outer


def _media_section(ctx: ReportContext, kind: str, ids_desc: List[str]) -> Table:
    title = Paragraph(ctx.t(f"media.{kind}.title"), SECTION_TITLE)

    top4, more = _top4_and_more(ids_desc)
    more_txt = Paragraph((f"+ {more} {ctx.t('common.more')}" if more > 0 else ""), SMALL)

    cell_w = 42 * mm
    cell_h = 42 * mm

    thumb_cells: List[Any] = []
    for mid in top4:
        thumb_path = _try_find_thumb(ctx, kind, mid)
        img = _safe_image(thumb_path, max_w=cell_w - 4 * mm, max_h=cell_h - 10 * mm)
        caption = Paragraph(f"{mid}", CAPTION)

        if img is None:
            box = Table([[Paragraph(f"{mid}", SMALL)]], colWidths=[cell_w], rowHeights=[cell_h])
            box.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            thumb_cells.append(Table([[box], [caption]], colWidths=[cell_w]))
        else:
            thumb_cells.append(Table([[img], [caption]], colWidths=[cell_w]))

    while len(thumb_cells) < 4:
        thumb_cells.append("")

    thumbs_row = Table([thumb_cells + [more_txt]], colWidths=[cell_w, cell_w, cell_w, cell_w, 22 * mm])
    thumbs_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (3, 0), "CENTER"),
        ("ALIGN", (4, 0), (4, 0), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    block = Table([[title], [thumbs_row]], colWidths=[A4[0] - 24 * mm])
    block.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.3, colors.lightgrey),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return block


def generate_sections_cards_pdf(ctx: ReportContext, payload: dict) -> bytes:
    buf = io.BytesIO()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer_left = f"{ctx.t('common.generated_on')}: {ts}"

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=14 * mm,
        title="Sections cards",
        author=ctx.user_email or "",
    )

    with get_terrain_connection(ctx.selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(report_sections_cards_list_sections_sql())
            section_ids = [int(r[0]) for r in cur.fetchall()]

    logger.info(f"[{ctx.selected_db}] Sections cards: {len(section_ids)} pages, lang={ctx.lang}")
    total_pages = len(section_ids)

    def _on_page(canv, d):
        page_no = canv.getPageNumber()
        _footer(canv, d, footer_left, f"{ctx.t('common.page')} {page_no}/{total_pages}")

    story: List[Any] = []

    for idx, sid in enumerate(section_ids, start=1):
        with get_terrain_connection(ctx.selected_db) as conn:
            s = _fetch_section_detail(conn, sid)
            if not s:
                continue

            sj_ids = _fetch_sj_ids(conn, sid)

            media_ids = {
                "photos": _fetch_media_ids(conn, sid, "photos"),
                "drawings": _fetch_media_ids(conn, sid, "drawings"),
                "sketches": _fetch_media_ids(conn, sid, "sketches"),
                "photograms": _fetch_media_ids(conn, sid, "photograms"),
            }

        story.append(_page_header(ctx))
        story.append(Spacer(1, 3 * mm))

        story.append(_section1_orange(ctx, s))
        story.append(Spacer(1, 2.5 * mm))

        story.append(_section2_grey(ctx, s))
        story.append(Spacer(1, 2.5 * mm))

        story.append(_section3_blue(ctx, sj_ids))
        story.append(Spacer(1, 4 * mm))

        story.append(Paragraph(ctx.t("section.section.media"), SECTION_TITLE))
        story.append(Spacer(1, 2 * mm))
        story.append(_media_section(ctx, "photos", media_ids["photos"]))
        story.append(_media_section(ctx, "drawings", media_ids["drawings"]))
        story.append(_media_section(ctx, "sketches", media_ids["sketches"]))
        story.append(_media_section(ctx, "photograms", media_ids["photograms"]))

        if idx != len(section_ids):
            story.append(PageBreak())

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()