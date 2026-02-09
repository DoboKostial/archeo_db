from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Any


@dataclass(frozen=True)
class ReportSpec:
    report_id: str
    title_key: str
    description_key: str
    icon: str = "📄"


# generator signature: (ctx, payload) -> bytes (PDF)
ReportGenerator = Callable[[Any, dict], bytes]


REPORT_SPECS: Dict[str, ReportSpec] = {
    "sample": ReportSpec(
        report_id="sample",
        title_key="report.sample.title",
        description_key="report.sample.description",
        icon="🧪",
    ),


    "sj_cards": ReportSpec(
        report_id="sj_cards",
        title_key="report.sj_cards.title",
        description_key="report.sj_cards.description",
        icon="🧾",
    ),

}


REPORT_GENERATORS: Dict[str, ReportGenerator] = {}



