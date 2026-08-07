from __future__ import annotations

from collections import OrderedDict
from typing import Any

from flask import url_for

from app.database import get_terrain_connection
from app.logger import logger
from app.queries import (
    rule_geopts_outside_srid_envelope_sql,
    rule_objects_without_su_sql,
    rule_orphan_drawings_sql,
    rule_orphan_photograms_sql,
    rule_orphan_photos_sql,
    rule_orphan_sketches_sql,
    rule_polygons_bottom_outside_top_sql,
    rule_polygons_missing_edges_sql,
    rule_polygons_missing_geopts_sql,
    rule_polygons_overlap_same_row_sql,
    rule_polygons_without_su_sql,
    rule_sections_without_any_documentation_sql,
    rule_sections_without_su_sql,
    rule_su_without_any_documentation_sql,
    rule_su_without_polygon_sql,
    rule_su_without_relation_sql,
)


def _link(kind: str, value: Any) -> str | None:
    if value is None or value == "":
        return None

    if kind == "polygon":
        return url_for("polygons.polygons", edit_polygon=value)
    if kind == "su":
        return url_for("su.add_su", edit_su=value)
    if kind == "object":
        return url_for("archeo_objects.objects", edit_object=value)
    if kind == "section":
        return url_for("sections.sections", edit_section=value)
    if kind == "photo":
        return url_for("photos.photos", edit_photo=value)
    if kind == "photogram":
        return url_for("photograms.photograms", edit_photogram=value)
    if kind == "sketch":
        return url_for("sketches.sketches", edit_sketch=value)
    if kind == "drawing":
        return url_for("drawings.drawings", edit_drawing=value)
    if kind == "geopt":
        return url_for("geodesy.geodesy", edit_geopt=value)

    return None


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if value is None or value == "":
        return "—"
    return str(value)


def _sql_for_exists(sql: str) -> str:
    return sql.strip().rstrip(";")


Rule = dict[str, Any]


RULES: list[Rule] = [
    {
        "category": "Polygons",
        "code": "POLY_NO_SU",
        "title": "Polygons without linked SUs",
        "sql": rule_polygons_without_su_sql,
        "columns": [("polygon_name", "Polygon")],
        "links": [("polygon", "polygon_name", "Edit polygon")],
        "module": "polygons.polygons",
    },
    {
        "category": "Polygons",
        "code": "POLY_OVERLAP",
        "title": "Same-level polygons overlap",
        "sql": rule_polygons_overlap_same_row_sql,
        "columns": [("side", "Side"), ("polygon_a", "Polygon A"), ("polygon_b", "Polygon B")],
        "links": [("polygon", "polygon_a", "Edit polygon A"), ("polygon", "polygon_b", "Edit polygon B")],
        "module": "polygons.polygons",
    },
    {
        "category": "Polygons",
        "code": "POLY_MISSING_EDGES",
        "title": "Polygons missing TOP/BOTTOM edge geometry",
        "sql": rule_polygons_missing_edges_sql,
        "columns": [
            ("polygon_name", "Polygon"),
            ("has_top_binding", "TOP range"),
            ("has_top_geom", "TOP geom"),
            ("has_bottom_binding", "BOTTOM range"),
            ("has_bottom_geom", "BOTTOM geom"),
        ],
        "links": [("polygon", "polygon_name", "Edit polygon")],
        "module": "polygons.polygons",
    },
    {
        "category": "Polygons",
        "code": "POLY_BOTTOM_OUTSIDE_TOP",
        "title": "Polygon BOTTOM edge lies outside TOP edge",
        "sql": rule_polygons_bottom_outside_top_sql,
        "columns": [("polygon_name", "Polygon"), ("outside_area", "Outside area")],
        "links": [("polygon", "polygon_name", "Edit polygon")],
        "module": "polygons.polygons",
    },
    {
        "category": "Polygons",
        "code": "POLY_MISSING_GEOPTS",
        "title": "Polygon ranges reference missing geodetic points",
        "sql": rule_polygons_missing_geopts_sql,
        "columns": [("polygon_name", "Polygon"), ("side", "Side"), ("missing_geopt_ids", "Missing points")],
        "links": [("polygon", "polygon_name", "Edit polygon")],
        "module": "polygons.polygons",
    },
    {
        "category": "Stratigraphic Units",
        "code": "SU_NO_DOC",
        "title": "SUs without any graphic documentation",
        "sql": rule_su_without_any_documentation_sql,
        "columns": [("id_sj", "SU")],
        "links": [("su", "id_sj", "Edit SU")],
        "module": "su.add_su",
    },
    {
        "category": "Stratigraphic Units",
        "code": "SU_NO_REL",
        "title": "SUs without any stratigraphic relation",
        "sql": rule_su_without_relation_sql,
        "columns": [("id_sj", "SU")],
        "links": [("su", "id_sj", "Edit SU")],
        "module": "su.add_su",
    },
    {
        "category": "Stratigraphic Units",
        "code": "SU_NO_POLYGON",
        "title": "SUs without linked polygon",
        "sql": rule_su_without_polygon_sql,
        "columns": [("id_sj", "SU")],
        "links": [("su", "id_sj", "Edit SU")],
        "module": "su.add_su",
    },
    {
        "category": "Objects",
        "code": "OBJ_NO_SU",
        "title": "Objects without linked SUs",
        "sql": rule_objects_without_su_sql,
        "columns": [("id_object", "Object")],
        "links": [("object", "id_object", "Edit object")],
        "module": "archeo_objects.objects",
    },
    {
        "category": "Sections",
        "code": "SEC_NO_SU",
        "title": "Sections without linked SUs",
        "sql": rule_sections_without_su_sql,
        "columns": [("id_section", "Section")],
        "links": [("section", "id_section", "Edit section")],
        "module": "sections.sections",
    },
    {
        "category": "Sections",
        "code": "SEC_NO_DOC",
        "title": "Sections without any graphic documentation",
        "sql": rule_sections_without_any_documentation_sql,
        "columns": [("id_section", "Section")],
        "links": [("section", "id_section", "Edit section")],
        "module": "sections.sections",
    },
    {
        "category": "Graphic Documentation",
        "code": "ORPH_PHOTO",
        "title": "Orphan photos",
        "sql": rule_orphan_photos_sql,
        "columns": [("id_photo", "Photo")],
        "links": [("photo", "id_photo", "Edit photo")],
        "module": "photos.photos",
    },
    {
        "category": "Graphic Documentation",
        "code": "ORPH_PHOTOGRAM",
        "title": "Orphan photograms",
        "sql": rule_orphan_photograms_sql,
        "columns": [("id_photogram", "Photogram")],
        "links": [("photogram", "id_photogram", "Edit photogram")],
        "module": "photograms.photograms",
    },
    {
        "category": "Graphic Documentation",
        "code": "ORPH_SKETCH",
        "title": "Orphan sketches",
        "sql": rule_orphan_sketches_sql,
        "columns": [("id_sketch", "Sketch")],
        "links": [("sketch", "id_sketch", "Edit sketch")],
        "module": "sketches.sketches",
    },
    {
        "category": "Graphic Documentation",
        "code": "ORPH_DRAWING",
        "title": "Orphan drawings",
        "sql": rule_orphan_drawings_sql,
        "columns": [("id_drawing", "Drawing")],
        "links": [("drawing", "id_drawing", "Edit drawing")],
        "module": "drawings.drawings",
    },
    {
        "category": "Geodesy",
        "code": "GEOPT_OUTSIDE_ENVELOPE",
        "title": "Geodetic points outside SRID envelope",
        "sql": rule_geopts_outside_srid_envelope_sql,
        "columns": [
            ("id_pts", "Point"),
            ("x", "X"),
            ("y", "Y"),
            ("h", "H"),
            ("srid", "SRID"),
            ("reason", "Reason"),
        ],
        "links": [("geopt", "id_pts", "Edit point")],
        "module": "geodesy.geodesy",
    },
]


