import logging
import os
from datetime import date
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

su_bp = Blueprint("su", __name__)
logger = logging.getLogger("mobile_api.su")

SU_KIND_TO_DB_TYPE = {
    "deposits": "deposit",
    "negatives": "negativ",
    "structures": "structure",
}

SU_DB_TYPE_TO_KIND = {value: key for key, value in SU_KIND_TO_DB_TYPE.items()}

SU_MEDIA_KIND_CONFIG = {
    "photos": {
        "table": "tab_photos",
        "id_col": "id_photo",
        "type_col": "photo_typ",
        "link_table": "tabaid_photo_sj",
        "link_media_col": "ref_photo",
        "allowed_types": PHOTO_TYP_CHOICES,
        "media_dir": "photos",
    },
    "sketches": {
        "table": "tab_sketches",
        "id_col": "id_sketch",
        "type_col": "sketch_typ",
        "link_table": "tabaid_sj_sketch",
        "link_media_col": "ref_sketch",
        "allowed_types": SKETCH_TYP_CHOICES,
        "media_dir": "sketches",
    },
    "drawings": {
        "table": "tab_drawings",
        "id_col": "id_drawing",
        "type_col": None,
        "link_table": "tabaid_sj_drawings",
        "link_media_col": "ref_drawing",
        "allowed_types": None,
        "media_dir": "drawings",
    },
    "photograms": {
        "table": "tab_photograms",
        "id_col": "id_photogram",
        "type_col": "photogram_typ",
        "link_table": "tabaid_photogram_sj",
        "link_media_col": "ref_photogram",
        "allowed_types": PHOTOGRAM_TYP_CHOICES,
        "media_dir": "photograms",
    },
}


def _validate_su_kind(feature_id: str):
    if feature_id not in SU_KIND_TO_DB_TYPE:
        raise ValueError("Invalid SU type.")
    return SU_KIND_TO_DB_TYPE[feature_id]


def _nullable_text(value):
    text = (value or "").strip()
    return text or None


def _nullable_float(value):
    text = (value or "").strip()
    if not text:
        return None
    return float(text)


def _nullable_int(value):
    text = (value or "").strip()
    if not text:
        return None
    return int(text)


def _load_su_detail(cur, su_id: int):
    cur.execute(
        """
        SELECT
            sj.id_sj,
            sj.sj_typ,
            sj.description,
            sj.interpretation,
            sj.author,
            sj.recorded,
            sj.docu_plan,
            sj.docu_vertical,
            dep.deposit_typ,
            dep.color,
            dep.boundary_visibility,
            dep."structure",
            dep.compactness,
            dep.deposit_removed,
            neg.negativ_typ,
            sj.excav_extent,
            neg.ident_niveau_cut,
            neg.shape_plan,
            neg.shape_sides,
            neg.shape_bottom,
            st.structure_typ,
            st.construction_typ,
            st.binder,
            st.basic_material,
            st.length_m,
            st.width_m,
            st.height_m
        FROM tab_sj sj
        LEFT JOIN tab_sj_deposit dep
          ON dep.id_deposit = sj.id_sj
        LEFT JOIN tab_sj_negativ neg
          ON neg.id_negativ = sj.id_sj
        LEFT JOIN tab_sj_structure st
          ON st.id_structure = sj.id_sj
        WHERE sj.id_sj = %s
        """,
        (su_id,),
    )
    row = cur.fetchone()
    if not row:
        return None

    sj_kind = SU_DB_TYPE_TO_KIND.get(row[1])
    return {
        "id": row[0],
        "kind": sj_kind,
        "description": row[2],
        "interpretation": row[3],
        "author": row[4],
        "recorded": row[5].isoformat() if row[5] else None,
        "docu_plan": bool(row[6]),
        "docu_vertical": bool(row[7]),
        "deposit_typ": row[8],
        "color": row[9],
        "boundary_visibility": row[10],
        "structure": row[11],
        "compactness": row[12],
        "deposit_removed": row[13],
        "negativ_typ": row[14],
        "excav_extent": row[15],
        "ident_niveau_cut": bool(row[16]) if row[16] is not None else False,
        "shape_plan": row[17],
        "shape_sides": row[18],
        "shape_bottom": row[19],
        "structure_typ": row[20],
        "construction_typ": row[21],
        "binder": row[22],
        "basic_material": row[23],
        "length_m": row[24],
        "width_m": row[25],
        "height_m": row[26],
    }


def _su_media_content_path(terrain_db: str, kind: str, media_id: str) -> str:
    return f"/api/mobile/terrain/{terrain_db}/su_media/{kind}/{quote(media_id)}"


