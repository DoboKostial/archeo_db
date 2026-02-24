# app/reports/exporters/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.reports.context import ReportContext


class Exporter(Protocol):
    export_id: str

    def to_xlsx(self, ctx: ReportContext) -> bytes: ...
    def to_sql(self, ctx: ReportContext) -> str: ...


@dataclass(frozen=True)
class ExportResult:
    """
    Optional helper if you later want to return filename/mime together.
    Not required right now.
    """
    data: bytes
    filename: str
    mimetype: str