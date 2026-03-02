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
    order: int = 1000  # UI ordering (lower = earlier)


# generator signature: (ctx, payload) -> bytes (PDF)
ReportGenerator = Callable[[Any, dict], bytes]


REPORT_SPECS: Dict[str, ReportSpec] = {
    "sj_cards": ReportSpec(
        report_id="sj_cards",
        title_key="report.sj_cards.title",
        description_key="report.sj_cards.description",
        icon="🧾",
        formats=frozenset({"pdf", "xlsx", "sql"}),
        order=10,
    ),
    "objects_cards": ReportSpec(
        report_id="objects_cards",
        title_key="report.objects_cards.title",
        description_key="report.objects_cards.description",
        icon="🧱",
        formats=frozenset({"pdf", "xlsx", "sql"}),
        order=20,
    ),
    "polygon_cards": ReportSpec(
        report_id="polygon_cards",
        title_key="report.polygon_cards.title",
        description_key="report.polygon_cards.description",
        icon="⬠",
        formats=frozenset({"pdf", "xlsx", "sql"}),
        order=30,
    ),
    "sections_cards": ReportSpec(
        report_id="sections_cards",
        title_key="report.sections_cards.title",
        description_key="report.sections_cards.description",
        icon="📐",
        formats=frozenset({"pdf", "xlsx", "sql"}),
        order=40,
    ),
    "finds_table": ReportSpec(
        report_id="finds_table",
        title_key="report.finds_table.title",
        description_key="report.finds_table.description",
        icon="📋",
        formats=frozenset({"pdf", "xlsx", "sql"}),
        order=50,
    ),
    "samples_table": ReportSpec(
        report_id="samples_table",
        title_key="report.samples_table.title",
        description_key="report.samples_table.description",
        icon="🧪",
        formats=frozenset({"pdf", "xlsx", "sql"}),
        order=60,
    ),
    "geopts_table": ReportSpec(
        report_id="geopts_table",
        title_key="report.geopts_table.title",
        description_key="report.geopts_table.description",
        icon="📍",
        formats=frozenset({"pdf", "xlsx", "sql"}),
        order=70,
    ),
    "photos_table": ReportSpec(
        report_id="photos_table",
        title_key="report.photos_table.title",
        description_key="report.photos_table.description",
        icon="📷",
        formats=frozenset({"pdf", "xlsx", "sql"}),
        order=80,
    ),  

}

REPORT_GENERATORS: Dict[str, ReportGenerator] = {}