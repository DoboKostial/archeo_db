import json
import logging
import os
from urllib.parse import quote

from flask import Blueprint, g, jsonify, request, send_file

from app.database import terrain_connection, terrain_transaction
from app.auth_tokens import require_mobile_token
from app.media import (
    PHOTO_TYP_CHOICES,
    PHOTOGRAM_TYP_CHOICES,
    SKETCH_TYP_CHOICES,
    _ensure_author_exists,
    _media_file_path,
    _store_media_upload,
)
from app.responses import _json_error
from app.validators import _validate_terrain_db

polygons_bp = Blueprint("polygons", __name__)
logger = logging.getLogger("mobile_api.polygons")

ALLOWED_ALLOCATIONS = {
    "physical_separation",
    "research_phase",
    "horizontal_stratigraphy",
    "other",
}

MEDIA_KIND_CONFIG = {
    "photos": {
        "table": "tab_photos",
        "id_col": "id_photo",
        "type_col": "photo_typ",
        "link_table": "tabaid_polygon_photos",
        "link_media_col": "ref_photo",
        "allowed_types": PHOTO_TYP_CHOICES,
        "media_dir": "photos",
    },
    "sketches": {
        "table": "tab_sketches",
        "id_col": "id_sketch",
        "type_col": "sketch_typ",
        "link_table": "tabaid_polygon_sketches",
        "link_media_col": "ref_sketch",
        "allowed_types": SKETCH_TYP_CHOICES,
        "media_dir": "sketches",
    },
    "photograms": {
        "table": "tab_photograms",
        "id_col": "id_photogram",
        "type_col": "photogram_typ",
        "link_table": "tabaid_polygon_photograms",
        "link_media_col": "ref_photogram",
        "allowed_types": PHOTOGRAM_TYP_CHOICES,
        "media_dir": "photograms",
    },
}


def _media_content_path(terrain_db: str, kind: str, media_id: str) -> str:
    return f"/api/mobile/terrain/{terrain_db}/media/{kind}/{quote(media_id)}"


def _validate_media_kind(kind: str):
    if kind not in MEDIA_KIND_CONFIG:
        raise ValueError("Unsupported media kind.")
    return MEDIA_KIND_CONFIG[kind]


def _validate_media_type(kind: str, value: str):
    cfg = _validate_media_kind(kind)
    if value not in cfg["allowed_types"]:
        raise ValueError("Invalid media type.")
    return cfg


def _parse_ranges(raw_ranges, label: str):
    if raw_ranges is None:
        return []
    if not isinstance(raw_ranges, list):
        raise ValueError(f"{label} must be a list.")

    parsed = []
    for item in raw_ranges:
        if not isinstance(item, dict):
            raise ValueError(f"{label} contains invalid range item.")
        start = item.get("from")
        end = item.get("to")
        if start is None or end is None:
            raise ValueError(f"{label} range must contain both 'from' and 'to'.")
        try:
            start_i = int(start)
            end_i = int(end)
        except (TypeError, ValueError):
            raise ValueError(f"{label} range values must be integers.")
        if start_i > end_i:
            raise ValueError(f"{label} range is invalid: {start_i} > {end_i}.")
        parsed.append((start_i, end_i))
    return parsed


def _polygon_exists(cur, polygon_name: str) -> bool:
    cur.execute("SELECT 1 FROM tab_polygons WHERE polygon_name = %s", (polygon_name,))
    return cur.fetchone() is not None


def _load_polygon_ranges(cur, polygon_name: str):
    cur.execute(
        """
        SELECT pts_from, pts_to
        FROM tab_polygon_geopts_binding_top
        WHERE ref_polygon = %s
        ORDER BY pts_from, pts_to
        """,
        (polygon_name,),
    )
    top_ranges = [{"from": row[0], "to": row[1]} for row in cur.fetchall()]

    cur.execute(
        """
        SELECT pts_from, pts_to
        FROM tab_polygon_geopts_binding_bottom
        WHERE ref_polygon = %s
        ORDER BY pts_from, pts_to
        """,
        (polygon_name,),
    )
    bottom_ranges = [{"from": row[0], "to": row[1]} for row in cur.fetchall()]

    return top_ranges, bottom_ranges


