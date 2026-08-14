import logging
import os
import tempfile
from datetime import date
from urllib.parse import quote
from uuid import uuid4

from flask import Blueprint, g, jsonify, request, send_file

from app.database import terrain_connection, terrain_transaction
from app.auth_tokens import require_mobile_token
from app.media import (
    _db_prefix_from_name,
    _detect_mime,
    _media_file_path,
    _sanitize_filename,
    _sha256_file,
)
from app.responses import _json_error
from app.validators import _validate_terrain_db

documentation_bp = Blueprint("documentation", __name__)
logger = logging.getLogger("mobile_api.documentation")

DOC_CONFIG = {
    "photos": {
        "table": "tab_photos",
        "id_col": "id_photo",
        "type_col": "photo_typ",
        "notes_col": "notes",
        "date_col": "datum",
        "author_col": "author",
        "allowed_types": {"vertical", "horizontal", "skew", "general", "detail"},
        "relations": {
            "su_ids": ("tabaid_photo_sj", "ref_photo", "ref_sj", int),
            "polygon_names": ("tabaid_polygon_photos", "ref_photo", "ref_polygon", str),
            "section_ids": ("tabaid_section_photos", "ref_photo", "ref_section", int),
            "find_ids": ("tabaid_finds_photos", "ref_photo", "ref_find", int),
            "sample_ids": ("tabaid_samples_photos", "ref_photo", "ref_sample", int),
        },
    },
    "sketches": {
        "table": "tab_sketches",
        "id_col": "id_sketch",
        "type_col": "sketch_typ",
        "notes_col": "notes",
        "date_col": "datum",
        "author_col": "author",
        "allowed_types": {"sketch", "photosketch", "general", "other"},
        "relations": {
            "su_ids": ("tabaid_sj_sketch", "ref_sketch", "ref_sj", int),
            "polygon_names": ("tabaid_polygon_sketches", "ref_sketch", "ref_polygon", str),
            "section_ids": ("tabaid_section_sketches", "ref_sketch", "ref_section", int),
            "find_ids": ("tabaid_finds_sketches", "ref_sketch", "ref_find", int),
            "sample_ids": ("tabaid_samples_sketches", "ref_sketch", "ref_sample", int),
        },
    },
    "drawings": {
        "table": "tab_drawings",
        "id_col": "id_drawing",
        "notes_col": "notes",
        "date_col": "datum",
        "author_col": "author",
        "allowed_types": set(),
        "relations": {
            "su_ids": ("tabaid_sj_drawings", "ref_drawing", "ref_sj", int),
            "section_ids": ("tabaid_section_drawings", "ref_drawing", "ref_section", int),
        },
    },
    "photograms": {
        "table": "tab_photograms",
        "id_col": "id_photogram",
        "type_col": "photogram_typ",
        "notes_col": "notes",
        "date_col": None,
        "author_col": None,
        "allowed_types": {"stereo", "resection", "synthetic", "other"},
        "relations": {
            "su_ids": ("tabaid_photogram_sj", "ref_photogram", "ref_sj", int),
            "polygon_names": ("tabaid_polygon_photograms", "ref_photogram", "ref_polygon", str),
            "section_ids": ("tabaid_section_photograms", "ref_photogram", "ref_section", int),
        },
    },
}


def _cfg(feature_id: str):
    cfg = DOC_CONFIG.get(feature_id)
    if not cfg:
        raise ValueError("Unsupported documentation feature.")
    return cfg


def _nullable_text(value):
    text = (value or "").strip()
    return text or None


def _nullable_date(value):
    text = _nullable_text(value)
    if text is None:
        return None
    return date.fromisoformat(text)


def _uses_author_date(feature_id: str) -> bool:
    return feature_id in {"photos", "sketches", "drawings"}


def _uses_type(feature_id: str) -> bool:
    return feature_id != "drawings"


def _doc_content_path(terrain_db: str, feature_id: str, doc_id: str) -> str:
    return f"/api/mobile/terrain/{terrain_db}/documentation_media/{feature_id}/{quote(doc_id)}"


def _parse_relation_values(expected_type, raw_values):
    if raw_values is None:
        return []
    if not isinstance(raw_values, list):
        raise ValueError("Relation values must be arrays.")
    values = []
    for item in raw_values:
        if expected_type is int:
            values.append(int(item))
        else:
            val = str(item).strip()
            if val:
                values.append(val)
    return sorted(set(values))


