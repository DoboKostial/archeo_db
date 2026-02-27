# app/reports/objects_cards_report.py
from __future__ import annotations

import io
import os
import json
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
    report_objects_cards_list_objects_sql,
    report_objects_cards_detail_sql,
    report_objects_cards_inhum_grave_sql,
    report_sj_cards_media_ids_sql,          # reuse existing SJ media logic
)

from config import Config


# -------------------------
# Fonts (same as sj_cards)
# -------------------------
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
TITLE = ParagraphStyle("ObjTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=14, leading=16)
HEADER_SMALL = ParagraphStyle("ObjHeaderSmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=9, leading=11, textColor=colors.grey)
SECTION_TITLE = ParagraphStyle("ObjSectionTitle", parent=_styles["Normal"], fontName=FONT_BOLD, fontSize=10, leading=12)
LABEL = ParagraphStyle("ObjLabel", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10, textColor=colors.grey)
VALUE = ParagraphStyle("ObjValue", parent=_styles["Normal"], fontName=FONT_REG, fontSize=9, leading=11)
SMALL = ParagraphStyle("ObjSmall", parent=_styles["Normal"], fontName=FONT_REG, fontSize=8, leading=10)
CAPTION = ParagraphStyle("ObjCaption", parent=_styles["Normal"], fontName=FONT_REG, fontSize=7, leading=9, textColor=colors.grey, alignment=1)

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


# ---- media thumbs (reuse same approach as sj_cards) ----
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


def _fetch_object_detail(conn, id_object: int) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(report_objects_cards_detail_sql(), (id_object,))
        row = cur.fetchone()
        if not row:
            return {}
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def _fetch_inhum(conn, id_object: int) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(report_objects_cards_inhum_grave_sql(), (id_object,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def _fetch_object_ids(ctx: ReportContext) -> List[int]:
    with get_terrain_connection(ctx.selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(report_objects_cards_list_objects_sql())
            return [int(r[0]) for r in cur.fetchall()]


def _fetch_media_ids_for_object(conn, sj_ids: List[int], kind: str, limit_ids: int = 50) -> List[str]:
    """
    Aggregate media IDs across all SJs of the object.
    Deduplicate while preserving order. Limit to keep it fast.
    """
    seen = set()
    out: List[str] = []
    for sj_id in sj_ids:
        with conn.cursor() as cur:
            cur.execute(report_sj_cards_media_ids_sql(kind), (sj_id,))
            ids = [str(r[0]) for r in cur.fetchall()]
        for mid in ids:
            if mid in seen:
                continue
            seen.add(mid)
            out.append(mid)
            if len(out) >= limit_ids:
                return out
    return out


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


def _page_header(ctx: ReportContext) -> Table:
    action_prefix, db_label = _parse_db_label(ctx.selected_db)
    left = Paragraph(ctx.t("header.objects_list.title"), TITLE)
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


def _section1_orange(ctx: ReportContext, o: Dict[str, Any]) -> Table:
    sj_ids = o.get("sj_ids") or []
    sj_count = len(sj_ids)

    row1 = Table([[
        Paragraph(ctx.t("field.object.id"), LABEL), Paragraph(_v(o.get("id_object")), VALUE),
        Paragraph(ctx.t("field.object.type"), LABEL), Paragraph(_v(o.get("object_typ")) or "—", VALUE),
    ]], colWidths=[22*mm, 24*mm, 18*mm, 126*mm])

    row2 = Table([[
        Paragraph(ctx.t("field.object.superior"), LABEL), Paragraph(_v(o.get("superior_object")) or "—", VALUE),
        Paragraph(ctx.t("field.object.sj_count"), LABEL), Paragraph(str(sj_count), VALUE),
    ]], colWidths=[28*mm, 48*mm, 26*mm, 88*mm])

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


def _section2_grey(ctx: ReportContext, o: Dict[str, Any]) -> Table:
    notes = _truncate(_v(o.get("notes")), 520) or "—"
    row = Table([[
        Paragraph(ctx.t("field.object.notes"), LABEL),
        Paragraph(notes, VALUE),
    ]], colWidths=[22*mm, 168*mm])

    outer = Table([[row]], colWidths=[A4[0] - 24*mm])
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_GREY),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return outer


def _section3_blue(ctx: ReportContext, o: Dict[str, Any]) -> Table:
    sj_ids = o.get("sj_ids") or []
    shown = sj_ids[:20]
    more = max(0, len(sj_ids) - len(shown))
    sj_txt = ", ".join(str(x) for x in shown) if shown else "—"
    more_txt = f"+ {more} {ctx.t('common.more')}" if more else ""

    row1 = Table([[
        Paragraph(ctx.t("field.object.sj_list"), LABEL),
        Paragraph(sj_txt, VALUE),
    ]], colWidths=[22*mm, 168*mm])

    row2 = Table([[
        Paragraph("", LABEL),
        Paragraph(more_txt, SMALL),
    ]], colWidths=[22*mm, 168*mm])

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


def _inhum_grave_block(ctx: ReportContext, inhum: Dict[str, Any]) -> Table:
    """
    Shows bone_map image + selected keys from bone_map JSON.
    """
    title = Paragraph(ctx.t("section.object.inhum.title"), SECTION_TITLE)

    preservation = _v(inhum.get("preservation")) or "—"
    orientation = _v(inhum.get("orientation_dir")) or "—"
    box_type = _v(inhum.get("burial_box_type")) or "—"
    anthropo = _v(inhum.get("anthropo_present"))
    notes = _truncate(_v(inhum.get("notes_grave")), 280) or "—"

    # bone_map present keys
    present_keys: List[str] = []
    bone_map = inhum.get("bone_map")
    if bone_map:
        try:
            if isinstance(bone_map, str):
                bone_map = json.loads(bone_map)
            if isinstance(bone_map, dict):
                present_keys = [k for k, v in bone_map.items() if bool(v)]
            elif isinstance(bone_map, list):
                # if stored as list of keys
                present_keys = [str(x) for x in bone_map]
        except Exception:
            present_keys = []

    present_txt = ", ".join(present_keys) if present_keys else "—"

    # image path (filesystem)
    img_path_candidates = [
        os.path.join("app", "static", "images", "bone_map.png"),
        os.path.join("web_app", "app", "static", "images", "bone_map.png"),
    ]
    img_path = next((p for p in img_path_candidates if os.path.exists(p)), "")

    img = _safe_image(img_path, max_w=70*mm, max_h=85*mm)
    if img is None:
        img_cell: Any = Paragraph(ctx.t("common.no_image"), SMALL) if hasattr(ctx, "t") else Paragraph("—", SMALL)
    else:
        img_cell = img

    info = Table([
        [Paragraph(ctx.t("field.inhum.preservation"), LABEL), Paragraph(preservation, VALUE)],
        [Paragraph(ctx.t("field.inhum.orientation_dir"), LABEL), Paragraph(orientation, VALUE)],
        [Paragraph(ctx.t("field.inhum.burial_box_type"), LABEL), Paragraph(box_type, VALUE)],
        [Paragraph(ctx.t("field.inhum.anthropo_present"), LABEL), Paragraph(anthropo, VALUE)],
        [Paragraph(ctx.t("field.inhum.bone_map_present"), LABEL), Paragraph(present_txt, VALUE)],
        [Paragraph(ctx.t("field.inhum.notes_grave"), LABEL), Paragraph(notes, VALUE)],
    ], colWidths=[38*mm, 82*mm])
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))

    body = Table([[img_cell, info]], colWidths=[75*mm, 115*mm])
    body.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    outer = Table([[title], [body]], colWidths=[A4[0] - 24*mm])
    outer.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.3, colors.lightgrey),
    ]))
    return outer