def _load_polygon_detail(cur, polygon_name: str):
    cur.execute(
        """
        SELECT
            p.polygon_name,
            p.parent_name,
            p.allocation_reason::text,
            p.notes,
            COALESCE(ST_NPoints(p.geom_top), 0) + COALESCE(ST_NPoints(p.geom_bottom), 0) AS npoints,
            EXISTS (
                SELECT 1
                FROM tab_polygon_geopts_binding_top bt
                WHERE bt.ref_polygon = p.polygon_name
                LIMIT 1
            ) AS has_top,
            EXISTS (
                SELECT 1
                FROM tab_polygon_geopts_binding_bottom bb
                WHERE bb.ref_polygon = p.polygon_name
                LIMIT 1
            ) AS has_bottom
        FROM tab_polygons p
        WHERE p.polygon_name = %s
        """,
        (polygon_name,),
    )
    row = cur.fetchone()
    if not row:
        return None

    top_ranges, bottom_ranges = _load_polygon_ranges(cur, polygon_name)
    return {
        "name": row[0],
        "parent_name": row[1],
        "allocation_reason": row[2],
        "notes": row[3],
        "point_count": row[4],
        "has_top": row[5],
        "has_bottom": row[6],
        "top_ranges": top_ranges,
        "bottom_ranges": bottom_ranges,
    }


def _save_polygon(cur, polygon_name: str, parent_name: str, allocation_reason: str, notes: str, top_ranges, bottom_ranges):
    cur.execute(
        """
        INSERT INTO tab_polygons (polygon_name, parent_name, allocation_reason, notes)
        VALUES (%s, NULLIF(%s,''), %s, NULLIF(%s,''))
        ON CONFLICT (polygon_name)
        DO UPDATE SET
            parent_name = EXCLUDED.parent_name,
            allocation_reason = EXCLUDED.allocation_reason,
            notes = EXCLUDED.notes
        """,
        (polygon_name, parent_name, allocation_reason, notes),
    )

    cur.execute(
        "DELETE FROM tab_polygon_geopts_binding_top WHERE ref_polygon = %s",
        (polygon_name,),
    )
    cur.execute(
        "DELETE FROM tab_polygon_geopts_binding_bottom WHERE ref_polygon = %s",
        (polygon_name,),
    )

    for start_i, end_i in top_ranges:
        cur.execute(
            """
            INSERT INTO tab_polygon_geopts_binding_top (ref_polygon, pts_from, pts_to)
            VALUES (%s, %s, %s)
            ON CONFLICT (ref_polygon, pts_from, pts_to) DO NOTHING
            """,
            (polygon_name, start_i, end_i),
        )

    for start_i, end_i in bottom_ranges:
        cur.execute(
            """
            INSERT INTO tab_polygon_geopts_binding_bottom (ref_polygon, pts_from, pts_to)
            VALUES (%s, %s, %s)
            ON CONFLICT (ref_polygon, pts_from, pts_to) DO NOTHING
            """,
            (polygon_name, start_i, end_i),
        )

    cur.execute("SELECT rebuild_polygon_geoms_from_geopts(%s)", (polygon_name,))


def _list_polygon_media(cur, terrain_db: str, polygon_name: str):
    output = {
        "photos": [],
        "sketches": [],
        "photograms": [],
    }

    for kind, cfg in MEDIA_KIND_CONFIG.items():
        cur.execute(
            f"""
            SELECT
                m.{cfg['id_col']},
                m.{cfg['type_col']},
                m.notes,
                m.mime_type
            FROM {cfg['link_table']} l
            JOIN {cfg['table']} m
              ON m.{cfg['id_col']} = l.{cfg['link_media_col']}
            WHERE l.ref_polygon = %s
            ORDER BY m.{cfg['id_col']}
            """,
            (polygon_name,),
        )
        for media_id, media_type, notes, mime_type in cur.fetchall():
            output[kind].append(
                {
                    "kind": kind,
                    "id": media_id,
                    "type": media_type,
                    "notes": notes,
                    "mime_type": mime_type,
                    "content_path": _media_content_path(terrain_db, kind, media_id),
                }
            )
    return output


