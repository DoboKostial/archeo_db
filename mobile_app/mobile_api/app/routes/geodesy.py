import csv
import io
import logging

from flask import Blueprint, jsonify, request

from config import Config
from app.auth_tokens import require_mobile_token
from app.database import terrain_connection, terrain_transaction
from app.responses import _json_error
from app.validators import _validate_terrain_db

geodesy_bp = Blueprint("geodesy", __name__)
logger = logging.getLogger("mobile_api.geodesy")

GEOPT_CODES = ["SU", "FX", "EP", "FO", "NI", "PF", "FI", "PR", "SP"]
DEFAULT_LIST_LIMIT = 500
MAX_LIST_LIMIT = 5000
DEFAULT_GEOJSON_LIMIT = 5000
MAX_GEOJSON_LIMIT = 20000
DEFAULT_POLYGON_GEOJSON_LIMIT = 2000
MAX_POLYGON_GEOJSON_LIMIT = 10000
DEFAULT_TEXT_UPLOAD_LIMIT = 8 * 1024 * 1024


def _find_geopts_srid_sql():
    return "SELECT Find_SRID(current_schema()::text, 'tab_geopts'::text, 'pts_geom'::text);"


def _upsert_geopt_sql():
    return """
        WITH p AS (
            SELECT ST_Transform(
                       ST_SetSRID(ST_MakePoint(%s, %s, %s), %s),
                       %s
                   ) AS g
        )
        INSERT INTO tab_geopts (id_pts, x, y, h, code, notes)
        SELECT
            %s,
            ST_X(p.g),
            ST_Y(p.g),
            %s,
            CASE
              WHEN NULLIF(BTRIM(%s), '') IS NULL THEN NULL
              WHEN UPPER(BTRIM(%s)) IN ('SU','FX','EP','FO','NI','PF','FI','PR','SP')
                THEN UPPER(BTRIM(%s))::geopt_code
              ELSE NULL
            END,
            NULLIF(BTRIM(%s), '')
        FROM p
        ON CONFLICT (id_pts) DO UPDATE SET
            x = EXCLUDED.x,
            y = EXCLUDED.y,
            h = EXCLUDED.h,
            code = EXCLUDED.code,
            notes = COALESCE(EXCLUDED.notes, tab_geopts.notes);
    """


def _list_geopts_sql():
    return """
      SELECT id_pts, x, y, h, code::text AS code, notes
      FROM tab_geopts
      WHERE
        (
          %s IS NULL
          OR code::text ILIKE %s
          OR notes ILIKE %s
        )
        AND (%s IS NULL OR id_pts >= %s)
        AND (%s IS NULL OR id_pts <= %s)
      ORDER BY id_pts
      LIMIT %s;
    """


def _update_geopt_sql():
    return """
      UPDATE tab_geopts
      SET
        x = %s,
        y = %s,
        h = %s,
        code = CASE
                 WHEN NULLIF(BTRIM(%s), '') IS NULL THEN NULL
                 WHEN UPPER(BTRIM(%s)) IN ('SU','FX','EP','FO','NI','PF','FI','PR','SP')
                   THEN UPPER(BTRIM(%s))::geopt_code
                 ELSE NULL
               END,
        notes = NULLIF(%s, '')
      WHERE id_pts = %s;
    """


def _delete_geopt_sql():
    return "DELETE FROM tab_geopts WHERE id_pts = %s;"


def _geojson_geopts_bbox_sql():
    return """
      WITH
      bbox AS (
        SELECT ST_Transform(
                 ST_MakeEnvelope(%s, %s, %s, %s, 4326),
                 %s
               ) AS g
      ),
      pts AS (
        SELECT
          g.id_pts,
          g.code::text AS code,
          g.notes,
          ST_Transform(g.pts_geom, 4326) AS geom_4326
        FROM tab_geopts g, bbox b
        WHERE g.pts_geom IS NOT NULL
          AND ST_Intersects(g.pts_geom, b.g)
          AND (%s IS NULL OR g.code::text = %s)
          AND (
            %s IS NULL
            OR g.notes ILIKE %s
            OR g.code::text ILIKE %s
          )
          AND (%s IS NULL OR g.id_pts >= %s)
          AND (%s IS NULL OR g.id_pts <= %s)
        ORDER BY g.id_pts
        LIMIT %s
      )
      SELECT json_build_object(
        'type', 'FeatureCollection',
        'features', COALESCE(json_agg(
          json_build_object(
            'type', 'Feature',
            'geometry', ST_AsGeoJSON(geom_4326)::json,
            'properties', json_build_object(
              'id_pts', id_pts,
              'code', code,
              'notes', notes
            )
          )
        ), '[]'::json)
      )
      FROM pts;
    """


