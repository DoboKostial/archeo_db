from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class ReportContext:
    lang: str
    locale: str
    selected_db: str
    user_email: Optional[str]
    t: Callable[[str], str]  # simple translator function bound to lang
