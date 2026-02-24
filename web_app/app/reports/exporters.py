# app/reports/exporters.py
from __future__ import annotations

from app.reports.context import ReportContext
from app.reports.exporters.registry import get_exporter


def export_sj_cards_excel(ctx: ReportContext) -> bytes:
    return get_exporter("sj_cards").to_xlsx(ctx)


def export_sj_cards_sql(ctx: ReportContext) -> str:
    return get_exporter("sj_cards").to_sql(ctx)