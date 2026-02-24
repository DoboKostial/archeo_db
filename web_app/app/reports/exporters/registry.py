# app/reports/exporters/registry.py
from __future__ import annotations

from typing import Dict

from .base import Exporter
from .sj_cards import SjCardsExporter


EXPORTERS: Dict[str, Exporter] = {
    "sj_cards": SjCardsExporter(),
}


def get_exporter(export_id: str) -> Exporter:
    if export_id not in EXPORTERS:
        raise KeyError(f"Unknown export_id '{export_id}'")
    return EXPORTERS[export_id]