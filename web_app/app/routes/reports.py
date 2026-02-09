# app/routes/reports.py
from __future__ import annotations

import io
from typing import Any, Dict

from flask import Blueprint, render_template, request, session, send_file, abort, g, flash, redirect, url_for

from app.logger import logger
from app.i18n.reporting.translator import ReportingTranslator
from app.reports.registry import REPORT_SPECS
from app.reports.service import build_report_context, generate_report_pdf
from app.utils.decorators import require_selected_db 

reports_bp = Blueprint("reports", __name__)

translator = ReportingTranslator(logger=logger)


@reports_bp.get("/reports")
@require_selected_db
def reports():
    selected_db = session.get("selected_db") or ""
    user_email = getattr(g, "user_email", "") or ""

    lang = request.args.get("lang")
    lang_norm = translator.normalize_lang(lang)

    try:
        logger.info(f"[{selected_db}] /reports opened by {user_email or '—'} lang={lang_norm}")

        # Languages from manifest
        lang_specs = translator.get_language_specs()
        languages = [
            {"code": spec.code, "label": spec.label, "icon": spec.icon, "locale": spec.locale}
            for spec in lang_specs.values()
        ]
        languages.sort(key=lambda x: x["code"])

        # Build localized report list
        ctx = build_report_context(
            translator=translator,
            selected_db=selected_db,
            user_email=user_email,
            lang=lang_norm,
        )

        reports = []
        for rid, spec in REPORT_SPECS.items():
            reports.append({
                "id": rid,
                "icon": spec.icon,
                "title": ctx.t(spec.title_key),
                "description": ctx.t(spec.description_key),
            })
        reports.sort(key=lambda x: x["id"])

        return render_template(
            "reports.html",
            lang=lang_norm,
            languages=languages,
            reports=reports,
            t=ctx.t,
        )

    except Exception as e:
        logger.error(f"[{selected_db}] Error while loading /reports: {e}")
        flash("Error while loading Reports.", "danger")
        # Keep the app responsive; return an empty page with flashed message
        return render_template(
            "reports.html",
            lang=lang_norm,
            languages=[],
            reports=[],
            t=lambda k: k,
        )


@reports_bp.post("/reports/<report_id>/pdf")
@require_selected_db
def generate_report(report_id: str):
    selected_db = session.get("selected_db") or ""
    user_email = getattr(g, "user_email", "") or ""

    lang = request.args.get("lang")

    try:
        ctx = build_report_context(
            translator=translator,
            selected_db=selected_db,
            user_email=user_email,
            lang=lang,
        )

        payload: Dict[str, Any] = {}

        logger.info(f"[{selected_db}] Generating report '{report_id}' lang={ctx.lang} user={user_email or '—'}")

        pdf_bytes, filename = generate_report_pdf(report_id, ctx, payload)

        logger.info(f"[{selected_db}] Report '{report_id}' generated OK: {filename} user={user_email or '—'}")

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    except KeyError as e:
        logger.error(f"[{selected_db}] Report '{report_id}' not found: {e}")
        flash("Unknown report type.", "danger")
        return abort(404)

    except Exception as e:
        logger.error(f"[{selected_db}] Error while generating report '{report_id}': {e}")
        flash("Error while generating report PDF.", "danger")
        # redirect back to reports page, keep current lang
        return redirect(url_for("reports.reports", lang=translator.normalize_lang(lang)))