def _geojson_polygons_bbox_sql():
    return """
      WITH
      bbox AS (
        SELECT ST_Transform(
                 ST_MakeEnvelope(%s, %s, %s, %s, 4326),
                 %s
               ) AS g
      ),
      polys AS (
        SELECT
          p.polygon_name,
          ST_Transform(p.geom_top, 4326) AS geom_4326
        FROM tab_polygons p, bbox b
        WHERE p.geom_top IS NOT NULL
          AND ST_Intersects(p.geom_top, b.g)
        ORDER BY p.polygon_name
        LIMIT %s
      )
      SELECT json_build_object(
        'type', 'FeatureCollection',
        'features', COALESCE(json_agg(
          json_build_object(
            'type', 'Feature',
            'geometry', ST_AsGeoJSON(geom_4326)::json,
            'properties', json_build_object('polygon_name', polygon_name)
          )
        ), '[]'::json)
      )
      FROM polys;
    """


def _geopts_extent_4326_sql():
    return """
      SELECT
        ST_XMin(ST_Extent(ST_Transform(pts_geom, 4326))) AS minx,
        ST_YMin(ST_Extent(ST_Transform(pts_geom, 4326))) AS miny,
        ST_XMax(ST_Extent(ST_Transform(pts_geom, 4326))) AS maxx,
        ST_YMax(ST_Extent(ST_Transform(pts_geom, 4326))) AS maxy
      FROM tab_geopts
      WHERE pts_geom IS NOT NULL;
    """


