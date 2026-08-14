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

sections_bp = Blueprint("sections", __name__)
logger = logging.getLogger("mobile_api.sections")

SECTION_TYPES = {"standard", "cumulative", "synthetic", "other"}

SECTION_MEDIA_KIND_CONFIG = {
    "photos": {
        "table": "tab_photos",
        "id_col": "id_photo",
        "type_col": "photo_typ",
        "link_table": "tabaid_section_photos",
        "link_media_col": "ref_photo",
        "allowed_types": PHOTO_TYP_CHOICES,
        "media_dir": "photos",
    },
    "sketches": {
        "table": "tab_sketches",
        "id_col": "id_sketch",
        "type_col": "sketch_typ",
        "link_table": "tabaid_section_sketches",
        "link_media_col": "ref_sketch",
        "allowed_types": SKETCH_TYP_CHOICES,
        "media_dir": "sketches",
    },
    "drawings": {
        "table": "tab_drawings",
        "id_col": "id_drawing",
        "type_col": None,
        "link_table": "tabaid_section_drawings",
        "link_media_col": "ref_drawing",
        "allowed_types": None,
        "media_dir": "drawings",
    },
    "photograms": {
        "table": "tab_photograms",
        "id_col": "id_photogram",
        "type_col": "photogram_typ",
        "link_table": "tabaid_section_photograms",
        "link_media_col": "ref_photogram",
        "allowed_types": PHOTOGRAM_TYP_CHOICES,
        "media_dir": "photograms",
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


def _parse_ranges(raw_ranges):
    if not isinstance(raw_ranges, list):
        raise ValueError("Point ranges must be a list.")

    parsed = []
    for item in raw_ranges:
        if not isinstance(item, dict):
            raise ValueError("Point ranges contain invalid item.")
        start = item.get("from")
        end = item.get("to")
        if start is None or end is None:
            raise ValueError("Each point range must contain both FROM and TO.")
        start_i = int(start)
        end_i = int(end)
        if start_i > end_i:
            raise ValueError(f"Invalid point range {start_i}-{end_i}.")
        parsed.append((start_i, end_i))
    return parsed


def _parse_su_ids(raw_su_ids):
    if raw_su_ids is None:
        return []
    if not isinstance(raw_su_ids, list):
        raise ValueError("SU IDs must be a list.")
    output = []
    for value in raw_su_ids:
        output.append(int(value))
    return output


def _section_media_content_path(terrain_db: str, kind: str, media_id: str) -> str:
    return f"/api/mobile/terrain/{terrain_db}/section_media/{kind}/{quote(media_id)}"


def _validate_media_type(kind: str, value: str):
    cfg = SECTION_MEDIA_KIND_CONFIG.get(kind)
    if cfg is None:
        raise ValueError("Unsupported media kind.")
    if cfg["allowed_types"] is None:
        return cfg, None
    if value not in cfg["allowed_types"]:
        raise ValueError("Invalid media type.")
    return cfg, value


def _load_section_ranges(cur, section_id: int):
    cur.execute(
        """
        SELECT pts_from, pts_to
        FROM tab_section_geopts_binding
        WHERE ref_section = %s
        ORDER BY pts_from, pts_to
        """,
        (section_id,),
    )
    return [{"from": row[0], "to": row[1]} for row in cur.fetchall()]


def _load_section_su_ids(cur, section_id: int):
    cur.execute(
        """
        SELECT ref_sj
        FROM tabaid_sj_section
        WHERE ref_section = %s
        ORDER BY ref_sj
        """,
        (section_id,),
    )
    return [row[0] for row in cur.fetchall()]


def _load_section_detail(cur, section_id: int):
    cur.execute(
        """
        SELECT id_section, section_type::text, description
        FROM tab_section
        WHERE id_section = %s
        """,
        (section_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "section_type": row[1],
        "description": row[2],
        "ranges": _load_section_ranges(cur, row[0]),
        "su_ids": _load_section_su_ids(cur, row[0]),
    }


def _section_media_preview_map(cur, terrain_db: str):
    previews = {}
    for kind, cfg in SECTION_MEDIA_KIND_CONFIG.items():
        cur.execute(
            f"""
            SELECT
                l.ref_section,
                m.{cfg['id_col']},
                m.mime_type
            FROM {cfg['link_table']} l
            JOIN {cfg['table']} m
              ON m.{cfg['id_col']} = l.{cfg['link_media_col']}
            ORDER BY l.ref_section, m.{cfg['id_col']}
            """
        )
        for section_id, media_id, mime_type in cur.fetchall():
            items = previews.setdefault(section_id, [])
            if len(items) >= 4:
                continue
            items.append(
                {
                    "kind": kind,
                    "id": media_id,
                    "type": None,
                    "mime_type": mime_type,
                    "content_path": _section_media_content_path(terrain_db, kind, media_id),
                }
            )
    return previews


def _list_section_media(cur, terrain_db: str, section_id: int):
    output = {
        "photos": [],
        "sketches": [],
        "drawings": [],
        "photograms": [],
    }
    for kind, cfg in SECTION_MEDIA_KIND_CONFIG.items():
        type_select = f"m.{cfg['type_col']}" if cfg["type_col"] else "NULL"
        cur.execute(
            f"""
            SELECT
                m.{cfg['id_col']},
                {type_select},
                m.notes,
                m.mime_type
            FROM {cfg['link_table']} l
            JOIN {cfg['table']} m
              ON m.{cfg['id_col']} = l.{cfg['link_media_col']}
            WHERE l.ref_section = %s
            ORDER BY m.{cfg['id_col']}
            """,
            (section_id,),
        )
        for media_id, media_type, notes, mime_type in cur.fetchall():
            output[kind].append(
                {
                    "kind": kind,
                    "id": media_id,
                    "type": media_type,
                    "notes": notes,
                    "mime_type": mime_type,
                    "content_path": _section_media_content_path(terrain_db, kind, media_id),
                }
            )
    return output


def _link_media_to_section(cur, kind: str, section_id: int, media_id: str):
    cfg = SECTION_MEDIA_KIND_CONFIG[kind]
    cur.execute(
        f"""
        INSERT INTO {cfg['link_table']} (ref_section, {cfg['link_media_col']})
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (section_id, media_id),
    )


def _save_section(cur, payload: dict, existing_id: int | None = None):
    section_id = _nullable_int(str(payload.get("id") if payload.get("id") is not None else ""))
    if section_id is None:
        raise ValueError("Section ID is required.")
    if existing_id is not None and section_id != existing_id:
        raise ValueError("Section ID cannot be changed in edit mode.")

    section_type = (payload.get("section_type") or "").strip()
    if section_type not in SECTION_TYPES:
        raise ValueError("Invalid section type.")

    ranges = _parse_ranges(payload.get("ranges") or [])
    if not ranges:
        raise ValueError("At least one point range is required.")

    su_ids = _parse_su_ids(payload.get("su_ids") or [])
    description = _nullable_text(payload.get("description"))

    if existing_id is None:
        cur.execute("SELECT 1 FROM tab_section WHERE id_section = %s", (section_id,))
        if cur.fetchone() is not None:
            raise ValueError("Section ID already exists.")
        cur.execute(
            """
            INSERT INTO tab_section (id_section, section_type, description)
            VALUES (%s, %s, %s)
            """,
            (section_id, section_type, description),
        )
    else:
        cur.execute("SELECT 1 FROM tab_section WHERE id_section = %s", (section_id,))
        if cur.fetchone() is None:
            raise ValueError("Section not found.")
        cur.execute(
            """
            UPDATE tab_section
            SET section_type = %s,
                description = %s
            WHERE id_section = %s
            """,
            (section_type, description, section_id),
        )
        cur.execute("DELETE FROM tab_section_geopts_binding WHERE ref_section = %s", (section_id,))
        cur.execute("DELETE FROM tabaid_sj_section WHERE ref_section = %s", (section_id,))

    for start_i, end_i in ranges:
        cur.execute(
            """
            INSERT INTO tab_section_geopts_binding (ref_section, pts_from, pts_to)
            VALUES (%s, %s, %s)
            ON CONFLICT (ref_section, pts_from, pts_to) DO NOTHING
            """,
            (section_id, start_i, end_i),
        )

    for su_id in su_ids:
        cur.execute(
            """
            INSERT INTO tabaid_sj_section (ref_sj, ref_section)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (su_id, section_id),
        )

    return section_id


@sections_bp.get("/api/mobile/terrain/<terrain_db>/sections")
@require_mobile_token
def list_sections(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id_section, section_type::text, description
                    FROM tab_section
                    ORDER BY id_section
                    """
                )
                rows = cur.fetchall()
                preview_map = _section_media_preview_map(cur, terrain_db)

                records = []
                for row in rows:
                    section_id = row[0]
                    records.append(
                        {
                            "id": section_id,
                            "section_type": row[1],
                            "description": row[2],
                            "ranges": _load_section_ranges(cur, section_id),
                            "su_ids": _load_section_su_ids(cur, section_id),
                            "media_preview": preview_map.get(section_id, []),
                        }
                    )

        return jsonify({"records": records})
    except Exception as e:
        logger.exception("Section list failed for %s: %s", terrain_db, e)
        return _json_error("Internal server error.", 500)


@sections_bp.post("/api/mobile/terrain/<terrain_db>/sections")
@require_mobile_token
def create_section(terrain_db: str):
    claims = g.mobile_claims
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    payload = request.get_json(silent=True) or {}
    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if not _ensure_author_exists(cur, claims.get("email", "")):
                    return _json_error("Current mobile user is not available in project personalia.", 400)
                section_id = _save_section(cur, payload)
                section = _load_section_detail(cur, section_id)
        return jsonify({"message": f'Section "{section_id}" was saved.', "section": section}), 201
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Section create failed for %s: %s", terrain_db, e)
        return _json_error("Internal server error.", 500)


@sections_bp.get("/api/mobile/terrain/<terrain_db>/sections/<int:section_id>")
@require_mobile_token
def get_section(terrain_db: str, section_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                section = _load_section_detail(cur, section_id)
                if not section:
                    return _json_error("Section not found.", 404)
        return jsonify({"section": section})
    except Exception as e:
        logger.exception("Section detail failed for %s/%s: %s", terrain_db, section_id, e)
        return _json_error("Internal server error.", 500)


@sections_bp.put("/api/mobile/terrain/<terrain_db>/sections/<int:section_id>")
@require_mobile_token
def update_section(terrain_db: str, section_id: int):
    claims = g.mobile_claims
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    payload = request.get_json(silent=True) or {}
    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if not _ensure_author_exists(cur, claims.get("email", "")):
                    return _json_error("Current mobile user is not available in project personalia.", 400)
                existing = _load_section_detail(cur, section_id)
                if not existing:
                    return _json_error("Section not found.", 404)
                _save_section(cur, payload, existing_id=section_id)
                section = _load_section_detail(cur, section_id)
        return jsonify({"message": f'Section "{section_id}" was updated.', "section": section})
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Section update failed for %s/%s: %s", terrain_db, section_id, e)
        return _json_error("Internal server error.", 500)


@sections_bp.delete("/api/mobile/terrain/<terrain_db>/sections/<int:section_id>")
@require_mobile_token
def delete_section(terrain_db: str, section_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if _load_section_detail(cur, section_id) is None:
                    return _json_error("Section not found.", 404)
                cur.execute("DELETE FROM tab_section WHERE id_section = %s", (section_id,))
        return jsonify({"message": f'Section "{section_id}" was deleted.'})
    except Exception as e:
        logger.exception("Section delete failed for %s/%s: %s", terrain_db, section_id, e)
        return _json_error("Internal server error.", 500)


@sections_bp.get("/api/mobile/terrain/<terrain_db>/sections/<int:section_id>/media")
@require_mobile_token
def list_section_media(terrain_db: str, section_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                if _load_section_detail(cur, section_id) is None:
                    return _json_error("Section not found.", 404)
                media = _list_section_media(cur, terrain_db, section_id)
        return jsonify(
            {
                "section_id": section_id,
                "photos": media["photos"],
                "sketches": media["sketches"],
                "drawings": media["drawings"],
                "photograms": media["photograms"],
            }
        )
    except Exception as e:
        logger.exception("Section media list failed for %s/%s: %s", terrain_db, section_id, e)
        return _json_error("Internal server error.", 500)


@sections_bp.post("/api/mobile/terrain/<terrain_db>/sections/<int:section_id>/media")
@require_mobile_token
def upload_section_media(terrain_db: str, section_id: int):
    claims = g.mobile_claims
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    kind = (request.form.get("kind") or "").strip()
    media_type = (request.form.get("typ") or "").strip()
    notes = _nullable_text(request.form.get("notes"))
    file_storage = request.files.get("file")

    try:
        _cfg, normalized_type = _validate_media_type(kind, media_type)
        if file_storage is None or not file_storage.filename:
            raise ValueError("Missing uploaded file.")
    except ValueError as e:
        return _json_error(str(e), 400)

    final_path = None
    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if _load_section_detail(cur, section_id) is None:
                    return _json_error("Section not found.", 404)
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
                _link_media_to_section(cur, kind, section_id, media_id)

        return jsonify(
            {
                "message": f'{kind[:-1].capitalize()} was attached to section "{section_id}".',
                "media": {
                    "kind": kind,
                    "id": media_id,
                    "type": normalized_type,
                    "notes": notes,
                    "mime_type": mime_type,
                    "content_path": _section_media_content_path(terrain_db, kind, media_id),
                },
            }
        ), 201
    except Exception as e:
        if final_path and os.path.exists(final_path):
            os.remove(final_path)
        if isinstance(e, ValueError):
            return _json_error(str(e), 400)
        logger.exception("Section media upload failed for %s/%s: %s", terrain_db, section_id, e)
        return _json_error("Internal server error.", 500)


@sections_bp.get("/api/mobile/terrain/<terrain_db>/section_media/<kind>/<media_id>")
@require_mobile_token
def get_section_media_content(terrain_db: str, kind: str, media_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    if kind not in SECTION_MEDIA_KIND_CONFIG:
        return _json_error("Unsupported media kind.", 400)
    try:
        path = _media_file_path(terrain_db, kind, media_id)
        if not os.path.exists(path):
            return _json_error("Media file not found.", 404)
        return send_file(path, conditional=True)
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Section media content failed for %s/%s/%s: %s", terrain_db, kind, media_id, e)
        return _json_error("Internal server error.", 500)
