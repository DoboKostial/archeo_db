# app/reports/sj_cards_report.py
from __future__ import annotations

import io
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    Image,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.logger import logger
from app.reports.context import ReportContext
from app.database import get_terrain_connection

from app.queries import (
    report_sj_cards_list_sj_sql,
    report_sj_cards_detail_sql,
    report_sj_cards_media_ids_sql,
)

from config import Config


# -------------------------
# Font (Unicode / diacritics)
# -------------------------

def _register_unicode_fonts() -> Tuple[str, str]:
    """
    Try to register DejaVu Sans (regular + bold). Falls back to Helvetica if not found.
    Returns (regular_font_name, bold_font_name).
    """
    candidates = [
        # system paths (common on Debian/Ubuntu/RHEL) or better to pack along with app?
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
         "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"),
        # project-bundled paths (recommended)
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

    logger.warning("Unicode font not found/registered -> falling back to Helvetica (non-ENG diacritics may break).")
    return "Helvetica", "Helvetica-Bold"


FONT_REG, FONT_BOLD = _register_unicode_fonts()


# -------------------------
# Styles
# -------------------------

_styles = getSampleStyleSheet()

TITLE = ParagraphStyle(
    "SJTitle",
    parent=_styles["Normal"],
    fontName=FONT_BOLD,
    fontSize=14,
    leading=16,
)

HEADER_SMALL = ParagraphStyle(
    "SJHeaderSmall",
    parent=_styles["Normal"],
    fontName=FONT_REG,
    fontSize=9,
    leading=11,
    textColor=colors.grey,
)

SECTION_TITLE = ParagraphStyle(
    "SJSectionTitle",
    parent=_styles["Normal"],
    fontName=FONT_BOLD,
    fontSize=10,
    leading=12,
)

LABEL = ParagraphStyle(
    "SJLabel",
    parent=_styles["Normal"],
    fontName=FONT_REG,
    fontSize=8,
    leading=10,
    textColor=colors.grey,
)

VALUE = ParagraphStyle(
    "SJValue",
    parent=_styles["Normal"],
    fontName=FONT_REG,
    fontSize=9,
    leading=11,
)

SMALL = ParagraphStyle(
    "SJSmall",
    parent=_styles["Normal"],
    fontName=FONT_REG,
    fontSize=8,
    leading=10,
)

CAPTION = ParagraphStyle(
    "SJCaption",
    parent=_styles["Normal"],
    fontName=FONT_REG,
    fontSize=7,
    leading=9,
    textColor=colors.grey,
    alignment=1,  # center
)

# Subtle backgrounds
BG_ORANGE = colors.HexColor("#fff3e0")  # very light orange
BG_GREY = colors.HexColor("#f5f5f5")    # very light grey
BG_BLUE = colors.HexColor("#e8f1ff")    # very light blue


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
    """
    Returns (action_prefix, db_name_label) from selected_db.
    If db contains '_', prefix is before first '_' and name after.
    """
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
    """
    DATA_DIR/<selected_db>/<MEDIA_DIRS[kind]>
    """
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


def _fetch_sj_detail(conn, sj_id: int) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(report_sj_cards_detail_sql(), (sj_id,))
        row = cur.fetchone()
        if not row:
            return {}
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def _fetch_media_ids(conn, sj_id: int, kind: str) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(report_sj_cards_media_ids_sql(kind), (sj_id,))
        return [str(r[0]) for r in cur.fetchall()]


def _top4_and_more(ids_desc: List[str]) -> Tuple[List[str], int]:
    top = ids_desc[:4]
    more = max(0, len(ids_desc) - len(top))
    return top, more


# -------------------------
# Layout blocks
# -------------------------

def _page_header(ctx: ReportContext) -> Table:
    """
    Header: "Seznam strat. jednotek" | "Akce: <prefix>" | "Databáze: <name>"
    """
    action_prefix, db_label = _parse_db_label(ctx.selected_db)
    left = Paragraph(ctx.t("header.sj_list.title"), TITLE)
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