def _polygon_media_preview_map(cur, terrain_db: str):
    previews = {}
    for kind, cfg in MEDIA_KIND_CONFIG.items():
        cur.execute(
            f"""
            SELECT
                l.ref_polygon,
                m.{cfg['id_col']},
                m.mime_type
            FROM {cfg['link_table']} l
            JOIN {cfg['table']} m
              ON m.{cfg['id_col']} = l.{cfg['link_media_col']}
            ORDER BY l.ref_polygon, m.{cfg['id_col']}
            """
        )
        for polygon_name, media_id, mime_type in cur.fetchall():
            polygon_items = previews.setdefault(polygon_name, [])
            if len(polygon_items) >= 4:
                continue
            polygon_items.append(
                {
                    "kind": kind,
                    "id": media_id,
                    "mime_type": mime_type,
                    "content_path": _media_content_path(terrain_db, kind, media_id),
                }
            )
    return previews


def _link_media_to_polygon(cur, kind: str, polygon_name: str, media_id: str):
    cfg = MEDIA_KIND_CONFIG[kind]
    cur.execute(
        f"""
        INSERT INTO {cfg['link_table']} (ref_polygon, {cfg['link_media_col']})
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (polygon_name, media_id),
    )


def _compute_polygon_side_geojson(cur, polygon_name: str, side_table: str):
    cur.execute(
        f"""
        WITH ranges AS (
            SELECT pts_from, pts_to
            FROM {side_table}
            WHERE ref_polygon = %s
        ),
        pts AS (
            SELECT DISTINCT ON (g.id_pts) g.id_pts, g.pts_geom
            FROM ranges r
            JOIN tab_geopts g
              ON g.id_pts BETWEEN r.pts_from AND r.pts_to
            WHERE g.pts_geom IS NOT NULL
            ORDER BY g.id_pts
        ),
        line_base AS (
            SELECT
                CASE
                    WHEN COUNT(*) >= 2 THEN ST_MakeLine(ARRAY_AGG(pts_geom ORDER BY id_pts))
                    ELSE NULL
                END AS geom
            FROM pts
        ),
        line_closed AS (
            SELECT
                CASE
                    WHEN geom IS NULL THEN NULL
                    WHEN ST_Equals(ST_StartPoint(geom), ST_EndPoint(geom))
                        THEN ST_RemoveRepeatedPoints(geom, 1e-7)
                    ELSE ST_RemoveRepeatedPoints(ST_AddPoint(geom, ST_StartPoint(geom)), 1e-7)
                END AS geom
            FROM line_base
        ),
        poly_try AS (
            SELECT
                CASE
                    WHEN geom IS NOT NULL
                         AND ST_NPoints(geom) >= 4
                         AND ST_IsSimple(geom)
                        THEN ST_MakePolygon(
                            CASE
                                WHEN ST_CoordDim(geom) < 3 THEN ST_Force3D(geom)
                                ELSE geom
                            END
                        )
                    ELSE NULL
                END AS geom
            FROM line_closed
        )
        SELECT
            CASE
                WHEN poly_try.geom IS NOT NULL AND ST_IsValid(poly_try.geom)
                    THEN ST_AsGeoJSON(ST_Transform(ST_Force2D(poly_try.geom), 4326))
                WHEN line_base.geom IS NOT NULL
                    THEN ST_AsGeoJSON(ST_Transform(ST_Force2D(line_base.geom), 4326))
                ELSE NULL
            END
        FROM line_base
        CROSS JOIN line_closed
        CROSS JOIN poly_try
        """,
        (polygon_name,),
    )
    row = cur.fetchone()
    return json.loads(row[0]) if row and row[0] else None


@polygons_bp.get("/api/mobile/terrain/<terrain_db>/polygons")
@require_mobile_token
def list_polygons(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        p.polygon_name,
                        p.parent_name,
                        p.allocation_reason::text,
                        p.notes,
                        COALESCE(ST_NPoints(p.geom_top), 0) + COALESCE(ST_NPoints(p.geom_bottom), 0) AS npoints,
                        EXISTS (
                            SELECT 1
                            FROM tab_polygon_geopts_binding_top bt
                            WHERE bt.ref_polygon = p.polygon_name
                            LIMIT 1
                        ) AS has_top,
                        EXISTS (
                            SELECT 1
                            FROM tab_polygon_geopts_binding_bottom bb
                            WHERE bb.ref_polygon = p.polygon_name
                            LIMIT 1
                        ) AS has_bottom
                    FROM tab_polygons p
                    ORDER BY p.polygon_name
                    """
                )
                rows = cur.fetchall()
                preview_map = _polygon_media_preview_map(cur, terrain_db)

        return jsonify(
            {
                "polygons": [
                    {
                        "name": row[0],
                        "parent_name": row[1],
                        "allocation_reason": row[2],
                        "notes": row[3],
                        "point_count": row[4],
                        "has_top": row[5],
                        "has_bottom": row[6],
                        "media_preview": preview_map.get(row[0], []),
                    }
                    for row in rows
                ]
            }
        )

    except Exception as e:
        logger.exception("Polygon list failed for %s: %s", terrain_db, e)
        return _json_error("Internal server error.", 500)


