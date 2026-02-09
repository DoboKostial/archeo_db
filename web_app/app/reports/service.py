from __future__ import annotations

from typing import Optional, Tuple, Dict

from app.i18n.reporting.translator import ReportingTranslator
from app.reports.context import ReportContext
from app.reports.registry import REPORT_GENERATORS, REPORT_SPECS
from app.reports.sample_report import generate_sample_pdf
from app.reports.sj_cards_report import generate_sj_cards_pdf


def init_report_generators() -> None:
    """
    Register built-in report generators.
    Call once during app init.
    """
    REPORT_GENERATORS.setdefault("sample", generate_sample_pdf)
    REPORT_GENERATORS.setdefault("sj_cards", generate_sj_cards_pdf)


def build_report_context(
    translator: ReportingTranslator,
    selected_db: str,
    user_email: Optional[str],
    lang: Optional[str],
) -> ReportContext:
    lang_norm = translator.normalize_lang(lang)
    specs = translator.get_language_specs()
    locale = specs[lang_norm].locale if lang_norm in specs else "en_US"

    def _t(key: str) -> str:
        return translator.t(key, lang=lang_norm)

    return ReportContext(
        lang=lang_norm,
        locale=locale,
        selected_db=selected_db,
        user_email=user_email,
        t=_t,
    )


def generate_report_pdf(report_id: str, ctx: ReportContext, payload: dict) -> Tuple[bytes, str]:
    if report_id not in REPORT_SPECS:
        raise KeyError(f"Unknown report_id '{report_id}'")

    gen = REPORT_GENERATORS.get(report_id)
    if not gen:
        raise KeyError(f"No generator registered for report_id '{report_id}'")

    pdf_bytes = gen(ctx, payload or {})
    filename = f"{report_id}_{ctx.selected_db}_{ctx.lang}.pdf"
    return pdf_bytes, filename
