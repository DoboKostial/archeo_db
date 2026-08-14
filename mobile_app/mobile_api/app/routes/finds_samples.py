import logging
import os
from urllib.parse import quote

from flask import Blueprint, g, jsonify, request, send_file

from app.database import terrain_connection, terrain_transaction
from app.auth_tokens import require_mobile_token
from app.media import (
    PHOTO_TYP_CHOICES,
    SKETCH_TYP_CHOICES,
    _ensure_author_exists,
    _media_file_path,
    _store_media_upload,
)
from app.responses import _json_error
from app.validators import _validate_terrain_db

finds_samples_mobile_bp = Blueprint("finds_samples_mobile", __name__)
logger = logging.getLogger("mobile_api.finds_samples")

FEATURE_CONFIG = {
    "finds": {
        "table": "tab_finds",
        "id_col": "id_find",
        "type_col": "ref_find_type",
        "gloss_table": "gloss_find_type",
        "media": {
            "photos": {
                "table": "tab_photos",
                "id_col": "id_photo",
                "type_col": "photo_typ",
                "link_table": "tabaid_finds_photos",
                "link_ref_col": "ref_find",
                "link_media_col": "ref_photo",
                "allowed_types": PHOTO_TYP_CHOICES,
                "media_dir": "photos",
            },
            "sketches": {
                "table": "tab_sketches",
                "id_col": "id_sketch",
                "type_col": "sketch_typ",
                "link_table": "tabaid_finds_sketches",
                "link_ref_col": "ref_find",
                "link_media_col": "ref_sketch",
                "allowed_types": SKETCH_TYP_CHOICES,
                "media_dir": "sketches",
            },
        },
    },
    "samples": {
        "table": "tab_samples",
        "id_col": "id_sample",
        "type_col": "ref_sample_type",
        "gloss_table": "gloss_sample_type",
        "media": {
            "photos": {
                "table": "tab_photos",
                "id_col": "id_photo",
                "type_col": "photo_typ",
                "link_table": "tabaid_samples_photos",
                "link_ref_col": "ref_sample",
                "link_media_col": "ref_photo",
                "allowed_types": PHOTO_TYP_CHOICES,
                "media_dir": "photos",
            },
            "sketches": {
                "table": "tab_sketches",
                "id_col": "id_sketch",
                "type_col": "sketch_typ",
                "link_table": "tabaid_samples_sketches",
                "link_ref_col": "ref_sample",
                "link_media_col": "ref_sketch",
                "allowed_types": SKETCH_TYP_CHOICES,
                "media_dir": "sketches",
            },
        },
    },
}


def _nullable_text(value):
    text = (value or "").strip()
    return text or None


def _nullable_int(value):
    text = (value or "").strip()
    if not text:
        return None
    return int(text)


def _feature_cfg(feature_id: str):
    cfg = FEATURE_CONFIG.get(feature_id)
    if cfg is None:
        raise ValueError("Invalid feature.")
    return cfg


def _feature_media_content_path(terrain_db: str, feature_id: str, kind: str, media_id: str) -> str:
    return f"/api/mobile/terrain/{terrain_db}/{feature_id}_media/{kind}/{quote(media_id)}"


def _list_types(cur, feature_id: str):
    cfg = _feature_cfg(feature_id)
    cur.execute(f"SELECT type_code FROM {cfg['gloss_table']} ORDER BY sort_order, type_code")
    return [row[0] for row in cur.fetchall()]


def _list_polygon_names(cur):
    cur.execute("SELECT polygon_name FROM tab_polygons ORDER BY polygon_name")
    return [row[0] for row in cur.fetchall()]


def _suggested_next_id(cur, feature_id: str):
    cfg = _feature_cfg(feature_id)
    cur.execute(f"SELECT COALESCE(MAX({cfg['id_col']}), 0) + 1 FROM {cfg['table']}")
    row = cur.fetchone()
    return row[0] if row else 1