@polygons_bp.post("/api/mobile/terrain/<terrain_db>/polygons")
@require_mobile_token
def create_polygon(terrain_db: str):
    claims = g.mobile_claims

    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    payload = request.get_json(silent=True) or {}
    polygon_name = (payload.get("polygon_name") or "").strip()
    parent_name = (payload.get("parent_name") or "").strip()
    allocation_reason = (payload.get("allocation_reason") or "").strip()
    notes = (payload.get("notes") or "").strip()

    try:
        if not polygon_name:
            raise ValueError("Polygon name is required.")
        if parent_name and parent_name == polygon_name:
            raise ValueError("Parent polygon cannot be the same as polygon name.")
        if allocation_reason not in ALLOWED_ALLOCATIONS:
            raise ValueError("Invalid allocation reason.")

        top_ranges = _parse_ranges(payload.get("top_ranges"), "Top ranges")
        bottom_ranges = _parse_ranges(payload.get("bottom_ranges"), "Bottom ranges")
        if not top_ranges and not bottom_ranges:
            raise ValueError("Provide at least one TOP or BOTTOM range of points.")
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                _save_polygon(cur, polygon_name, parent_name, allocation_reason, notes, top_ranges, bottom_ranges)
                polygon = _load_polygon_detail(cur, polygon_name)

        logger.info(
            "Polygon saved in %s by %s: %s",
            terrain_db,
            claims.get("email", ""),
            polygon_name,
        )
        return jsonify(
            {
                "message": f'Polygon "{polygon_name}" was saved.',
                "polygon": polygon,
            }
        ), 201

    except Exception as e:
        logger.exception("Polygon save failed for %s/%s: %s", terrain_db, polygon_name, e)
        return _json_error("Internal server error.", 500)


