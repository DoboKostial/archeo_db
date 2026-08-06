# web_app/app/routes/analyze.py
from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, jsonify, render_template, session

from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db
from app.utils.analyze_checks import run_analyze_checks

from app.queries import (
    # stats
    stats_polygons_by_row_sql,
    stats_su_by_type_sql,
    stats_objects_by_type_sql,
    stats_objects_by_su_count_bucket_sql,
    stats_sections_by_type_sql,
    stats_sections_by_su_count_bucket_sql,
    stats_photos_by_type_sql,
    stats_sketches_by_type_sql,
    stats_photograms_vs_drawings_sql,
    stats_finds_by_type_sql,
    stats_samples_by_type_sql,
)

analyze_bp = Blueprint("analyze", __name__)


def _as_pie(labels: List[str], values: List[int], title: str) -> Dict[str, Any]:
    return {"title": title, "labels": labels, "values": values}

def _i0(v) -> int:
    """Safe int() -> None/'' -> 0."""
    try:
        if v is None:
            return 0
        return int(v)
    except Exception:
        return 0
    

@analyze_bp.get("/analyze")
@require_selected_db
def analyze():
    selected_db = session["selected_db"]
    return render_template(
        "analyze.html",
        selected_db=selected_db,
        analyze_groups=None,
        total_issues=None,
        bad_checks_count=None,
        total_checks=None,
    )


@analyze_bp.get("/analyze/stats.json")
@require_selected_db
def analyze_stats_json():
    selected_db = session["selected_db"]
    charts: List[Dict[str, Any]] = []

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            # 1) polygons row1/row2 (can return NULLs)
            cur.execute(stats_polygons_by_row_sql())
            row = cur.fetchone()
            if not row:
                row1, row2 = 0, 0
            else:
                # row might contain None values
                row1 = row[0] if len(row) > 0 else 0
                row2 = row[1] if len(row) > 1 else 0

            charts.append(
                _as_pie(
                    ["row1 (no parent)", "row2 (has parent)"],
                    [_i0(row1), _i0(row2)],
                    "Polygons by nesting level",
                )
            )

            # Helper: rows -> pie (label,value)
            def _rows_to_pie(rows, title: str):
                labels = [(r[0] if r and len(r) > 0 else "") for r in rows]
                values = [_i0(r[1]) if r and len(r) > 1 else 0 for r in rows]
                charts.append(_as_pie(labels, values, title))

            # 2) SU by type
            cur.execute(stats_su_by_type_sql())
            _rows_to_pie(cur.fetchall(), "Stratigraphic units by type")

            # 3) Objects by type
            cur.execute(stats_objects_by_type_sql())
            _rows_to_pie(cur.fetchall(), "Objects by type")

            # 4) Objects by SU count bucket
            cur.execute(stats_objects_by_su_count_bucket_sql())
            _rows_to_pie(cur.fetchall(), "Objects by number of SUs")

            # 5) Sections by type
            cur.execute(stats_sections_by_type_sql())
            _rows_to_pie(cur.fetchall(), "Sections by type")

            # 6) Sections by SU count bucket
            cur.execute(stats_sections_by_su_count_bucket_sql())
            _rows_to_pie(cur.fetchall(), "Sections by number of SUs")

            # 7) Photos by type
            cur.execute(stats_photos_by_type_sql())
            _rows_to_pie(cur.fetchall(), "Photos by type")

            # 8) Sketches by type
            cur.execute(stats_sketches_by_type_sql())
            _rows_to_pie(cur.fetchall(), "Sketches by type")

            # 9) Photograms vs drawings (can return NULLs)
            cur.execute(stats_photograms_vs_drawings_sql())
            row = cur.fetchone()
            if not row:
                photograms, drawings = 0, 0
            else:
                photograms = row[0] if len(row) > 0 else 0
                drawings = row[1] if len(row) > 1 else 0

            charts.append(
                _as_pie(
                    ["photograms", "drawings"],
                    [_i0(photograms), _i0(drawings)],
                    "Photograms vs drawings (count)",
                )
            )

            # 10) Finds by type
            cur.execute(stats_finds_by_type_sql())
            _rows_to_pie(cur.fetchall(), "Finds by type")

            # 11) Samples by type
            cur.execute(stats_samples_by_type_sql())
            _rows_to_pie(cur.fetchall(), "Samples by type")

    return jsonify({"charts": charts})



@analyze_bp.post("/analyze/run")
@require_selected_db
def analyze_run():
    selected_db = session["selected_db"]
    payload = run_analyze_checks(selected_db)

    return render_template(
        "analyze.html",
        selected_db=selected_db,
        analyze_groups=payload["groups"],
        total_issues=payload["total_issues"],
        bad_checks_count=payload["bad_checks_count"],
        total_checks=payload["total_checks"],
    )
