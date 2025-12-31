# app/utils/labels.py

from __future__ import annotations

import io
from typing import Iterable, List

from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.graphics.barcode import qr
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing


def a6_pagesize() -> tuple[float, float]:
    """
    A6 landscape: 148 × 105 mm (na šířku).
    """
    return (148 * mm, 105 * mm)


def _qr_widget(value: str, size_mm: float = 30.0) -> Drawing:
    """
    Returns a Drawing containing a QR code scaled to size_mm × size_mm.
    Scaling is done via Drawing transform (QrCodeWidget has no .scale()).
    """
    widget = qr.QrCodeWidget(value)

    x1, y1, x2, y2 = widget.getBounds()
    w = x2 - x1
    h = y2 - y1
    size = size_mm * mm

    if w <= 0 or h <= 0:
        return Drawing(size, size)

    sx = size / w
    sy = size / h

    # translate by -x1,-y1 (scaled) so QR starts at (0,0)
    d = Drawing(size, size, transform=[sx, 0, 0, sy, -x1 * sx, -y1 * sy])
    d.add(widget)
    return d


def _wrap_text(text: str, font_name: str, font_size: float, max_width: float) -> List[str]:
    """
    Simple word-wrapping for ReportLab canvas.
    """
    text = (text or "").strip()
    if not text:
        return []

    words = text.split()
    lines: List[str] = []
    cur = ""

    for w in words:
        cand = (cur + " " + w).strip()
        if stringWidth(cand, font_name, font_size) <= max_width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            # if single word is too long, hard-split it
            if stringWidth(w, font_name, font_size) <= max_width:
                cur = w
            else:
                chunk = ""
                for ch in w:
                    cand2 = chunk + ch
                    if stringWidth(cand2, font_name, font_size) <= max_width:
                        chunk = cand2
                    else:
                        if chunk:
                            lines.append(chunk)
                        chunk = ch
                cur = chunk

    if cur:
        lines.append(cur)

    return lines


def make_a6_label_pdf_bytes(
    title: str,
    lines: Iterable[str],
    url: str,
    *,
    qr_size_mm: float = 30.0,
    margin_mm: float = 8.0,
    gap_mm: float = 7.0,
) -> bytes:
    """
    Generates A6 landscape PDF label with:
      - QR left (URL payload)
      - Title + wrapped text right
      - URL footer at bottom

    Layout guards:
      - QR block is reserved
      - text block width is computed from page width - margins - QR width - gap
      - text is wrapped to avoid overflow
      - footer is kept separate at bottom
    """
    buf = io.BytesIO()
    page_w, page_h = a6_pagesize()

    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    margin = margin_mm * mm
    gap = gap_mm * mm
    qr_size = qr_size_mm * mm

    # --- QR placement (top-left) ---
    qr_x = margin
    qr_y = page_h - margin - qr_size  # top margin
    d = _qr_widget(url, size_mm=qr_size_mm)
    renderPDF.draw(d, c, qr_x, qr_y)

    # --- Text block (right side) ---
    text_x = qr_x + qr_size + gap
    text_w = page_w - margin - text_x
    if text_w < 30 * mm:
        # If very small (should not happen on A6), fall back to using full width below QR.
        text_x = margin
        text_w = page_w - 2 * margin

    # fonts
    title_font = "Helvetica-Bold"
    title_size = 14
    body_font = "Helvetica"
    body_size = 10
    footer_font = "Helvetica"
    footer_size = 8

    # footer reserved height
    footer_h = 10 * mm

    # top baseline for title aligned with QR top
    top_y = page_h - margin

    # Title (wrap if needed)
    c.setFont(title_font, title_size)
    title_lines = _wrap_text(title or "", title_font, title_size, text_w)
    if not title_lines:
        title_lines = [""]

    line_h_title = 6.5 * mm
    y = top_y - title_size * 0.35  # small optical adjustment

    for tl in title_lines[:2]:  # guard: max 2 title lines
        c.drawString(text_x, y, tl)
        y -= line_h_title

    # Body lines (wrap each input line)
    c.setFont(body_font, body_size)
    line_h_body = 5.0 * mm

    # Start body a bit below title, but never above QR if text is on the right
    body_y = y - 1.0 * mm
    min_y = margin + footer_h  # keep space for footer

    wrapped: List[str] = []
    for ln in lines:
        wrapped.extend(_wrap_text(str(ln), body_font, body_size, text_w))

    for wl in wrapped:
        if body_y < min_y:
            # guard: stop if we hit footer zone
            break
        c.drawString(text_x, body_y, wl)
        body_y -= line_h_body

    # URL footer
    c.setFont(footer_font, footer_size)
    # also wrap footer if extremely long
    footer_lines = _wrap_text(url, footer_font, footer_size, page_w - 2 * margin)
    footer_y = margin
    for fl in footer_lines[:2]:
        c.drawString(margin, footer_y, fl)
        footer_y += 4.0 * mm  # upward if multiple lines

    c.showPage()
    c.save()

    pdf = buf.getvalue()
    buf.close()
    return pdf
