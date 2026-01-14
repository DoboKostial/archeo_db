# web_app/app/routes/analyze.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional

from flask import Blueprint, jsonify, render_template, session, url_for

from app.database import get_terrain_connection
from app.logger import logger
from app.utils.decorators import require_selected_db

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
    # rules
    rule_polygons_without_su_sql,
    rule_polygons_overlap_same_row_sql,
    rule_polygons_missing_edges_sql,
    rule_su_without_photo_sql,
    rule_su_without_sketch_sql,
    rule_su_without_relation_sql,
    rule_sections_without_su_sql,
    rule_sections_without_photo_sql,
    rule_sections_without_sketch_sql,
    rule_orphan_photos_sql,
    rule_orphan_sketches_sql,
    rule_orphan_drawings_sql,
    rule_orphan_photograms_sql,
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
    return render_template("analyze.html", selected_db=selected_db, analyze_results=None, total_issues=None)


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
    results: List[Dict[str, Any]] = []

    def _add_rule(code: str, title: str, sql: str, module_url: str):
        try:
            with get_terrain_connection(selected_db) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    rows = cur.fetchall()

            results.append({
                "code": code,
                "title": title,
                "count": len(rows),
                "rows": rows,           # analyze.html si to případně vykreslí do tabulky
                "module_url": module_url,
                "error": None,
            })
        except Exception as e:
            results.append({
                "code": code,
                "title": title,
                "count": 0,
                "rows": [],
                "module_url": module_url,
                "error": str(e),
            })
            logger.error(f"[{selected_db}] analyze rule failed {code}: {e}")

    _add_rule("POLY_NO_SU",        "Polygons without linked SUs",                         rule_polygons_without_su_sql(),        url_for("polygons.polygons"))
    _add_rule("POLY_OVERLAP",      "Overlap between polygons of same nesting level",      rule_polygons_overlap_same_row_sql(),  url_for("polygons.polygons"))
    _add_rule("POLY_MISSING_EDGES","Polygons missing top/bottom geometry",                rule_polygons_missing_edges_sql(),     url_for("polygons.polygons"))

    _add_rule("SU_NO_PHOTO",       "SUs without any linked photo",                        rule_su_without_photo_sql(),           url_for("su.add_su"))
    _add_rule("SU_NO_SKETCH",      "SUs without any linked sketch",                       rule_su_without_sketch_sql(),          url_for("su.add_su"))
    _add_rule("SU_NO_REL",         "SUs without any stratigraphic relation",              rule_su_without_relation_sql(),        url_for("su.harrismatrix"))

    _add_rule("SEC_NO_SU",         "Sections without linked SUs",                         rule_sections_without_su_sql(),        url_for("sections.sections"))
    _add_rule("SEC_NO_PHOTO",      "Sections without any linked photo",                   rule_sections_without_photo_sql(),     url_for("sections.sections"))
    _add_rule("SEC_NO_SKETCH",     "Sections without any linked sketch",                  rule_sections_without_sketch_sql(),    url_for("sections.sections"))

    _add_rule("ORPH_PHOTO",        "Orphan photos (no links to SU/Polygon/Section/Find)", rule_orphan_photos_sql(),             url_for("photos.photos"))
    _add_rule("ORPH_SKETCH",       "Orphan sketches (no links to SU/Polygon/Section/...)",rule_orphan_sketches_sql(),           url_for("sketches.sketches"))
    _add_rule("ORPH_DRAWING",      "Orphan drawings (no links to SU/Section)",            rule_orphan_drawings_sql(),           url_for("drawings.drawings"))
    _add_rule("ORPH_PHOTOGRAM",    "Orphan photograms (no links)",                        rule_orphan_photograms_sql(),          url_for("photograms.photograms"))

    total_issues = sum(r["count"] for r in results if not r.get("error"))

    return render_template(
        "analyze.html",
        selected_db=selected_db,
        analyze_results=results,
        total_issues=total_issues,
    )