def _read_text_file(file_storage) -> str:
    max_bytes = int(getattr(Config, "MAX_TEXT_UPLOAD_BYTES", DEFAULT_TEXT_UPLOAD_LIMIT))
    raw = file_storage.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("Uploaded text file is too large.")
    for encoding in ("utf-8", "cp1250", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _is_header_row(row: list[str]) -> bool:
    if not row:
        return False
    head = " ".join([cell.lower().strip() for cell in row])
    return ("id" in head and "x" in head and "y" in head) or ("id_pts" in head)


def _parse_points(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith("#") and not line.startswith("//")]
    if not lines:
        return []

    sample = "\n".join(lines[:10])
    delimiter = None
    if ";" in sample and sample.count(";") >= sample.count(","):
        delimiter = ";"
    elif "," in sample:
        delimiter = ","

    rows = []
    if delimiter:
        reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
        rows = [[cell.strip() for cell in row] for row in reader if row and any(cell.strip() for cell in row)]
    else:
        rows = [line.split() for line in lines]

    if rows and _is_header_row(rows[0]):
        rows = rows[1:]

    points = []
    for row in rows:
        if len(row) < 4:
            continue
        try:
            id_pts = int(str(row[0]).strip())
            x = float(str(row[1]).strip().replace(",", "."))
            y = float(str(row[2]).strip().replace(",", "."))
            h = float(str(row[3]).strip().replace(",", "."))
        except (TypeError, ValueError):
            continue

        code = row[4].strip() if len(row) >= 5 and row[4] is not None else None
        notes = row[5].strip() if len(row) >= 6 and row[5] is not None else None
        points.append({"id_pts": id_pts, "x": x, "y": y, "h": h, "code": code, "notes": notes})

    return points


def _optional_int_arg(name: str) -> int | None:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _limit_arg(default: int, maximum: int) -> int:
    raw = (request.args.get("limit") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < 1:
        return default
    return min(value, maximum)


def _parse_bbox_arg():
    raw = (request.args.get("bbox") or "").strip()
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 4:
        return None
    try:
        minx, miny, maxx, maxy = [float(part) for part in parts]
    except (TypeError, ValueError):
        return None
    if minx >= maxx or miny >= maxy:
        return None
    return minx, miny, maxx, maxy


def _target_srid(cur) -> int:
    cur.execute(_find_geopts_srid_sql())
    row = cur.fetchone()
    return int(row[0]) if row and row[0] else 0


def _point_from_row(row) -> dict:
    return {
        "id_pts": row[0],
        "x": float(row[1]),
        "y": float(row[2]),
        "h": float(row[3]),
        "code": row[4],
        "notes": row[5],
    }


def _parse_point_payload(payload: dict, require_id: bool = True) -> dict:
    try:
        id_pts = int(payload.get("id_pts")) if require_id else None
        x = float(payload.get("x"))
        y = float(payload.get("y"))
        h = float(payload.get("h"))
    except (TypeError, ValueError):
        raise ValueError("Point ID, x, y and h must be valid numbers.")

    code = (payload.get("code") or "").strip().upper()
    if code and code not in GEOPT_CODES:
        raise ValueError("Invalid point code.")

    notes = (payload.get("notes") or "").strip()
    return {"id_pts": id_pts, "x": x, "y": y, "h": h, "code": code, "notes": notes}


def _source_epsg_from_request(default_srid: int) -> int:
    raw = (request.form.get("source_epsg") or "").strip()
    if not raw:
        payload = request.get_json(silent=True) or {}
        raw = str(payload.get("source_epsg") or "").strip()
    if not raw:
        return default_srid
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Source EPSG must be an integer.")
    if value <= 0:
        raise ValueError("Source EPSG must be greater than 0.")
    return value


def _run_point_upsert(cur, point: dict, source_srid: int, target_srid: int):
    cur.execute(
        _upsert_geopt_sql(),
        (
            point["x"], point["y"], point["h"], source_srid, target_srid,
            point["id_pts"], point["h"],
            point.get("code"), point.get("code"), point.get("code"),
            point.get("notes") or "",
        ),
    )


def _normalized_bbox(row) -> list[float] | None:
    if not row or any(value is None for value in row):
        return None
    minx, miny, maxx, maxy = [float(value) for value in row]
    if minx == maxx:
        minx -= 0.0005
        maxx += 0.0005
    if miny == maxy:
        miny -= 0.0005
        maxy += 0.0005
    if minx >= maxx or miny >= maxy:
        return None
    return [minx, miny, maxx, maxy]


@geodesy_bp.get("/api/mobile/terrain/<terrain_db>/geodesy/meta")
@require_mobile_token
def geodesy_meta(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                srid = _target_srid(cur)
                cur.execute("SELECT COALESCE(MAX(id_pts), 0) + 1, COUNT(*) FROM tab_geopts")
                suggested_id, point_count = cur.fetchone()
        return jsonify(
            {
                "target_srid": srid,
                "codes": GEOPT_CODES,
                "suggested_id": suggested_id,
                "point_count": point_count,
            }
        )
    except Exception as exc:
        logger.exception("Geodesy meta failed for %s: %s", terrain_db, exc)
        return _json_error("Internal server error.", 500)


@geodesy_bp.get("/api/mobile/terrain/<terrain_db>/geodesy/points")
@require_mobile_token
def list_geodesy_points(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    q = (request.args.get("q") or "").strip() or None
    id_from = _optional_int_arg("id_from")
    id_to = _optional_int_arg("id_to")
    limit = _limit_arg(DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)
    q_like = f"%{q}%" if q else None

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _list_geopts_sql(),
                    (q, q_like, q_like, id_from, id_from, id_to, id_to, limit),
                )
                rows = cur.fetchall()
        return jsonify({"points": [_point_from_row(row) for row in rows]})
    except Exception as exc:
        logger.exception("Geodesy point list failed for %s: %s", terrain_db, exc)
        return _json_error("Internal server error.", 500)


@geodesy_bp.post("/api/mobile/terrain/<terrain_db>/geodesy/points")
@require_mobile_token
def create_geodesy_point(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    payload = request.get_json(silent=True) or {}
    try:
        point = _parse_point_payload(payload)
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                target_srid = _target_srid(cur)
                if target_srid <= 0:
                    raise ValueError("Project SRID is not configured for geodetic points.")
                source_srid = _source_epsg_from_request(target_srid)
                _run_point_upsert(cur, point, source_srid, target_srid)
        return jsonify({"message": f'Point "{point["id_pts"]}" was saved.', "point": point}), 201
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:
        logger.exception("Geodesy point save failed for %s: %s", terrain_db, exc)
        return _json_error("Internal server error.", 500)


@geodesy_bp.post("/api/mobile/terrain/<terrain_db>/geodesy/points/upload")
@require_mobile_token
def upload_geodesy_points(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    file_storage = request.files.get("file")
    if not file_storage:
        return _json_error("File is missing.", 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                target_srid = _target_srid(cur)
                if target_srid <= 0:
                    raise ValueError("Project SRID is not configured for geodetic points.")
                source_srid = _source_epsg_from_request(target_srid)
                points = _parse_points(_read_text_file(file_storage))
                if not points:
                    raise ValueError("No valid points found in the uploaded file.")
                for point in points:
                    _run_point_upsert(cur, point, source_srid, target_srid)
        return jsonify({"message": f"Import finished: {len(points)} points processed.", "imported": len(points)})
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:
        logger.exception("Geodesy point upload failed for %s: %s", terrain_db, exc)
        return _json_error("Internal server error.", 500)


@geodesy_bp.put("/api/mobile/terrain/<terrain_db>/geodesy/points/<int:id_pts>")
@require_mobile_token
def update_geodesy_point(terrain_db: str, id_pts: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    payload = request.get_json(silent=True) or {}
    try:
        point = _parse_point_payload(payload, require_id=False)
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _update_geopt_sql(),
                    (
                        point["x"],
                        point["y"],
                        point["h"],
                        point.get("code"),
                        point.get("code"),
                        point.get("code"),
                        point.get("notes") or "",
                        id_pts,
                    ),
                )
                if cur.rowcount == 0:
                    return _json_error("Point not found.", 404)
        return jsonify({"message": f'Point "{id_pts}" was updated.'})
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:
        logger.exception("Geodesy point update failed for %s: %s", terrain_db, exc)
        return _json_error("Internal server error.", 500)


@geodesy_bp.delete("/api/mobile/terrain/<terrain_db>/geodesy/points/<int:id_pts>")
@require_mobile_token
def delete_geodesy_point(terrain_db: str, id_pts: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(_delete_geopt_sql(), (id_pts,))
                if cur.rowcount == 0:
                    return _json_error("Point not found.", 404)
        return jsonify({"message": f'Point "{id_pts}" was deleted.'})
    except Exception as exc:
        logger.exception("Geodesy point delete failed for %s: %s", terrain_db, exc)
        return _json_error("Internal server error.", 500)


@geodesy_bp.get("/api/mobile/terrain/<terrain_db>/geodesy/points/geojson")
@require_mobile_token
def geodesy_points_geojson(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    bbox = _parse_bbox_arg()
    if not bbox:
        return jsonify({"type": "FeatureCollection", "features": []})

    code = (request.args.get("code") or "").strip().upper() or None
    q = (request.args.get("q") or "").strip() or None
    id_from = _optional_int_arg("id_from")
    id_to = _optional_int_arg("id_to")
    limit = _limit_arg(DEFAULT_GEOJSON_LIMIT, MAX_GEOJSON_LIMIT)
    q_like = f"%{q}%" if q else None

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                target_srid = _target_srid(cur)
                if target_srid <= 0:
                    return jsonify({"type": "FeatureCollection", "features": []})
                cur.execute(
                    _geojson_geopts_bbox_sql(),
                    (
                        bbox[0], bbox[1], bbox[2], bbox[3], target_srid,
                        code, code,
                        q, q_like, q_like,
                        id_from, id_from,
                        id_to, id_to,
                        limit,
                    ),
                )
                feature_collection = cur.fetchone()[0]
        return jsonify(feature_collection)
    except Exception as exc:
        logger.exception("Geodesy GeoJSON failed for %s: %s", terrain_db, exc)
        return _json_error("Internal server error.", 500)


@geodesy_bp.get("/api/mobile/terrain/<terrain_db>/geodesy/polygons/geojson")
@require_mobile_token
def geodesy_polygons_geojson(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    bbox = _parse_bbox_arg()
    if not bbox:
        return jsonify({"type": "FeatureCollection", "features": []})

    limit = _limit_arg(DEFAULT_POLYGON_GEOJSON_LIMIT, MAX_POLYGON_GEOJSON_LIMIT)

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                target_srid = _target_srid(cur)
                if target_srid <= 0:
                    return jsonify({"type": "FeatureCollection", "features": []})
                cur.execute(
                    _geojson_polygons_bbox_sql(),
                    (bbox[0], bbox[1], bbox[2], bbox[3], target_srid, limit),
                )
                feature_collection = cur.fetchone()[0]
        return jsonify(feature_collection)
    except Exception as exc:
        logger.exception("Geodesy polygon GeoJSON failed for %s: %s", terrain_db, exc)
        return _json_error("Internal server error.", 500)


@geodesy_bp.get("/api/mobile/terrain/<terrain_db>/geodesy/extent")
@require_mobile_token
def geodesy_extent(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(_geopts_extent_4326_sql())
                bbox = _normalized_bbox(cur.fetchone())
        return jsonify({"bbox": bbox})
    except Exception as exc:
        logger.exception("Geodesy extent failed for %s: %s", terrain_db, exc)
        return _json_error("Internal server error.", 500)