def _load_record(cur, feature_id: str, record_id: int):
    if feature_id == "finds":
        cur.execute(
            """
            SELECT
                id_find,
                ref_find_type,
                description,
                count,
                ref_sj,
                ref_geopt,
                ref_polygon,
                box
            FROM tab_finds
            WHERE id_find = %s
            """,
            (record_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "feature_id": feature_id,
            "type_code": row[1],
            "description": row[2],
            "count": row[3],
            "ref_sj": row[4],
            "ref_geopt": row[5],
            "ref_polygon": row[6],
            "box": row[7],
        }

    cur.execute(
        """
        SELECT
            id_sample,
            ref_sample_type,
            description,
            ref_sj,
            ref_geopt,
            ref_polygon
        FROM tab_samples
        WHERE id_sample = %s
        """,
        (record_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "feature_id": feature_id,
        "type_code": row[1],
        "description": row[2],
        "ref_sj": row[3],
        "ref_geopt": row[4],
        "ref_polygon": row[5],
        "count": None,
        "box": None,
    }


def _media_preview_map(cur, terrain_db: str, feature_id: str):
    previews = {}
    cfg = _feature_cfg(feature_id)
    id_col = cfg["id_col"]
    for kind, media_cfg in cfg["media"].items():
        cur.execute(
            f"""
            SELECT
                l.{media_cfg['link_ref_col']},
                m.{media_cfg['id_col']},
                m.mime_type
            FROM {media_cfg['link_table']} l
            JOIN {media_cfg['table']} m
              ON m.{media_cfg['id_col']} = l.{media_cfg['link_media_col']}
            ORDER BY l.{media_cfg['link_ref_col']}, m.{media_cfg['id_col']}
            """
        )
        for record_id, media_id, mime_type in cur.fetchall():
            items = previews.setdefault(record_id, [])
            if len(items) >= 4:
                continue
            items.append(
                {
                    "kind": kind,
                    "id": media_id,
                    "type": None,
                    "mime_type": mime_type,
                    "content_path": _feature_media_content_path(terrain_db, feature_id, kind, media_id),
                }
            )
    return previews


def _list_media(cur, terrain_db: str, feature_id: str, record_id: int):
    cfg = _feature_cfg(feature_id)
    output = {"photos": [], "sketches": []}
    for kind, media_cfg in cfg["media"].items():
        cur.execute(
            f"""
            SELECT
                m.{media_cfg['id_col']},
                m.{media_cfg['type_col']},
                m.notes,
                m.mime_type
            FROM {media_cfg['link_table']} l
            JOIN {media_cfg['table']} m
              ON m.{media_cfg['id_col']} = l.{media_cfg['link_media_col']}
            WHERE l.{media_cfg['link_ref_col']} = %s
            ORDER BY m.{media_cfg['id_col']}
            """,
            (record_id,),
        )
        for media_id, media_type, notes, mime_type in cur.fetchall():
            output[kind].append(
                {
                    "kind": kind,
                    "id": media_id,
                    "type": media_type,
                    "notes": notes,
                    "mime_type": mime_type,
                    "content_path": _feature_media_content_path(terrain_db, feature_id, kind, media_id),
                }
            )
    return output


def _validate_media_type(feature_id: str, kind: str, value: str):
    cfg = _feature_cfg(feature_id)
    media_cfg = cfg["media"].get(kind)
    if media_cfg is None:
        raise ValueError("Unsupported media kind.")
    if value not in media_cfg["allowed_types"]:
        raise ValueError("Invalid media type.")
    return media_cfg, value


def _save_record(cur, feature_id: str, payload: dict, existing_id: int | None = None):
    cfg = _feature_cfg(feature_id)
    record_id = _nullable_int(str(payload.get("id") if payload.get("id") is not None else ""))
    if record_id is None:
        raise ValueError("Record ID is required.")
    if existing_id is not None and record_id != existing_id:
        raise ValueError("Record ID cannot be changed in edit mode.")

    type_code = (payload.get("type_code") or "").strip().lower()
    description = _nullable_text(payload.get("description"))
    ref_sj = _nullable_int(str(payload.get("ref_sj") if payload.get("ref_sj") is not None else ""))
    ref_geopt = _nullable_int(str(payload.get("ref_geopt") if payload.get("ref_geopt") is not None else ""))
    ref_polygon = _nullable_text(payload.get("ref_polygon"))

    if not type_code:
        raise ValueError("Type is required.")
    if ref_sj is None:
        raise ValueError("Linked SU is required.")

    cur.execute(f"SELECT 1 FROM {cfg['gloss_table']} WHERE type_code = %s", (type_code,))
    if cur.fetchone() is None:
        raise ValueError("Selected type does not exist.")

    if existing_id is None:
        cur.execute(f"SELECT 1 FROM {cfg['table']} WHERE {cfg['id_col']} = %s", (record_id,))
        if cur.fetchone() is not None:
            raise ValueError("Record ID already exists.")

    if feature_id == "finds":
        count = _nullable_int(str(payload.get("count") if payload.get("count") is not None else ""))
        box = _nullable_int(str(payload.get("box") if payload.get("box") is not None else ""))
        if count is not None and count <= 0:
            raise ValueError("Count must be greater than 0 when provided.")
        if box is not None and box <= 0:
            raise ValueError("Box must be greater than 0 when provided.")
        if existing_id is None:
            cur.execute(
                """
                INSERT INTO tab_finds (
                    id_find, ref_find_type, description, count, ref_sj, ref_geopt, ref_polygon, box
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (record_id, type_code, description, count, ref_sj, ref_geopt, ref_polygon, box),
            )
        else:
            cur.execute(
                """
                UPDATE tab_finds
                SET ref_find_type = %s,
                    description = %s,
                    count = %s,
                    ref_sj = %s,
                    ref_geopt = %s,
                    ref_polygon = %s,
                    box = %s
                WHERE id_find = %s
                """,
                (type_code, description, count, ref_sj, ref_geopt, ref_polygon, box, record_id),
            )
        return record_id

    if existing_id is None:
        cur.execute(
            """
            INSERT INTO tab_samples (
                id_sample, ref_sample_type, description, ref_sj, ref_geopt, ref_polygon
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (record_id, type_code, description, ref_sj, ref_geopt, ref_polygon),
        )
    else:
        cur.execute(
            """
            UPDATE tab_samples
            SET ref_sample_type = %s,
                description = %s,
                ref_sj = %s,
                ref_geopt = %s,
                ref_polygon = %s
            WHERE id_sample = %s
            """,
            (type_code, description, ref_sj, ref_geopt, ref_polygon, record_id),
        )
    return record_id


def _link_media(cur, feature_id: str, kind: str, record_id: int, media_id: str):
    media_cfg = _feature_cfg(feature_id)["media"][kind]
    cur.execute(
        f"""
        INSERT INTO {media_cfg['link_table']} ({media_cfg['link_ref_col']}, {media_cfg['link_media_col']})
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (record_id, media_id),
    )


@finds_samples_mobile_bp.get("/api/mobile/terrain/<terrain_db>/<feature_id>/meta")
@require_mobile_token
def get_feature_meta(terrain_db: str, feature_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        _feature_cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                return jsonify(
                    {
                        "types": _list_types(cur, feature_id),
                        "polygon_names": _list_polygon_names(cur),
                        "suggested_id": _suggested_next_id(cur, feature_id),
                    }
                )
    except Exception as e:
        logger.exception("Meta load failed for %s/%s: %s", terrain_db, feature_id, e)
        return _json_error("Internal server error.", 500)


@finds_samples_mobile_bp.post("/api/mobile/terrain/<terrain_db>/<feature_id>/types")
@require_mobile_token
def create_feature_type(terrain_db: str, feature_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        cfg = _feature_cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    payload = request.get_json(silent=True) or {}
    type_code = (payload.get("type_code") or "").strip().lower()
    if not type_code:
        return _json_error("Type code is required.", 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {cfg['gloss_table']} (type_code, sort_order)
                    VALUES (%s, COALESCE((SELECT MAX(sort_order) + 10 FROM {cfg['gloss_table']}), 10))
                    ON CONFLICT (type_code) DO NOTHING
                    """,
                    (type_code,),
                )
                types = _list_types(cur, feature_id)
        return jsonify({"types": types, "message": f'Type "{type_code}" was saved.'}), 201
    except Exception as e:
        logger.exception("Type create failed for %s/%s: %s", terrain_db, feature_id, e)
        return _json_error("Internal server error.", 500)


@finds_samples_mobile_bp.get("/api/mobile/terrain/<terrain_db>/<feature_id>")
@require_mobile_token
def list_feature_records(terrain_db: str, feature_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        cfg = _feature_cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                if feature_id == "finds":
                    cur.execute(
                        """
                        SELECT id_find, ref_find_type, description, count, ref_sj, ref_geopt, ref_polygon, box
                        FROM tab_finds
                        ORDER BY id_find
                        """
                    )
                else:
                    cur.execute(
                        """
                        SELECT id_sample, ref_sample_type, description, ref_sj, ref_geopt, ref_polygon
                        FROM tab_samples
                        ORDER BY id_sample
                        """
                    )
                rows = cur.fetchall()
                preview_map = _media_preview_map(cur, terrain_db, feature_id)

        records = []
        for row in rows:
            record_id = row[0]
            records.append(
                {
                    "id": record_id,
                    "feature_id": feature_id,
                    "type_code": row[1],
                    "description": row[2],
                    "count": row[3] if feature_id == "finds" else None,
                    "ref_sj": row[4] if feature_id == "finds" else row[3],
                    "ref_geopt": row[5] if feature_id == "finds" else row[4],
                    "ref_polygon": row[6] if feature_id == "finds" else row[5],
                    "box": row[7] if feature_id == "finds" else None,
                    "media_preview": preview_map.get(record_id, []),
                }
            )
        return jsonify({"records": records})
    except Exception as e:
        logger.exception("List failed for %s/%s: %s", terrain_db, feature_id, e)
        return _json_error("Internal server error.", 500)


@finds_samples_mobile_bp.post("/api/mobile/terrain/<terrain_db>/<feature_id>")
@require_mobile_token
def create_feature_record(terrain_db: str, feature_id: str):
    claims = g.mobile_claims
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    payload = request.get_json(silent=True) or {}

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                _feature_cfg(feature_id)
                if not _ensure_author_exists(cur, claims.get("email", "")):
                    return _json_error("Current mobile user is not available in project personalia.", 400)
                record_id = _save_record(cur, feature_id, payload)
                record = _load_record(cur, feature_id, record_id)
        label = "Find" if feature_id == "finds" else "Sample"
        return jsonify({"message": f'{label} "{record_id}" was saved.', "record": record}), 201
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Create failed for %s/%s: %s", terrain_db, feature_id, e)
        return _json_error("Internal server error.", 500)


@finds_samples_mobile_bp.get("/api/mobile/terrain/<terrain_db>/<feature_id>/<int:record_id>")
@require_mobile_token
def get_feature_record(terrain_db: str, feature_id: str, record_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        _feature_cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                record = _load_record(cur, feature_id, record_id)
                if not record:
                    return _json_error("Record not found.", 404)
        return jsonify({"record": record})
    except Exception as e:
        logger.exception("Detail failed for %s/%s/%s: %s", terrain_db, feature_id, record_id, e)
        return _json_error("Internal server error.", 500)


@finds_samples_mobile_bp.put("/api/mobile/terrain/<terrain_db>/<feature_id>/<int:record_id>")
@require_mobile_token
def update_feature_record(terrain_db: str, feature_id: str, record_id: int):
    claims = g.mobile_claims
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    payload = request.get_json(silent=True) or {}

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                _feature_cfg(feature_id)
                if not _ensure_author_exists(cur, claims.get("email", "")):
                    return _json_error("Current mobile user is not available in project personalia.", 400)
                if _load_record(cur, feature_id, record_id) is None:
                    return _json_error("Record not found.", 404)
                _save_record(cur, feature_id, payload, existing_id=record_id)
                record = _load_record(cur, feature_id, record_id)
        label = "Find" if feature_id == "finds" else "Sample"
        return jsonify({"message": f'{label} "{record_id}" was updated.', "record": record})
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Update failed for %s/%s/%s: %s", terrain_db, feature_id, record_id, e)
        return _json_error("Internal server error.", 500)


@finds_samples_mobile_bp.delete("/api/mobile/terrain/<terrain_db>/<feature_id>/<int:record_id>")
@require_mobile_token
def delete_feature_record(terrain_db: str, feature_id: str, record_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        cfg = _feature_cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if _load_record(cur, feature_id, record_id) is None:
                    return _json_error("Record not found.", 404)
                cur.execute(f"DELETE FROM {cfg['table']} WHERE {cfg['id_col']} = %s", (record_id,))
        label = "Find" if feature_id == "finds" else "Sample"
        return jsonify({"message": f'{label} "{record_id}" was deleted.'})
    except Exception as e:
        logger.exception("Delete failed for %s/%s/%s: %s", terrain_db, feature_id, record_id, e)
        return _json_error("Internal server error.", 500)


@finds_samples_mobile_bp.get("/api/mobile/terrain/<terrain_db>/<feature_id>/<int:record_id>/media")
@require_mobile_token
def list_feature_media(terrain_db: str, feature_id: str, record_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        _feature_cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                if _load_record(cur, feature_id, record_id) is None:
                    return _json_error("Record not found.", 404)
                media = _list_media(cur, terrain_db, feature_id, record_id)
        return jsonify(
            {
                "record_id": record_id,
                "photos": media["photos"],
                "sketches": media["sketches"],
            }
        )
    except Exception as e:
        logger.exception("Media list failed for %s/%s/%s: %s", terrain_db, feature_id, record_id, e)
        return _json_error("Internal server error.", 500)


@finds_samples_mobile_bp.post("/api/mobile/terrain/<terrain_db>/<feature_id>/<int:record_id>/media")
@require_mobile_token
def upload_feature_media(terrain_db: str, feature_id: str, record_id: int):
    claims = g.mobile_claims
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    kind = (request.form.get("kind") or "").strip()
    media_type = (request.form.get("typ") or "").strip()
    notes = _nullable_text(request.form.get("notes"))
    file_storage = request.files.get("file")

    try:
        _media_cfg, normalized_type = _validate_media_type(feature_id, kind, media_type)
        if file_storage is None or not file_storage.filename:
            raise ValueError("Missing uploaded file.")
    except ValueError as e:
        return _json_error(str(e), 400)

    final_path = None
    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if _load_record(cur, feature_id, record_id) is None:
                    return _json_error("Record not found.", 404)
                if not _ensure_author_exists(cur, claims.get("email", "")):
                    return _json_error("Current mobile user is not available in project personalia.", 400)

                media_id, mime_type, final_path = _store_media_upload(
                    cur,
                    terrain_db,
                    kind,
                    file_storage,
                    normalized_type,
                    claims.get("email", ""),
                    notes,
                )
                _link_media(cur, feature_id, kind, record_id, media_id)

        label = "Find" if feature_id == "finds" else "Sample"
        return jsonify(
            {
                "message": f'{kind[:-1].capitalize()} was attached to {label.lower()} "{record_id}".',
                "media": {
                    "kind": kind,
                    "id": media_id,
                    "type": normalized_type,
                    "notes": notes,
                    "mime_type": mime_type,
                    "content_path": _feature_media_content_path(terrain_db, feature_id, kind, media_id),
                },
            }
        ), 201
    except Exception as e:
        if final_path and os.path.exists(final_path):
            os.remove(final_path)
        if isinstance(e, ValueError):
            return _json_error(str(e), 400)
        logger.exception("Media upload failed for %s/%s/%s: %s", terrain_db, feature_id, record_id, e)
        return _json_error("Internal server error.", 500)


@finds_samples_mobile_bp.get("/api/mobile/terrain/<terrain_db>/<feature_id>_media/<kind>/<media_id>")
@require_mobile_token
def get_feature_media_content(terrain_db: str, feature_id: str, kind: str, media_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        cfg = _feature_cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)
    if kind not in cfg["media"]:
        return _json_error("Unsupported media kind.", 400)
    try:
        path = _media_file_path(terrain_db, kind, media_id)
        if not os.path.exists(path):
            return _json_error("Media file not found.", 404)
        return send_file(path, conditional=True)
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Media content failed for %s/%s/%s/%s: %s", terrain_db, feature_id, kind, media_id, e)
        return _json_error("Internal server error.", 500)