def _doc_exists(cur, feature_id: str, doc_id: str) -> bool:
    cfg = _cfg(feature_id)
    cur.execute(
        f"SELECT 1 FROM {cfg['table']} WHERE {cfg['id_col']} = %s LIMIT 1",
        (doc_id,),
    )
    return cur.fetchone() is not None


def _make_doc_id(cur, terrain_db: str, feature_id: str, original_name: str) -> str:
    cfg = _cfg(feature_id)
    prefix = _db_prefix_from_name(terrain_db)
    safe_base, ext = _sanitize_filename(original_name)
    candidate = f"{prefix}{safe_base}.{ext}"
    cur.execute(
        f"SELECT 1 FROM {cfg['table']} WHERE {cfg['id_col']} = %s LIMIT 1",
        (candidate,),
    )
    if cur.fetchone() is None:
        return candidate
    candidate = f"{prefix}{safe_base}_{int(date.today().strftime('%Y%m%d'))}.{ext}"
    cur.execute(
        f"SELECT 1 FROM {cfg['table']} WHERE {cfg['id_col']} = %s LIMIT 1",
        (candidate,),
    )
    if cur.fetchone() is None:
        return candidate
    return f"{prefix}{safe_base}_{uuid4().hex[:8]}.{ext}"


def _list_docs(cur, terrain_db: str, feature_id: str):
    cfg = _cfg(feature_id)
    if feature_id == "photograms":
        cur.execute(
            """
            SELECT
                id_photogram,
                photogram_typ,
                notes,
                mime_type,
                file_size,
                ref_sketch,
                ref_photo_from,
                ref_photo_to
            FROM tab_photograms
            ORDER BY id_photogram DESC
            """
        )
    else:
        if feature_id == "drawings":
            cur.execute(
                """
                SELECT
                    id_drawing,
                    author,
                    datum,
                    notes,
                    mime_type,
                    file_size
                FROM tab_drawings
                ORDER BY id_drawing DESC
                """
            )
        else:
            cur.execute(
                f"""
                SELECT
                    {cfg['id_col']},
                    {cfg['type_col']},
                    {cfg['author_col']},
                    {cfg['date_col']},
                    {cfg['notes_col']},
                    mime_type,
                    file_size
                FROM {cfg['table']}
                ORDER BY {cfg['id_col']} DESC
                """
            )
    items = []
    for row in cur.fetchall():
        if feature_id == "photograms":
            item = {
                "id": row[0],
                "type": row[1],
                "notes": row[2],
                "mime_type": row[3] or "application/octet-stream",
                "file_size": row[4] or 0,
                "content_path": _doc_content_path(terrain_db, feature_id, row[0]),
                "ref_sketch": row[5],
                "ref_photo_from": row[6],
                "ref_photo_to": row[7],
            }
        elif feature_id == "drawings":
            item = {
                "id": row[0],
                "author": row[1],
                "datum": row[2].isoformat() if row[2] else None,
                "notes": row[3],
                "mime_type": row[4] or "application/octet-stream",
                "file_size": row[5] or 0,
                "content_path": _doc_content_path(terrain_db, feature_id, row[0]),
            }
        else:
            item = {
                "id": row[0],
                "type": row[1],
                "author": row[2],
                "datum": row[3].isoformat() if row[3] else None,
                "notes": row[4],
                "mime_type": row[5] or "application/octet-stream",
                "file_size": row[6] or 0,
                "content_path": _doc_content_path(terrain_db, feature_id, row[0]),
            }
        items.append(item)
    return items


