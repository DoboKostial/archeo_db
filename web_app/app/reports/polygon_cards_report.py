# app/reports/polygon_cards_report.py
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
    report_polygon_cards_list_polygons_sql,
    report_polygon_cards_detail_sql,
    report_polygon_cards_bindings_top_sql,
    report_polygon_cards_bindings_bottom_sql,
    report_polygon_cards_sj_ids_sql,
    report_polygon_cards_media_ids_sql,
)

from config import Config


# -------------------------
# Unicode font (same approach as sj_cards)
# -------------------------

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

    logger.warning("Unicode font not found/registered -> falling back to Helvetica.")
    return "Helvetica", "Helvetica-Bold"


FONT_REG, FONT_BOLD = _register_unicode_fonts()


# -------------------------
# Styles (kept consistent)
# -------------------------

_styles = getSampleStyleSheet()

TITLE = ParagraphStyle("PolyTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=14, leading=16)
HEADER_SMALL = ParagraphStyle("PolyHeaderSmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=9, leading=11, textColor=colors.grey)
SECTION_TITLE = ParagraphStyle("PolySectionTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=10, leading=12)
LABEL = ParagraphStyle("PolyLabel", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10, textColor=colors.grey)
VALUE = ParagraphStyle("PolyValue", parent=_styles["Normal"], fontName=FONT_REG, fontSize=9, leading=11)
SMALL = ParagraphStyle("PolySmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
CAPTION = ParagraphStyle("PolyCaption", parent=_styles["Normal"], fontName=FONT_REG, fontSize=7, leading=9, textColor=colors.grey, alignment=1)

BG_ORANGE = colors.HexColor("#fff3e0")
BG_GREY = colors.HexColor("#f5f5f5")
BG_BLUE = colors.HexColor("#e8f1ff")


# -------------------------
# Helpers
# -------------------------

def _v(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, bool):
        return "✓" if x else "—"
    return str(x)


def _truncate(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


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
    base = os.path.join(base_dir, "thumbs", str(media_id))
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


def _format_m2(x: Any) -> str:
    try:
        if x is None:
            return ""
        val = float(x)
        return f"{val:,.2f}".replace(",", " ")  # simple, locale-independent
    except Exception:
        return ""


def _fetch_polygon_detail(conn, polygon_name: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(report_polygon_cards_detail_sql(), (polygon_name,))
        row = cur.fetchone()
        if not row:
            return {}
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def _fetch_bindings(conn, polygon_name: str, which: str) -> List[Tuple[int, int]]:
    sql = report_polygon_cards_bindings_top_sql() if which == "top" else report_polygon_cards_bindings_bottom_sql()
    with conn.cursor() as cur:
        cur.execute(sql, (polygon_name,))
        return [(int(r[0]), int(r[1])) for r in cur.fetchall()]


def _fetch_sj_ids(conn, polygon_name: str) -> List[int]:
    with conn.cursor() as cur:
        cur.execute(report_polygon_cards_sj_ids_sql(), (polygon_name,))
        return [int(r[0]) for r in cur.fetchall()]


def _fetch_media_ids(conn, polygon_name: str, kind: str) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(report_polygon_cards_media_ids_sql(kind), (polygon_name,))
        return [str(r[0]) for r in cur.fetchall()]


def _format_intervals(intervals: List[Tuple[int, int]], max_items: int = 8) -> Tuple[str, int]:
    """
    Returns ("a–b, c–d, ...", more_count)
    """
    if not intervals:
        return "—", 0
    shown = intervals[:max_items]
    more = max(0, len(intervals) - len(shown))
    txt = ", ".join(f"{a}–{b}" for a, b in shown)
    return txt, more


def _format_ids_list(ids: List[Any], max_items: int = 10) -> Tuple[str, int]:
    if not ids:
        return "—", 0
    shown = ids[:max_items]
    more = max(0, len(ids) - len(shown))
    txt = ", ".join(str(x) for x in shown)
    return txt, more


# -------------------------
# Layout blocks
# -------------------------

def _page_header(ctx: ReportContext) -> Table:
    action_prefix, db_label = _parse_db_label(ctx.selected_db)
    left = Paragraph(ctx.t("header.polygon_list.title"), TITLE)
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


def _section1_orange(ctx: ReportContext, p: Dict[str, Any]) -> Table:
    line1 = Table([[
        Paragraph(ctx.t("field.polygon.name"), LABEL), Paragraph(_v(p.get("polygon_name")), VALUE),
        Paragraph(ctx.t("field.polygon.parent"), LABEL), Paragraph(_v(p.get("parent_name")) or "—", VALUE),
    ]], colWidths=[26*mm, 74*mm, 20*mm, 70*mm])

    line2 = Table([[
        Paragraph(ctx.t("field.polygon.allocation_reason"), LABEL), Paragraph(_v(p.get("allocation_reason")), VALUE),
        Paragraph(ctx.t("field.polygon.srid"), LABEL), Paragraph(_v(p.get("srid")) or "—", VALUE),
    ]], colWidths=[36*mm, 84*mm, 16*mm, 54*mm])

    # areas optional
    a_top = _format_m2(p.get("area_top_m2"))
    a_bot = _format_m2(p.get("area_bottom_m2"))
    line3 = Table([[
        Paragraph(ctx.t("field.polygon.area_top_m2"), LABEL), Paragraph(a_top or "—", VALUE),
        Paragraph(ctx.t("field.polygon.area_bottom_m2"), LABEL), Paragraph(a_bot or "—", VALUE),
    ]], colWidths=[34*mm, 56*mm, 38*mm, 62*mm])

    line4 = Table([[
        Paragraph(ctx.t("field.polygon.npoints_top"), LABEL), Paragraph(_v(p.get("npoints_top")), VALUE),
        Paragraph(ctx.t("field.polygon.npoints_bottom"), LABEL), Paragraph(_v(p.get("npoints_bottom")), VALUE),
        Paragraph(ctx.t("field.polygon.npoints_total"), LABEL), Paragraph(_v(p.get("npoints_total")), VALUE),
    ]], colWidths=[30*mm, 18*mm, 34*mm, 18*mm, 34*mm, 18*mm])

    outer = Table([[line1], [line2], [line3], [line4]], colWidths=[A4[0] - 24*mm])
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_ORANGE),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return outer


def _section2_grey(ctx: ReportContext, p: Dict[str, Any]) -> Table:
    notes = _truncate(_v(p.get("notes")), 520) or "—"

    row1 = Table([[
        Paragraph(ctx.t("field.polygon.has_geom_top"), LABEL), Paragraph(_v(p.get("has_geom_top")), VALUE),
        Paragraph(ctx.t("field.polygon.has_geom_bottom"), LABEL), Paragraph(_v(p.get("has_geom_bottom")), VALUE),
    ]], colWidths=[34*mm, 56*mm, 40*mm, 60*mm])

    row2 = Table([[
        Paragraph(ctx.t("field.polygon.notes"), LABEL),
        Paragraph(notes, VALUE),
    ]], colWidths=[22*mm, 168*mm])

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


def _section3_blue(ctx: ReportContext, bindings_top: List[Tuple[int, int]], bindings_bottom: List[Tuple[int, int]], sj_ids: List[int]) -> Table:
    top_txt, top_more = _format_intervals(bindings_top, max_items=8)
    bot_txt, bot_more = _format_intervals(bindings_bottom, max_items=8)
    sj_txt, sj_more = _format_ids_list(sj_ids, max_items=12)

    left_rows = [
        [Paragraph(ctx.t("field.polygon.bindings_top"), LABEL), Paragraph(top_txt, VALUE)],
        [Paragraph("", LABEL), Paragraph((f"+ {top_more} {ctx.t('common.more')}" if top_more else ""), SMALL)],
        [Paragraph(ctx.t("field.polygon.bindings_bottom"), LABEL), Paragraph(bot_txt, VALUE)],
        [Paragraph("", LABEL), Paragraph((f"+ {bot_more} {ctx.t('common.more')}" if bot_more else ""), SMALL)],
    ]
    left = Table(left_rows, colWidths=[38*mm, 57*mm])
    left.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))

    right_rows = [
        [Paragraph(ctx.t("field.polygon.sj_links"), LABEL), Paragraph(sj_txt, VALUE)],
        [Paragraph("", LABEL), Paragraph((f"+ {sj_more} {ctx.t('common.more')}" if sj_more else ""), SMALL)],
        [Paragraph(ctx.t("field.polygon.sj_count"), LABEL), Paragraph(str(len(sj_ids)), VALUE)],
    ]
    right = Table(right_rows, colWidths=[30*mm, 65*mm])
    right.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))

    outer = Table([[left, right]], colWidths=[95*mm, 95*mm])
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
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


# -------------------------
# Main generator
# -------------------------

def generate_polygon_cards_pdf(ctx: ReportContext, payload: dict) -> bytes:
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
        title="Polygon cards",
        author=ctx.user_email or "",
    )

    story: List[Any] = []

    with get_terrain_connection(ctx.selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(report_polygon_cards_list_polygons_sql())
            polygon_names = [str(r[0]) for r in cur.fetchall()]

    logger.info(f"[{ctx.selected_db}] Polygon cards: {len(polygon_names)} pages, lang={ctx.lang}")

    total_pages = len(polygon_names)

    def _on_page(canv, d):
        page_no = canv.getPageNumber()
        _footer(canv, d, footer_left, f"{ctx.t('common.page')} {page_no}/{total_pages}")

    for idx, poly_name in enumerate(polygon_names, start=1):
        with get_terrain_connection(ctx.selected_db) as conn:
            p = _fetch_polygon_detail(conn, poly_name)
            if not p:
                logger.warning(f"[{ctx.selected_db}] Polygon cards: polygon '{poly_name}' not found")
                continue

            bindings_top = _fetch_bindings(conn, poly_name, "top")
            bindings_bottom = _fetch_bindings(conn, poly_name, "bottom")
            sj_ids = _fetch_sj_ids(conn, poly_name)

            media_ids = {
                "photos": _fetch_media_ids(conn, poly_name, "photos"),
                "sketches": _fetch_media_ids(conn, poly_name, "sketches"),
                "photograms": _fetch_media_ids(conn, poly_name, "photograms"),
            }

        story.append(_page_header(ctx))
        story.append(Spacer(1, 3 * mm))

        story.append(_section1_orange(ctx, p))
        story.append(Spacer(1, 2.5 * mm))

        story.append(_section2_grey(ctx, p))
        story.append(Spacer(1, 2.5 * mm))

        story.append(_section3_blue(ctx, bindings_top, bindings_bottom, sj_ids))
        story.append(Spacer(1, 4 * mm))

        story.append(Paragraph(ctx.t("section.polygon.media"), SECTION_TITLE))
        story.append(Spacer(1, 2 * mm))
        story.append(_media_section(ctx, "photos", media_ids["photos"]))
        story.append(_media_section(ctx, "sketches", media_ids["sketches"]))
        story.append(_media_section(ctx, "photograms", media_ids["photograms"]))

        if idx != len(polygon_names):
            story.append(PageBreak())

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()