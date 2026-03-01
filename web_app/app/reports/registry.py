# app/reports/registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Any, FrozenSet


@dataclass(frozen=True)
class ReportSpec:
    """
    Report metadata for UI and routing.
    'formats' controls which buttons/actions appear on /reports and which endpoints are valid.
    """
    report_id: str
    title_key: str
    description_key: str
    icon: str = "📄"
    formats: FrozenSet[str] = frozenset({"pdf"})  # default: only PDF


# generator signature: (ctx, payload) -> bytes (PDF)
ReportGenerator = Callable[[Any, dict], bytes]


REPORT_SPECS: Dict[str, ReportSpec] = {
    "polygon_cards": ReportSpec(
        report_id="polygon_cards",
        title_key="report.polygon_cards.title",
        description_key="report.polygon_cards.description",
        icon="⬠",
        formats=frozenset({"pdf", "xlsx", "sql"}),
    ),
    "sj_cards": ReportSpec(
        report_id="sj_cards",
        title_key="report.sj_cards.title",
        description_key="report.sj_cards.description",
        icon="🧾",
        formats=frozenset({"pdf", "xlsx", "sql"}),
    ),
    "objects_cards": ReportSpec(
        report_id="objects_cards",
        title_key="report.objects_cards.title",
        description_key="report.objects_cards.description",
        icon="🧱",
        formats=frozenset({"pdf", "xlsx", "sql"}),
    ),
    "sections_cards": ReportSpec(
        report_id="sections_cards",
        title_key="report.sections_cards.title",
        description_key="report.sections_cards.description",
        icon="📐",
        formats=frozenset({"pdf", "xlsx", "sql"}),
    ),
}

REPORT_GENERATORS: Dict[str, ReportGenerator] = {}