def _section1_orange(ctx: ReportContext, sj: Dict[str, Any]) -> Table:
    """
    Section 1 (orange):
      Strat. jednotka: xxx | Typ SJ xxx (podtyp xxx)
      Autor: xxx | Zapsano: xxx
    """
    line1 = Table([[
        Paragraph(ctx.t("field.sj.id"), LABEL),
        Paragraph(_v(sj.get("id_sj")), VALUE),
        Paragraph(ctx.t("field.sj.type"), LABEL),
        Paragraph(_v(sj.get("sj_typ")), VALUE),
        Paragraph(ctx.t("field.sj.subtype"), LABEL),
        Paragraph(_v(sj.get("sj_subtype")), VALUE),
    ]], colWidths=[22*mm, 20*mm, 18*mm, 35*mm, 16*mm, 45*mm])

    line2 = Table([[
        Paragraph(ctx.t("field.sj.author"), LABEL),
        Paragraph(_v(sj.get("author")), VALUE),
        Paragraph(ctx.t("field.sj.recorded"), LABEL),
        Paragraph(_v(sj.get("recorded")), VALUE),
    ]], colWidths=[18*mm, 70*mm, 18*mm, 84*mm])

    outer = Table([[line1], [line2]], colWidths=[A4[0] - 24*mm])
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_ORANGE),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return outer


def _section2_grey(ctx: ReportContext, sj: Dict[str, Any]) -> Table:
    """
    Section 2 (grey):
      Docu plan | Docu vertical | Object
      Description | Interpretation
    """
    row1 = Table([[
        Paragraph(ctx.t("field.sj.docu_plan"), LABEL),
        Paragraph(_v(sj.get("docu_plan")), VALUE),
        Paragraph(ctx.t("field.sj.docu_vertical"), LABEL),
        Paragraph(_v(sj.get("docu_vertical")), VALUE),
        Paragraph(ctx.t("field.sj.ref_object"), LABEL),
        Paragraph(_v(sj.get("ref_object")), VALUE),
    ]], colWidths=[26*mm, 16*mm, 34*mm, 16*mm, 18*mm, 60*mm])

    desc = _truncate(_v(sj.get("description")), 420)
    intr = _truncate(_v(sj.get("interpretation")), 420)

    row2 = Table([[
        Paragraph(ctx.t("field.sj.description"), LABEL),
        Paragraph(desc or "—", VALUE),
    ]], colWidths=[24*mm, 166*mm])

    row3 = Table([[
        Paragraph(ctx.t("field.sj.interpretation"), LABEL),
        Paragraph(intr or "—", VALUE),
    ]], colWidths=[24*mm, 166*mm])

    outer = Table([[row1], [row2], [row3]], colWidths=[A4[0] - 24*mm])
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_GREY),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 1), (-1, 2), 4),
    ]))
    return outer


