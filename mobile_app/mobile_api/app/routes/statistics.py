import logging

from flask import Blueprint, jsonify

from app.database import terrain_connection
from app.auth_tokens import require_mobile_token
from app.responses import _json_error
from app.validators import _validate_terrain_db

statistics_bp = Blueprint("statistics", __name__)
logger = logging.getLogger("mobile_api.statistics")


def _count(cur, table_name: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table_name}")
    return int(cur.fetchone()[0])


@statistics_bp.get("/api/mobile/terrain/<terrain_db>/statistics")
@require_mobile_token
def get_statistics(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                terrain = {
                    "polygons": _count(cur, "tab_polygons"),
                    "sjs_total": _count(cur, "tab_sj"),
                    "deposits": _count(cur, "tab_sj_deposit"),
                    "negatives": _count(cur, "tab_sj_negativ"),
                    "structures": _count(cur, "tab_sj_structure"),
                    "objects": _count(cur, "tab_object"),
                    "sections": _count(cur, "tab_section"),
                    "finds": _count(cur, "tab_finds"),
                    "samples": _count(cur, "tab_samples"),
                }
                documentation = {
                    "photos": _count(cur, "tab_photos"),
                    "sketches": _count(cur, "tab_sketches"),
                    "drawings": _count(cur, "tab_drawings"),
                    "photograms": _count(cur, "tab_photograms"),
                }
        return jsonify(
            {
                "terrain_db": terrain_db,
                "terrain": terrain,
                "documentation": documentation,
            }
        )
    except Exception as e:
        logger.exception("Statistics failed for %s: %s", terrain_db, e)
        return _json_error("Internal server error.", 500)