def _build_issue(rule: Rule, row: tuple[Any, ...]) -> dict[str, Any]:
    columns = rule["columns"]
    row_map = {key: row[idx] if idx < len(row) else None for idx, (key, _label) in enumerate(columns)}
    fields = [
        {"key": key, "label": label, "value": row_map.get(key), "display": _format_value(row_map.get(key))}
        for key, label in columns
    ]

    links = []
    for kind, column, label in rule.get("links", []):
        value = row_map.get(column)
        url = _link(kind, value)
        if url:
            links.append({"label": f"{label} {_format_value(value)}", "url": url})

    summary = ", ".join(field["display"] for field in fields if field["display"] != "—")
    return {"summary": summary, "fields": fields, "links": links}


def _module_link(rule: Rule) -> dict[str, str] | None:
    endpoint = rule.get("module")
    if not endpoint:
        return None
    return {"label": "Open module", "url": url_for(endpoint)}


def run_analyze_checks(selected_db: str) -> dict[str, Any]:
    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    flat_results = []

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            for rule in RULES:
                result = {
                    "category": rule["category"],
                    "code": rule["code"],
                    "title": rule["title"],
                    "count": 0,
                    "issues": [],
                    "module_link": None,
                    "error": None,
                }

                try:
                    cur.execute(rule["sql"]())
                    rows = cur.fetchall()
                    result["count"] = len(rows)
                    result["issues"] = [_build_issue(rule, row) for row in rows]
                    result["module_link"] = _module_link(rule)
                except Exception as e:
                    result["error"] = str(e)
                    logger.error(f"[{selected_db}] analyze rule failed {rule['code']}: {e}")

                flat_results.append(result)
                category = grouped.setdefault(
                    rule["category"],
                    {"name": rule["category"], "checks": [], "bad_checks": 0, "issue_count": 0},
                )
                category["checks"].append(result)
                if result["error"] or result["count"] > 0:
                    category["bad_checks"] += 1
                if not result["error"]:
                    category["issue_count"] += result["count"]

    return {
        "groups": list(grouped.values()),
        "flat_results": flat_results,
        "total_issues": sum(r["count"] for r in flat_results if not r["error"]),
        "bad_checks_count": sum(1 for r in flat_results if r["error"] or r["count"] > 0),
        "total_checks": len(flat_results),
    }


def count_bad_checks(selected_db: str) -> int:
    bad = 0
    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            for rule in RULES:
                try:
                    cur.execute(f"SELECT EXISTS ({_sql_for_exists(rule['sql']())})")
                    if bool(cur.fetchone()[0]):
                        bad += 1
                except Exception as e:
                    bad += 1
                    logger.error(f"[{selected_db}] analyze bad-check count failed {rule['code']}: {e}")
    return bad
