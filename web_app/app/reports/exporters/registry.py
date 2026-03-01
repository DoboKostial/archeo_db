# app/reports/exporters/registry.py
from __future__ import annotations
from typing import Dict
from .base import Exporter
from .sj_cards import SjCardsExporter
from .polygon_cards import PolygonCardsExporter
from .objects_cards import ObjectsCardsExporter
from .sections_cards import SectionsCardsExporter
from .finds_table import FindsTableExporter
from .samples_table import SamplesTableExporter


EXPORTERS = {
    "polygon_cards": PolygonCardsExporter(),
    "sj_cards": SjCardsExporter(),
    "objects_cards": ObjectsCardsExporter(),
    "sections_cards": SectionsCardsExporter(),
    "finds_table": FindsTableExporter(),
    "samples_table": SamplesTableExporter(),
}


def get_exporter(export_id: str) -> Exporter:
    if export_id not in EXPORTERS:
        raise KeyError(f"Unknown export_id '{export_id}'")
    return EXPORTERS[export_id]