def generate_objects_cards_pdf(ctx: ReportContext, payload: dict) -> bytes:
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
        title="Objects cards",
        author=ctx.user_email or "",
    )

    obj_ids = _fetch_object_ids(ctx)
    logger.info(f"[{ctx.selected_db}] Objects cards: {len(obj_ids)} pages, lang={ctx.lang}")

    total_pages = len(obj_ids)

    def _on_page(canv, d):
        page_no = canv.getPageNumber()
        _footer(canv, d, footer_left, f"{ctx.t('common.page')} {page_no}/{total_pages}")

    story: List[Any] = []

    for idx, oid in enumerate(obj_ids, start=1):
        with get_terrain_connection(ctx.selected_db) as conn:
            o = _fetch_object_detail(conn, oid)
            if not o:
                continue

            sj_ids = o.get("sj_ids") or []
            inhum = _fetch_inhum(conn, oid)

            media_ids = {
                "photos": _fetch_media_ids_for_object(conn, sj_ids, "photos", limit_ids=60),
                "drawings": _fetch_media_ids_for_object(conn, sj_ids, "drawings", limit_ids=60),
                "sketches": _fetch_media_ids_for_object(conn, sj_ids, "sketches", limit_ids=60),
                "photograms": _fetch_media_ids_for_object(conn, sj_ids, "photograms", limit_ids=60),
            }

        story.append(_page_header(ctx))
        story.append(Spacer(1, 3 * mm))

        story.append(_section1_orange(ctx, o))
        story.append(Spacer(1, 2.5 * mm))

        story.append(_section2_grey(ctx, o))
        story.append(Spacer(1, 2.5 * mm))

        story.append(_section3_blue(ctx, o))
        story.append(Spacer(1, 4 * mm))

        if inhum:
            story.append(_inhum_grave_block(ctx, inhum))
            story.append(Spacer(1, 4 * mm))

        story.append(Paragraph(ctx.t("section.object.media"), SECTION_TITLE))
        story.append(Spacer(1, 2 * mm))
        story.append(_media_section(ctx, "photos", media_ids["photos"]))
        story.append(_media_section(ctx, "drawings", media_ids["drawings"]))
        story.append(_media_section(ctx, "sketches", media_ids["sketches"]))
        story.append(_media_section(ctx, "photograms", media_ids["photograms"]))

        if idx != len(obj_ids):
            story.append(PageBreak())

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()