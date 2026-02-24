# app/reports/exporters/utils_excel.py
from __future__ import annotations

from typing import List
from openpyxl.utils import get_column_letter


def set_basic_column_widths(ws, headers: List[str]) -> None:
    # cheap default widths; you can enhance later to measure content
    for col_idx in range(1, len(headers) + 1):
        col = get_column_letter(col_idx)
        ws.column_dimensions[col].width = min(60, max(12, len(headers[col_idx - 1]) + 2))