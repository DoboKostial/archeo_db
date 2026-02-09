from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .context import ReportContext


def generate_sample_pdf(ctx: ReportContext, payload: dict) -> bytes:
    """
    Minimal PDF generator (canvas) to prove end-to-end i18n & routing.
    Later you will likely switch to platypus for real tables/flows.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    y = height - 20 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, y, ctx.t("report.sample.title"))

    y -= 10 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, ctx.t("report.sample.description"))

    y -= 12 * mm
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.drawString(20 * mm, y, f"{ctx.t('common.generated_on')}: {now}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"{ctx.t('common.database')}: {ctx.selected_db}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"{ctx.t('common.user')}: {ctx.user_email or '—'}")

    c.showPage()
    c.save()

    return buf.getvalue()