def _media_preview_map(cur, terrain_db: str):
    previews = {}
    for kind, cfg in SU_MEDIA_KIND_CONFIG.items():
        cur.execute(
            f"""
            SELECT
                l.ref_sj,
                m.{cfg['id_col']},
                m.mime_type
            FROM {cfg['link_table']} l
            JOIN {cfg['table']} m
              ON m.{cfg['id_col']} = l.{cfg['link_media_col']}
            ORDER BY l.ref_sj, m.{cfg['id_col']}
            """
        )
        for su_id, media_id, mime_type in cur.fetchall():
            items = previews.setdefault(su_id, [])
            if len(items) >= 4:
                continue
            items.append(
                {
                    "kind": kind,
                    "id": media_id,
                    "type": None,
                    "mime_type": mime_type,
                    "content_path": _su_media_content_path(terrain_db, kind, media_id),
                }
            )
    return previews


def _validate_media_type(kind: str, value: str):
    cfg = SU_MEDIA_KIND_CONFIG.get(kind)
    if cfg is None:
        raise ValueError("Unsupported media kind.")
    if cfg["allowed_types"] is None:
        return cfg, None
    if value not in cfg["allowed_types"]:
        raise ValueError("Invalid media type.")
    return cfg, value


def _list_su_media(cur, terrain_db: str, su_id: int):
    output = {
        "photos": [],
        "sketches": [],
        "drawings": [],
        "photograms": [],
    }
    for kind, cfg in SU_MEDIA_KIND_CONFIG.items():
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
            WHERE l.ref_sj = %s
            ORDER BY m.{cfg['id_col']}
            """,
            (su_id,),
        )
        for media_id, media_type, notes, mime_type in cur.fetchall():
            output[kind].append(
                {
                    "kind": kind,
                    "id": media_id,
                    "type": media_type,
                    "notes": notes,
                    "mime_type": mime_type,
                    "content_path": _su_media_content_path(terrain_db, kind, media_id),
                }
            )
    return output


def _link_media_to_su(cur, kind: str, su_id: int, media_id: str):
    cfg = SU_MEDIA_KIND_CONFIG[kind]
    cur.execute(
        f"""
        INSERT INTO {cfg['link_table']} (ref_sj, {cfg['link_media_col']})
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (su_id, media_id),
    )


def _save_su(cur, feature_id: str, payload: dict, author_email: str, existing_id: int | None = None):
    sj_typ = _validate_su_kind(feature_id)
    su_id = _nullable_int(str(payload.get("id") if payload.get("id") is not None else ""))
    if su_id is None:
        raise ValueError("SU ID is required.")

    if existing_id is not None and su_id != existing_id:
        raise ValueError("SU ID cannot be changed in edit mode.")

    description = _nullable_text(payload.get("description"))
    interpretation = _nullable_text(payload.get("interpretation"))
    docu_plan = bool(payload.get("docu_plan"))
    docu_vertical = bool(payload.get("docu_vertical"))
    excav_extent = None
    if sj_typ == "negativ":
        raw_excav_extent = payload.get("excav_extent")
        excav_extent = _nullable_int(str(raw_excav_extent if raw_excav_extent is not None else ""))
        if excav_extent is not None and not 0 <= excav_extent <= 100:
            raise ValueError("Excavation extent must be between 0 and 100 percent.")

    if existing_id is None:
        cur.execute("SELECT 1 FROM tab_sj WHERE id_sj = %s", (su_id,))
        if cur.fetchone() is not None:
            raise ValueError("SU ID already exists.")
        cur.execute(
            """
            INSERT INTO tab_sj
                (id_sj, sj_typ, description, interpretation, author, recorded, docu_plan, docu_vertical, excav_extent)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (su_id, sj_typ, description, interpretation, author_email, date.today(), docu_plan, docu_vertical, excav_extent),
        )
    else:
        cur.execute("SELECT 1 FROM tab_sj WHERE id_sj = %s AND sj_typ = %s", (su_id, sj_typ))
        if cur.fetchone() is None:
            raise ValueError("SU not found.")
        cur.execute(
            """
            UPDATE tab_sj
            SET description = %s,
                interpretation = %s,
                docu_plan = %s,
                docu_vertical = %s,
                excav_extent = %s
            WHERE id_sj = %s
            """,
            (description, interpretation, docu_plan, docu_vertical, excav_extent, su_id),
        )
        cur.execute("DELETE FROM tab_sj_deposit WHERE id_deposit = %s", (su_id,))
        cur.execute("DELETE FROM tab_sj_negativ WHERE id_negativ = %s", (su_id,))
        cur.execute("DELETE FROM tab_sj_structure WHERE id_structure = %s", (su_id,))

    if sj_typ == "deposit":
        cur.execute(
            """
            INSERT INTO tab_sj_deposit
                (id_deposit, deposit_typ, color, boundary_visibility, "structure", compactness, deposit_removed)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                su_id,
                _nullable_text(payload.get("deposit_typ")),
                _nullable_text(payload.get("color")),
                _nullable_text(payload.get("boundary_visibility")),
                _nullable_text(payload.get("structure")),
                _nullable_text(payload.get("compactness")),
                _nullable_text(payload.get("deposit_removed")),
            ),
        )
    elif sj_typ == "negativ":
        cur.execute(
            """
            INSERT INTO tab_sj_negativ
                (id_negativ, negativ_typ, ident_niveau_cut, shape_plan, shape_sides, shape_bottom)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                su_id,
                _nullable_text(payload.get("negativ_typ")),
                bool(payload.get("ident_niveau_cut")),
                _nullable_text(payload.get("shape_plan")),
                _nullable_text(payload.get("shape_sides")),
                _nullable_text(payload.get("shape_bottom")),
            ),
        )
    else:
        try:
            length_m = _nullable_float(str(payload.get("length_m") if payload.get("length_m") is not None else ""))
            width_m = _nullable_float(str(payload.get("width_m") if payload.get("width_m") is not None else ""))
            height_m = _nullable_float(str(payload.get("height_m") if payload.get("height_m") is not None else ""))
        except ValueError:
            raise ValueError("Structure dimensions must be numeric values.")
        cur.execute(
            """
            INSERT INTO tab_sj_structure
                (id_structure, structure_typ, construction_typ, binder, basic_material, length_m, width_m, height_m)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                su_id,
                _nullable_text(payload.get("structure_typ")),
                _nullable_text(payload.get("construction_typ")),
                _nullable_text(payload.get("binder")),
                _nullable_text(payload.get("basic_material")),
                length_m,
                width_m,
                height_m,
            ),
        )

    return su_id