@polygons_bp.get("/api/mobile/terrain/<terrain_db>/polygons/geojson")
@require_mobile_token
def polygons_geojson(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        polygon_name,
                        CASE WHEN geom_top IS NOT NULL
                          THEN ST_AsGeoJSON(ST_Transform(ST_Force2D(geom_top), 4326))
                          ELSE NULL END AS top_gj,
                        CASE WHEN geom_bottom IS NOT NULL
                          THEN ST_AsGeoJSON(ST_Transform(ST_Force2D(geom_bottom), 4326))
                          ELSE NULL END AS bottom_gj
                    FROM tab_polygons
                    ORDER BY polygon_name
                    """
                )
                rows = cur.fetchall()

                top_list = []
                bottom_list = []
                for polygon_name, top_gj, bottom_gj in rows:
                    top_geojson = json.loads(top_gj) if top_gj else _compute_polygon_side_geojson(
                        cur,
                        polygon_name,
                        "tab_polygon_geopts_binding_top",
                    )
                    bottom_geojson = json.loads(bottom_gj) if bottom_gj else _compute_polygon_side_geojson(
                        cur,
                        polygon_name,
                        "tab_polygon_geopts_binding_bottom",
                    )

                    if top_geojson:
                        top_list.append({"name": polygon_name, "geojson": top_geojson})
                    if bottom_geojson:
                        bottom_list.append({"name": polygon_name, "geojson": bottom_geojson})

        return jsonify({"top": top_list, "bottom": bottom_list})

    except Exception as e:
        logger.exception("Polygon geojson failed for %s: %s", terrain_db, e)
        return _json_error("Internal server error.", 500)


@polygons_bp.get("/api/mobile/terrain/<terrain_db>/polygons/<polygon_name>")
@require_mobile_token
def get_polygon(terrain_db: str, polygon_name: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                polygon = _load_polygon_detail(cur, polygon_name)
                if not polygon:
                    return _json_error("Polygon not found.", 404)
        return jsonify({"polygon": polygon})

    except Exception as e:
        logger.exception("Polygon detail failed for %s/%s: %s", terrain_db, polygon_name, e)
        return _json_error("Internal server error.", 500)


@polygons_bp.get("/api/mobile/terrain/<terrain_db>/polygons/<polygon_name>/media")
@require_mobile_token
def list_polygon_media(terrain_db: str, polygon_name: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                if not _polygon_exists(cur, polygon_name):
                    return _json_error("Polygon not found.", 404)
                media = _list_polygon_media(cur, terrain_db, polygon_name)
        return jsonify(
            {
                "polygon_name": polygon_name,
                "photos": media["photos"],
                "sketches": media["sketches"],
                "photograms": media["photograms"],
            }
        )
    except Exception as e:
        logger.exception("Polygon media list failed for %s/%s: %s", terrain_db, polygon_name, e)
        return _json_error("Internal server error.", 500)


@polygons_bp.post("/api/mobile/terrain/<terrain_db>/polygons/<polygon_name>/media")
@require_mobile_token
def upload_polygon_media(terrain_db: str, polygon_name: str):
    claims = g.mobile_claims

    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    kind = (request.form.get("kind") or "").strip()
    media_type = (request.form.get("typ") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    file_storage = request.files.get("file")

    try:
        cfg = _validate_media_type(kind, media_type)
        if file_storage is None or not file_storage.filename:
            raise ValueError("Missing uploaded file.")
    except ValueError as e:
        return _json_error(str(e), 400)

    final_path = None
    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if not _polygon_exists(cur, polygon_name):
                    return _json_error("Polygon not found.", 404)
                if not _ensure_author_exists(cur, claims.get("email", "")):
                    return _json_error("Current mobile user is not available in project personalia.", 400)

                media_id, mime_type, final_path = _store_media_upload(
                    cur,
                    terrain_db,
                    kind,
                    file_storage,
                    media_type,
                    claims.get("email", ""),
                    notes or None,
                )
                _link_media_to_polygon(cur, kind, polygon_name, media_id)

        logger.info(
            "Polygon media uploaded in %s by %s: polygon=%s kind=%s id=%s",
            terrain_db,
            claims.get("email", ""),
            polygon_name,
            kind,
            media_id,
        )
        return jsonify(
            {
                "message": f"{kind[:-1].capitalize()} was attached to polygon \"{polygon_name}\".",
                "media": {
                    "kind": kind,
                    "id": media_id,
                    "type": media_type,
                    "notes": notes or None,
                    "mime_type": mime_type,
                    "content_path": _media_content_path(terrain_db, kind, media_id),
                },
            }
        ), 201
    except Exception as e:
        if final_path and os.path.exists(final_path):
            try:
                os.remove(final_path)
            except Exception:
                pass
        logger.exception("Polygon media upload failed for %s/%s: %s", terrain_db, polygon_name, e)
        if isinstance(e, ValueError):
            return _json_error(str(e), 400)
        return _json_error("Internal server error.", 500)


@polygons_bp.get("/api/mobile/terrain/<terrain_db>/media/<kind>/<media_id>")
@require_mobile_token
def get_polygon_media_content(terrain_db: str, kind: str, media_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        _validate_media_kind(kind)
        path = _media_file_path(terrain_db, kind, media_id)
        if not os.path.exists(path):
            return _json_error("Media file not found.", 404)
        return send_file(path, conditional=True)
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Polygon media content failed for %s/%s/%s: %s", terrain_db, kind, media_id, e)
        return _json_error("Internal server error.", 500)


@polygons_bp.put("/api/mobile/terrain/<terrain_db>/polygons/<polygon_name>")
@require_mobile_token
def update_polygon(terrain_db: str, polygon_name: str):
    claims = g.mobile_claims

    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    payload = request.get_json(silent=True) or {}
    body_name = (payload.get("polygon_name") or polygon_name).strip()
    if body_name != polygon_name:
        return _json_error("Polygon name cannot be changed in edit mode.", 400)

    parent_name = (payload.get("parent_name") or "").strip()
    allocation_reason = (payload.get("allocation_reason") or "").strip()
    notes = (payload.get("notes") or "").strip()

    try:
        if parent_name and parent_name == polygon_name:
            raise ValueError("Parent polygon cannot be the same as polygon name.")
        if allocation_reason not in ALLOWED_ALLOCATIONS:
            raise ValueError("Invalid allocation reason.")
        top_ranges = _parse_ranges(payload.get("top_ranges"), "Top ranges")
        bottom_ranges = _parse_ranges(payload.get("bottom_ranges"), "Bottom ranges")
        if not top_ranges and not bottom_ranges:
            raise ValueError("Provide at least one TOP or BOTTOM range of points.")
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if not _polygon_exists(cur, polygon_name):
                    return _json_error("Polygon not found.", 404)

                _save_polygon(cur, polygon_name, parent_name, allocation_reason, notes, top_ranges, bottom_ranges)
                polygon = _load_polygon_detail(cur, polygon_name)

        logger.info(
            "Polygon updated in %s by %s: %s",
            terrain_db,
            claims.get("email", ""),
            polygon_name,
        )
        return jsonify(
            {
                "message": f'Polygon "{polygon_name}" was updated.',
                "polygon": polygon,
            }
        )

    except Exception as e:
        logger.exception("Polygon update failed for %s/%s: %s", terrain_db, polygon_name, e)
        return _json_error("Internal server error.", 500)


@polygons_bp.delete("/api/mobile/terrain/<terrain_db>/polygons/<polygon_name>")
@require_mobile_token
def delete_polygon(terrain_db: str, polygon_name: str):
    claims = g.mobile_claims

    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT parent_name FROM tab_polygons WHERE polygon_name = %s",
                    (polygon_name,),
                )
                row = cur.fetchone()
                if not row:
                    return _json_error("Polygon not found.", 404)

                parent_of_deleted = row[0]
                cur.execute(
                    "UPDATE tab_polygons SET parent_name = %s WHERE parent_name = %s",
                    (parent_of_deleted, polygon_name),
                )
                cur.execute("DELETE FROM tab_polygons WHERE polygon_name = %s", (polygon_name,))

        logger.info(
            "Polygon deleted in %s by %s: %s",
            terrain_db,
            claims.get("email", ""),
            polygon_name,
        )
        return jsonify({"message": f'Polygon "{polygon_name}" was deleted.'})

    except Exception as e:
        logger.exception("Polygon delete failed for %s/%s: %s", terrain_db, polygon_name, e)
        return _json_error("Internal server error.", 500)