def _load_doc(cur, terrain_db: str, feature_id: str, doc_id: str):
    cfg = _cfg(feature_id)
    if feature_id == "photograms":
        cur.execute(
            """
            SELECT
                id_photogram,
                photogram_typ,
                notes,
                mime_type,
                file_size,
                ref_sketch,
                ref_photo_from,
                ref_photo_to
            FROM tab_photograms
            WHERE id_photogram = %s
            """,
            (doc_id,),
        )
    else:
        if feature_id == "drawings":
            cur.execute(
                """
                SELECT
                    id_drawing,
                    author,
                    datum,
                    notes,
                    mime_type,
                    file_size
                FROM tab_drawings
                WHERE id_drawing = %s
                """,
                (doc_id,),
            )
        else:
            cur.execute(
                f"""
                SELECT
                    {cfg['id_col']},
                    {cfg['type_col']},
                    {cfg['author_col']},
                    {cfg['date_col']},
                    {cfg['notes_col']},
                    mime_type,
                    file_size
                FROM {cfg['table']}
                WHERE {cfg['id_col']} = %s
                """,
                (doc_id,),
            )
    row = cur.fetchone()
    if not row:
        return None
    if feature_id == "photograms":
        return {
            "id": row[0],
            "type": row[1],
            "notes": row[2],
            "mime_type": row[3] or "application/octet-stream",
            "file_size": row[4] or 0,
            "content_path": _doc_content_path(terrain_db, feature_id, row[0]),
            "relations": _load_relations(cur, feature_id, row[0]),
            "ref_sketch": row[5],
            "ref_photo_from": row[6],
            "ref_photo_to": row[7],
        }
    if feature_id == "drawings":
        return {
            "id": row[0],
            "author": row[1],
            "datum": row[2].isoformat() if row[2] else None,
            "notes": row[3],
            "mime_type": row[4] or "application/octet-stream",
            "file_size": row[5] or 0,
            "content_path": _doc_content_path(terrain_db, feature_id, row[0]),
            "relations": _load_relations(cur, feature_id, row[0]),
        }
    return {
        "id": row[0],
        "type": row[1],
        "author": row[2],
        "datum": row[3].isoformat() if row[3] else None,
        "notes": row[4],
        "mime_type": row[5] or "application/octet-stream",
        "file_size": row[6] or 0,
        "content_path": _doc_content_path(terrain_db, feature_id, row[0]),
        "relations": _load_relations(cur, feature_id, row[0]),
    }


def _load_relations(cur, feature_id: str, doc_id: str):
    cfg = _cfg(feature_id)
    data = {}
    for payload_key, rel_cfg in cfg["relations"].items():
        table, doc_col, target_col, _target_type = rel_cfg
        cur.execute(
            f"""
            SELECT {target_col}
            FROM {table}
            WHERE {doc_col} = %s
            ORDER BY {target_col}
            """,
            (doc_id,),
        )
        data[payload_key] = [row[0] for row in cur.fetchall()]
    return data


def _set_relations(cur, feature_id: str, doc_id: str, payload: dict):
    cfg = _cfg(feature_id)
    for payload_key, rel_cfg in cfg["relations"].items():
        table, doc_col, target_col, target_type = rel_cfg
        values = _parse_relation_values(target_type, payload.get(payload_key))
        cur.execute(f"DELETE FROM {table} WHERE {doc_col} = %s", (doc_id,))
        for value in values:
            cur.execute(
                f"INSERT INTO {table} ({doc_col}, {target_col}) VALUES (%s, %s)",
                (doc_id, value),
            )