def _subtype_left_block(ctx: ReportContext, sj: Dict[str, Any]) -> Table:
    """
    Left block in section 3: subtype-specific attributes (compact).
    """
    subtype = (_v(sj.get("sj_subtype")) or "").strip().lower()

    rows: List[List[Any]] = []
    if subtype == "deposit":
        rows = [
            [Paragraph(ctx.t("field.deposit.structure"), LABEL), Paragraph(_v(sj.get("deposit_structure")), VALUE)],
            [Paragraph(ctx.t("field.deposit.compactness"), LABEL), Paragraph(_v(sj.get("deposit_compactness")), VALUE)],
            [Paragraph(ctx.t("field.deposit.boundary_visibility"), LABEL), Paragraph(_v(sj.get("deposit_boundary_visibility")), VALUE)],
            [Paragraph(ctx.t("field.deposit.color"), LABEL), Paragraph(_v(sj.get("deposit_color")), VALUE)],
            [Paragraph(ctx.t("field.deposit.deposit_removed"), LABEL), Paragraph(_v(sj.get("deposit_removed")), VALUE)],
        ]
    elif subtype == "negativ":
        rows = [
            [Paragraph(ctx.t("field.negativ.negativ_typ"), LABEL), Paragraph(_v(sj.get("negativ_typ")), VALUE)],
            [Paragraph(ctx.t("field.negativ.excav_extent"), LABEL), Paragraph(_v(sj.get("negativ_excav_extent")), VALUE)],
            [Paragraph(ctx.t("field.negativ.shape_plan"), LABEL), Paragraph(_v(sj.get("negativ_shape_plan")), VALUE)],
            [Paragraph(ctx.t("field.negativ.shape_sides"), LABEL), Paragraph(_v(sj.get("negativ_shape_sides")), VALUE)],
            [Paragraph(ctx.t("field.negativ.shape_bottom"), LABEL), Paragraph(_v(sj.get("negativ_shape_bottom")), VALUE)],
        ]
    elif subtype == "structure":
        rows = [
            [Paragraph(ctx.t("field.structure.structure_typ"), LABEL), Paragraph(_v(sj.get("structure_typ")), VALUE)],
            [Paragraph(ctx.t("field.structure.construction_typ"), LABEL), Paragraph(_v(sj.get("structure_construction_typ")), VALUE)],
            [Paragraph(ctx.t("field.structure.basic_material"), LABEL), Paragraph(_v(sj.get("structure_basic_material")), VALUE)],
            [Paragraph(ctx.t("field.structure.length_m"), LABEL), Paragraph(_v(sj.get("structure_length_m")), VALUE)],
            [Paragraph(ctx.t("field.structure.width_m"), LABEL), Paragraph(_v(sj.get("structure_width_m")), VALUE)],
        ]
    else:
        rows = [[Paragraph("—", VALUE), Paragraph("", VALUE)]]

    t = Table(rows, colWidths=[45*mm, 50*mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def _strat_right_block(ctx: ReportContext, sj: Dict[str, Any]) -> Table:
    """
    Right block in section 3: stratigraphy (Above / Below / Equal).
    Based on rule: ref_sj1 < ref_sj2 => sj1 below sj2
    """
    rows = [
        [Paragraph(ctx.t("field.strat.above"), LABEL), Paragraph(_v(sj.get("strat_above")) or "—", VALUE)],
        [Paragraph(ctx.t("field.strat.below"), LABEL), Paragraph(_v(sj.get("strat_below")) or "—", VALUE)],
        [Paragraph(ctx.t("field.strat.equal"), LABEL), Paragraph(_v(sj.get("strat_equal")) or "—", VALUE)],
    ]
    t = Table(rows, colWidths=[30*mm, 65*mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def _section3_blue(ctx: ReportContext, sj: Dict[str, Any]) -> Table:
    """
    Section 3 (blue):
      Left: subtype-specific attributes
      Right: stratigraphy
    """
    left = _subtype_left_block(ctx, sj)
    right = _strat_right_block(ctx, sj)

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
    """
    One media kind row:
      Title + thin line
      thumbnails (top4) + "+X more"
    """
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
            box = Table([[Paragraph(f"{mid}", SMALL)]],
                        colWidths=[cell_w], rowHeights=[cell_h])
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

def generate_sj_cards_pdf(ctx: ReportContext, payload: dict) -> bytes:
    """
    A4 portrait.
    1 SJ = 1 page.
    Top: 3 colored sections (orange/grey/blue).
    Bottom: media (full width) with 4 type sections separated by thin lines.
    """
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
        title="SJ cards",
        author=ctx.user_email or "",
    )

    story: List[Any] = []

    # List SJ IDs
    with get_terrain_connection(ctx.selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(report_sj_cards_list_sj_sql())
            sj_ids = [r[0] for r in cur.fetchall()]

    logger.info(f"[{ctx.selected_db}] SJ cards: {len(sj_ids)} pages, lang={ctx.lang}")

    total_pages = len(sj_ids)

    def _on_page(canv, d):
        page_no = canv.getPageNumber()
        _footer(canv, d, footer_left, f"{ctx.t('common.page')} {page_no}/{total_pages}")

    for idx, sj_id in enumerate(sj_ids, start=1):
        with get_terrain_connection(ctx.selected_db) as conn:
            sj = _fetch_sj_detail(conn, sj_id)
            if not sj:
                logger.warning(f"[{ctx.selected_db}] SJ cards: SJ {sj_id} not found")
                continue

            media_ids = {
                "photos": _fetch_media_ids(conn, sj_id, "photos"),
                "drawings": _fetch_media_ids(conn, sj_id, "drawings"),
                "sketches": _fetch_media_ids(conn, sj_id, "sketches"),
                "photograms": _fetch_media_ids(conn, sj_id, "photograms"),
            }

        # Header (page-level)
        story.append(_page_header(ctx))
        story.append(Spacer(1, 3 * mm))

        # 1) orange
        story.append(_section1_orange(ctx, sj))
        story.append(Spacer(1, 2.5 * mm))

        # 2) grey
        story.append(_section2_grey(ctx, sj))
        story.append(Spacer(1, 2.5 * mm))

        # 3) blue
        story.append(_section3_blue(ctx, sj))
        story.append(Spacer(1, 4 * mm))

        # 4) media (no background, keep as is)
        story.append(Paragraph(ctx.t("section.sj.media"), SECTION_TITLE))
        story.append(Spacer(1, 2 * mm))
        story.append(_media_section(ctx, "photos", media_ids["photos"]))
        story.append(_media_section(ctx, "drawings", media_ids["drawings"]))
        story.append(_media_section(ctx, "sketches", media_ids["sketches"]))
        story.append(_media_section(ctx, "photograms", media_ids["photograms"]))

        if idx != len(sj_ids):
            story.append(PageBreak())

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