@su_bp.get("/api/mobile/terrain/<terrain_db>/su/<feature_id>")
@require_mobile_token
def list_sus(terrain_db: str, feature_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        sj_typ = _validate_su_kind(feature_id)
    except ValueError as e:
        return _json_error(str(e), 400)

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id_sj, description, interpretation, docu_plan, docu_vertical
                    FROM tab_sj
                    WHERE sj_typ = %s
                    ORDER BY id_sj
                    """,
                    (sj_typ,),
                )
                rows = cur.fetchall()
                preview_map = _media_preview_map(cur, terrain_db)

        return jsonify(
            {
                "records": [
                    {
                        "id": row[0],
                        "kind": feature_id,
                        "description": row[1],
                        "interpretation": row[2],
                        "docu_plan": bool(row[3]),
                        "docu_vertical": bool(row[4]),
                        "media_preview": preview_map.get(row[0], []),
                    }
                    for row in rows
                ]
            }
        )
    except Exception as e:
        logger.exception("SU list failed for %s/%s: %s", terrain_db, feature_id, e)
        return _json_error("Internal server error.", 500)


@su_bp.post("/api/mobile/terrain/<terrain_db>/su/<feature_id>")
@require_mobile_token
def create_su(terrain_db: str, feature_id: str):
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
                su_id = _save_su(cur, feature_id, payload, claims.get("email", ""))
                su = _load_su_detail(cur, su_id)
        return jsonify({"message": f'SU "{su_id}" was saved.', "su": su}), 201
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("SU create failed for %s/%s: %s", terrain_db, feature_id, e)
        return _json_error("Internal server error.", 500)


@su_bp.get("/api/mobile/terrain/<terrain_db>/su/<feature_id>/<int:su_id>")
@require_mobile_token
def get_su(terrain_db: str, feature_id: str, su_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                su = _load_su_detail(cur, su_id)
                if not su or su["kind"] != feature_id:
                    return _json_error("SU not found.", 404)
        return jsonify({"su": su})
    except Exception as e:
        logger.exception("SU detail failed for %s/%s/%s: %s", terrain_db, feature_id, su_id, e)
        return _json_error("Internal server error.", 500)


@su_bp.put("/api/mobile/terrain/<terrain_db>/su/<feature_id>/<int:su_id>")
@require_mobile_token
def update_su(terrain_db: str, feature_id: str, su_id: int):
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
                existing = _load_su_detail(cur, su_id)
                if not existing or existing["kind"] != feature_id:
                    return _json_error("SU not found.", 404)
                _save_su(cur, feature_id, payload, claims.get("email", ""), existing_id=su_id)
                su = _load_su_detail(cur, su_id)
        return jsonify({"message": f'SU "{su_id}" was updated.', "su": su})
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("SU update failed for %s/%s/%s: %s", terrain_db, feature_id, su_id, e)
        return _json_error("Internal server error.", 500)


@su_bp.delete("/api/mobile/terrain/<terrain_db>/su/<feature_id>/<int:su_id>")
@require_mobile_token
def delete_su(terrain_db: str, feature_id: str, su_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                su = _load_su_detail(cur, su_id)
                if not su or su["kind"] != feature_id:
                    return _json_error("SU not found.", 404)
                cur.execute("DELETE FROM tab_sj_deposit WHERE id_deposit = %s", (su_id,))
                cur.execute("DELETE FROM tab_sj_negativ WHERE id_negativ = %s", (su_id,))
                cur.execute("DELETE FROM tab_sj_structure WHERE id_structure = %s", (su_id,))
                cur.execute("DELETE FROM tab_sj WHERE id_sj = %s", (su_id,))
        return jsonify({"message": f'SU "{su_id}" was deleted.'})
    except Exception as e:
        logger.exception("SU delete failed for %s/%s/%s: %s", terrain_db, feature_id, su_id, e)
        return _json_error("Internal server error.", 500)


@su_bp.get("/api/mobile/terrain/<terrain_db>/su/<feature_id>/<int:su_id>/media")
@require_mobile_token
def list_su_media(terrain_db: str, feature_id: str, su_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                su = _load_su_detail(cur, su_id)
                if not su or su["kind"] != feature_id:
                    return _json_error("SU not found.", 404)
                media = _list_su_media(cur, terrain_db, su_id)
        return jsonify(
            {
                "su_id": su_id,
                "photos": media["photos"],
                "sketches": media["sketches"],
                "drawings": media["drawings"],
                "photograms": media["photograms"],
            }
        )
    except Exception as e:
        logger.exception("SU media list failed for %s/%s/%s: %s", terrain_db, feature_id, su_id, e)
        return _json_error("Internal server error.", 500)


@su_bp.post("/api/mobile/terrain/<terrain_db>/su/<feature_id>/<int:su_id>/media")
@require_mobile_token
def upload_su_media(terrain_db: str, feature_id: str, su_id: int):
    claims = g.mobile_claims
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    kind = (request.form.get("kind") or "").strip()
    media_type = (request.form.get("typ") or "").strip()
    notes = _nullable_text(request.form.get("notes"))
    file_storage = request.files.get("file")

    try:
        cfg, normalized_type = _validate_media_type(kind, media_type)
        if file_storage is None or not file_storage.filename:
            raise ValueError("Missing uploaded file.")
    except ValueError as e:
        return _json_error(str(e), 400)

    final_path = None
    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                su = _load_su_detail(cur, su_id)
                if not su or su["kind"] != feature_id:
                    return _json_error("SU not found.", 404)
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
                _link_media_to_su(cur, kind, su_id, media_id)

        return jsonify(
            {
                "message": f'{kind[:-1].capitalize()} was attached to SU "{su_id}".',
                "media": {
                    "kind": kind,
                    "id": media_id,
                    "type": normalized_type,
                    "notes": notes,
                    "mime_type": mime_type,
                    "content_path": _su_media_content_path(terrain_db, kind, media_id),
                },
            }
        ), 201
    except Exception as e:
        if final_path and os.path.exists(final_path):
            os.remove(final_path)
        if isinstance(e, ValueError):
            return _json_error(str(e), 400)
        logger.exception("SU media upload failed for %s/%s/%s: %s", terrain_db, feature_id, su_id, e)
        return _json_error("Internal server error.", 500)


@su_bp.get("/api/mobile/terrain/<terrain_db>/su_media/<kind>/<media_id>")
@require_mobile_token
def get_su_media_content(terrain_db: str, kind: str, media_id: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error
    if kind not in SU_MEDIA_KIND_CONFIG:
        return _json_error("Unsupported media kind.", 400)
    try:
        path = _media_file_path(terrain_db, kind, media_id)
        if not os.path.exists(path):
            return _json_error("Media file not found.", 404)
        return send_file(path, conditional=True)
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("SU media content failed for %s/%s/%s: %s", terrain_db, kind, media_id, e)
        return _json_error("Internal server error.", 500)