@documentation_bp.get("/api/mobile/terrain/<terrain_db>/documentation/<feature_id>")
@require_mobile_token
def list_documentation(terrain_db: str, feature_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        cfg = _cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                items = _list_docs(cur, terrain_db, feature_id)
        return jsonify(
            {
                "feature_id": feature_id,
                "allowed_types": sorted(cfg["allowed_types"]),
                "records": items,
            }
        )
    except Exception as e:
        logger.exception("Documentation list failed for %s/%s: %s", terrain_db, feature_id, e)
        return _json_error("Internal server error.", 500)


@documentation_bp.post("/api/mobile/terrain/<terrain_db>/documentation/<feature_id>")
@require_mobile_token
def create_documentation(terrain_db: str, feature_id: str):
    claims = g.mobile_claims
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        cfg = _cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    media_type = (request.form.get("typ") or "").strip()
    notes = _nullable_text(request.form.get("notes"))
    ref_sketch = _nullable_text(request.form.get("ref_sketch"))
    ref_photo_from = _nullable_text(request.form.get("ref_photo_from"))
    ref_photo_to = _nullable_text(request.form.get("ref_photo_to"))
    file_storage = request.files.get("file")

    if not file_storage or not file_storage.filename:
        return _json_error("File is missing.", 400)
    if _uses_type(feature_id) and media_type not in cfg["allowed_types"]:
        return _json_error("Invalid documentation type.", 400)

    tmp_path = None
    try:
        author_email = _nullable_text(request.form.get("author")) or ((claims or {}).get("email") if _uses_author_date(feature_id) else None)
        doc_date = _nullable_date(request.form.get("datum"))
        if _uses_author_date(feature_id) and not author_email:
            return _json_error("Author is missing.", 400)
        if _uses_author_date(feature_id) and doc_date is None:
            doc_date = date.today()

        with tempfile.NamedTemporaryFile(delete=False) as tmp_handle:
            file_storage.save(tmp_handle)
            tmp_path = tmp_handle.name

        mime_type = _detect_mime(tmp_path, file_storage.filename)
        file_size = os.path.getsize(tmp_path)
        checksum = _sha256_file(tmp_path)

        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                doc_id = _make_doc_id(cur, terrain_db, feature_id, file_storage.filename)
                if feature_id == "photograms":
                    cur.execute(
                        """
                        INSERT INTO tab_photograms
                            (id_photogram, photogram_typ, notes, ref_sketch, ref_photo_from, ref_photo_to, mime_type, file_size, checksum_sha256)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            doc_id,
                            media_type,
                            notes,
                            ref_sketch,
                            ref_photo_from,
                            ref_photo_to,
                            mime_type,
                            file_size,
                            checksum,
                        ),
                    )
                elif feature_id == "drawings":
                    cur.execute(
                        """
                        INSERT INTO tab_drawings
                            (id_drawing, author, datum, notes, mime_type, file_size, checksum_sha256)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            doc_id,
                            author_email,
                            doc_date or date.today(),
                            notes,
                            mime_type,
                            file_size,
                            checksum,
                        ),
                    )
                else:
                    cur.execute(
                        f"""
                        INSERT INTO {cfg['table']}
                            ({cfg['id_col']}, {cfg['type_col']}, {cfg['author_col']}, {cfg['date_col']}, {cfg['notes_col']}, mime_type, file_size, checksum_sha256)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            doc_id,
                            media_type,
                            author_email,
                            doc_date or date.today(),
                            notes,
                            mime_type,
                            file_size,
                            checksum,
                        ),
                    )

                final_path = _media_file_path(terrain_db, feature_id, doc_id)
                os.makedirs(os.path.dirname(final_path), exist_ok=True)
                os.replace(tmp_path, final_path)
                tmp_path = None

                detail = _load_doc(cur, terrain_db, feature_id, doc_id)
        return jsonify({"message": "Documentation was saved.", "record": detail}), 201
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Documentation create failed for %s/%s: %s", terrain_db, feature_id, e)
        return _json_error("Internal server error.", 500)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@documentation_bp.get("/api/mobile/terrain/<terrain_db>/documentation/<feature_id>/<doc_id>")
@require_mobile_token
def get_documentation_detail(terrain_db: str, feature_id: str, doc_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        _cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                detail = _load_doc(cur, terrain_db, feature_id, doc_id)
                if detail is None:
                    return _json_error("Record not found.", 404)
        return jsonify({"record": detail})
    except Exception as e:
        logger.exception("Documentation detail failed for %s/%s/%s: %s", terrain_db, feature_id, doc_id, e)
        return _json_error("Internal server error.", 500)


@documentation_bp.put("/api/mobile/terrain/<terrain_db>/documentation/<feature_id>/<doc_id>")
@require_mobile_token
def update_documentation(terrain_db: str, feature_id: str, doc_id: str):
    claims = g.mobile_claims
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    payload = request.get_json(silent=True) or {}

    try:
        cfg = _cfg(feature_id)
        media_type = _nullable_text(payload.get("typ"))
        notes = _nullable_text(payload.get("notes"))
        author_email = _nullable_text(payload.get("author"))
        doc_date = _nullable_date(payload.get("datum"))
        if _uses_type(feature_id) and (media_type is None or media_type not in cfg["allowed_types"]):
            raise ValueError("Invalid documentation type.")
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                existing = _load_doc(cur, terrain_db, feature_id, doc_id)
                if existing is None:
                    return _json_error("Record not found.", 404)
                if feature_id == "photograms":
                    cur.execute(
                        """
                        UPDATE tab_photograms
                        SET photogram_typ = %s,
                            notes = %s,
                            ref_sketch = %s,
                            ref_photo_from = %s,
                            ref_photo_to = %s
                        WHERE id_photogram = %s
                        """,
                        (
                            media_type,
                            notes,
                            _nullable_text(payload.get("ref_sketch")),
                            _nullable_text(payload.get("ref_photo_from")),
                            _nullable_text(payload.get("ref_photo_to")),
                            doc_id,
                        ),
                    )
                elif feature_id == "drawings":
                    author_email = author_email or existing.get("author") or ((claims or {}).get("email") if claims else None)
                    if not author_email:
                        return _json_error("Author is missing.", 400)
                    if doc_date is None:
                        doc_date = _nullable_date(existing.get("datum")) or date.today()
                    cur.execute(
                        """
                        UPDATE tab_drawings
                        SET author = %s,
                            datum = %s,
                            notes = %s
                        WHERE id_drawing = %s
                        """,
                        (
                            author_email,
                            doc_date,
                            notes,
                            doc_id,
                        ),
                    )
                else:
                    author_email = author_email or existing.get("author") or ((claims or {}).get("email") if claims else None)
                    if not author_email:
                        return _json_error("Author is missing.", 400)
                    if doc_date is None:
                        doc_date = _nullable_date(existing.get("datum")) or date.today()
                    cur.execute(
                        f"""
                        UPDATE {cfg['table']}
                        SET {cfg['type_col']} = %s,
                            {cfg['author_col']} = %s,
                            {cfg['date_col']} = %s,
                            {cfg['notes_col']} = %s
                        WHERE {cfg['id_col']} = %s
                        """,
                        (media_type, author_email, doc_date, notes, doc_id),
                    )
                detail = _load_doc(cur, terrain_db, feature_id, doc_id)
        return jsonify({"message": "Documentation was updated.", "record": detail})
    except Exception as e:
        logger.exception("Documentation update failed for %s/%s/%s: %s", terrain_db, feature_id, doc_id, e)
        return _json_error("Internal server error.", 500)


@documentation_bp.delete("/api/mobile/terrain/<terrain_db>/documentation/<feature_id>/<doc_id>")
@require_mobile_token
def delete_documentation(terrain_db: str, feature_id: str, doc_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        cfg = _cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {cfg['table']} WHERE {cfg['id_col']} = %s",
                    (doc_id,),
                )
                if cur.rowcount == 0:
                    return _json_error("Record not found.", 404)
        path = _media_file_path(terrain_db, feature_id, doc_id)
        if os.path.exists(path):
            os.remove(path)
        return jsonify({"message": "Documentation was deleted."})
    except Exception as e:
        logger.exception("Documentation delete failed for %s/%s/%s: %s", terrain_db, feature_id, doc_id, e)
        return _json_error("Internal server error.", 500)


@documentation_bp.post("/api/mobile/terrain/<terrain_db>/documentation/<feature_id>/<doc_id>/relations")
@require_mobile_token
def set_documentation_relations(terrain_db: str, feature_id: str, doc_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    payload = request.get_json(silent=True) or {}

    try:
        _cfg(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if not _doc_exists(cur, feature_id, doc_id):
                    return _json_error("Record not found.", 404)
                _set_relations(cur, feature_id, doc_id, payload)
                detail = _load_doc(cur, terrain_db, feature_id, doc_id)
        return jsonify({"message": "Relations were updated.", "record": detail})
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Documentation relation update failed for %s/%s/%s: %s", terrain_db, feature_id, doc_id, e)
        return _json_error("Internal server error.", 500)


@documentation_bp.get("/api/mobile/terrain/<terrain_db>/documentation_media/<feature_id>/<doc_id>")
@require_mobile_token
def get_documentation_content(terrain_db: str, feature_id: str, doc_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    try:
        _cfg(feature_id)
        path = _media_file_path(terrain_db, feature_id, doc_id)
        if not os.path.exists(path):
            return _json_error("File not found.", 404)
        return send_file(path, conditional=True, etag=True)
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Documentation content failed for %s/%s/%s: %s", terrain_db, feature_id, doc_id, e)
        return _json_error("Internal server error.", 500)
