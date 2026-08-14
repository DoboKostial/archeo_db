import logging

from flask import Blueprint, jsonify, request

from app.database import terrain_connection, terrain_transaction
from app.auth_tokens import require_mobile_token
from app.responses import _json_error
from app.validators import _validate_terrain_db

objects_bp = Blueprint("objects", __name__)
logger = logging.getLogger("mobile_api.objects")


def _nullable_text(value):
    text = (value or "").strip()
    return text or None


def _nullable_int(value):
    text = (value or "").strip()
    if not text:
        return None
    return int(text)


def _next_object_id(cur) -> int:
    cur.execute("SELECT COALESCE(MAX(id_object), 0) + 1 FROM tab_object")
    return cur.fetchone()[0]


def _list_object_types(cur):
    cur.execute("SELECT object_typ FROM gloss_object_type ORDER BY object_typ")
    return [row[0] for row in cur.fetchall()]


def _object_exists(cur, object_id: int) -> bool:
    cur.execute("SELECT 1 FROM tab_object WHERE id_object = %s", (object_id,))
    return cur.fetchone() is not None


def _superior_exists(cur, object_id: int) -> bool:
    cur.execute("SELECT 1 FROM tab_object WHERE id_object = %s", (object_id,))
    return cur.fetchone() is not None


def _has_children(cur, object_id: int) -> bool:
    cur.execute("SELECT 1 FROM tab_object WHERE superior_object = %s LIMIT 1", (object_id,))
    return cur.fetchone() is not None


def _would_create_cycle(cur, object_id: int, superior_object: int | None) -> bool:
    if superior_object is None:
        return False
    if superior_object == object_id:
        return True

    current = superior_object
    visited = set()
    while current is not None:
        if current == object_id:
            return True
        # a pre-existing cycle in the chain would loop forever; treat it as a cycle
        if current in visited:
            return True
        visited.add(current)
        cur.execute("SELECT superior_object FROM tab_object WHERE id_object = %s", (current,))
        row = cur.fetchone()
        current = row[0] if row else None
    return False


def _parse_su_ids(raw_items):
    if not isinstance(raw_items, list):
        raise ValueError("SU IDs must be a list.")
    values = []
    for item in raw_items:
        try:
            su_id = int(item)
        except (TypeError, ValueError):
            raise ValueError("SU IDs must be integers.")
        values.append(su_id)
    unique_values = sorted(set(values))
    if len(unique_values) < 2:
        raise ValueError("Object must contain at least two SUs.")
    return unique_values


def _validate_sus(cur, su_ids, object_id: int | None):
    for su_id in su_ids:
        cur.execute("SELECT ref_object FROM tab_sj WHERE id_sj = %s", (su_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"SU #{su_id} does not exist.")
        existing_object = row[0]
        if existing_object is not None and existing_object != object_id:
            raise ValueError(f"SU #{su_id} already belongs to a different object.")


def _upsert_object_type(cur, object_typ: str):
    cur.execute(
        """
        INSERT INTO gloss_object_type (object_typ, description_typ)
        VALUES (%s, NULL)
        ON CONFLICT DO NOTHING
        """,
        (object_typ,),
    )


def _load_object_detail(cur, object_id: int):
    cur.execute(
        """
        SELECT
            o.id_object,
            o.object_typ,
            o.superior_object,
            o.notes,
            COALESCE(
                ARRAY(
                    SELECT sj.id_sj
                    FROM tab_sj sj
                    WHERE sj.ref_object = o.id_object
                    ORDER BY sj.id_sj
                ),
                ARRAY[]::int[]
            ) AS su_ids,
            COALESCE(
                ARRAY(
                    SELECT child.id_object
                    FROM tab_object child
                    WHERE child.superior_object = o.id_object
                    ORDER BY child.id_object
                ),
                ARRAY[]::int[]
            ) AS child_ids
        FROM tab_object o
        WHERE o.id_object = %s
        """,
        (object_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "object_typ": row[1],
        "superior_object": row[2],
        "notes": row[3],
        "su_ids": row[4] or [],
        "child_ids": row[5] or [],
    }


def _list_objects(cur):
    cur.execute(
        """
        SELECT
            o.id_object,
            o.object_typ,
            o.superior_object,
            o.notes,
            COALESCE(COUNT(sj.id_sj), 0) AS su_count
        FROM tab_object o
        LEFT JOIN tab_sj sj
          ON sj.ref_object = o.id_object
        GROUP BY o.id_object, o.object_typ, o.superior_object, o.notes
        ORDER BY o.id_object
        """
    )
    rows = cur.fetchall()
    items = []
    for row in rows:
        detail = _load_object_detail(cur, row[0])
        items.append(
            {
                "id": row[0],
                "object_typ": row[1],
                "superior_object": row[2],
                "notes": row[3],
                "su_count": row[4],
                "su_ids": detail["su_ids"] if detail else [],
                "child_ids": detail["child_ids"] if detail else [],
            }
        )
    return items


def _save_object(cur, object_id: int, object_typ: str, superior_object: int | None, notes: str | None, su_ids, existing: bool):
    _upsert_object_type(cur, object_typ)

    if existing:
        cur.execute(
            """
            UPDATE tab_object
            SET object_typ = %s,
                superior_object = %s,
                notes = %s
            WHERE id_object = %s
            """,
            (object_typ, superior_object, notes, object_id),
        )
        cur.execute("UPDATE tab_sj SET ref_object = NULL WHERE ref_object = %s", (object_id,))
    else:
        cur.execute(
            """
            INSERT INTO tab_object (id_object, object_typ, superior_object, notes)
            VALUES (%s, %s, %s, %s)
            """,
            (object_id, object_typ, superior_object, notes),
        )

    for su_id in su_ids:
        cur.execute("UPDATE tab_sj SET ref_object = %s WHERE id_sj = %s", (object_id, su_id))


@objects_bp.get("/api/mobile/terrain/<terrain_db>/objects/types")
@require_mobile_token
def list_object_types(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                types = _list_object_types(cur)
                next_id = _next_object_id(cur)
        return jsonify({"object_types": types, "suggested_id": next_id})
    except Exception as e:
        logger.exception("Object type list failed for %s: %s", terrain_db, e)
        return _json_error("Internal server error.", 500)


@objects_bp.post("/api/mobile/terrain/<terrain_db>/objects/types")
@require_mobile_token
def create_object_type(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    payload = request.get_json(silent=True) or {}
    object_typ = _nullable_text(payload.get("object_typ"))
    if not object_typ:
        return _json_error("Object type name is missing.", 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                _upsert_object_type(cur, object_typ)
                types = _list_object_types(cur)
        return jsonify({"message": f'Type "{object_typ}" was saved.', "object_types": types})
    except Exception as e:
        logger.exception("Object type save failed for %s/%s: %s", terrain_db, object_typ, e)
        return _json_error("Internal server error.", 500)


@objects_bp.get("/api/mobile/terrain/<terrain_db>/objects")
@require_mobile_token
def list_objects(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                items = _list_objects(cur)
        return jsonify({"objects": items})
    except Exception as e:
        logger.exception("Object list failed for %s: %s", terrain_db, e)
        return _json_error("Internal server error.", 500)


@objects_bp.get("/api/mobile/terrain/<terrain_db>/objects/overview")
@require_mobile_token
def objects_overview(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                items = _list_objects(cur)
        roots = [item for item in items if item["superior_object"] is None]
        return jsonify({"objects": items, "root_ids": [item["id"] for item in roots]})
    except Exception as e:
        logger.exception("Object overview failed for %s: %s", terrain_db, e)
        return _json_error("Internal server error.", 500)


@objects_bp.post("/api/mobile/terrain/<terrain_db>/objects")
@require_mobile_token
def create_object(terrain_db: str):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    payload = request.get_json(silent=True) or {}
    try:
        object_id = int(payload.get("id"))
        object_typ = _nullable_text(payload.get("object_typ"))
        superior_object = _nullable_int(str(payload.get("superior_object") if payload.get("superior_object") is not None else ""))
        notes = _nullable_text(payload.get("notes"))
        su_ids = _parse_su_ids(payload.get("su_ids") or [])
        if not object_typ:
            raise ValueError("Object type is required.")
    except Exception as e:
        return _json_error(str(e), 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if _object_exists(cur, object_id):
                    return _json_error(f"Object #{object_id} already exists.", 409)
                if superior_object is not None:
                    if not _superior_exists(cur, superior_object):
                        return _json_error(f"Superior object #{superior_object} does not exist.", 400)
                    if _would_create_cycle(cur, object_id, superior_object):
                        return _json_error("Invalid superior object: would create a cycle.", 400)
                _validate_sus(cur, su_ids, None)
                _save_object(cur, object_id, object_typ, superior_object, notes, su_ids, existing=False)
                detail = _load_object_detail(cur, object_id)
        return jsonify({"message": f'Object "{object_id}" was saved.', "object": detail}), 201
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Object save failed for %s/%s: %s", terrain_db, object_id, e)
        return _json_error("Internal server error.", 500)


@objects_bp.get("/api/mobile/terrain/<terrain_db>/objects/<int:object_id>")
@require_mobile_token
def get_object(terrain_db: str, object_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_connection(terrain_db) as conn:
            with conn.cursor() as cur:
                detail = _load_object_detail(cur, object_id)
                if not detail:
                    return _json_error("Object not found.", 404)
        return jsonify({"object": detail})
    except Exception as e:
        logger.exception("Object detail failed for %s/%s: %s", terrain_db, object_id, e)
        return _json_error("Internal server error.", 500)


@objects_bp.put("/api/mobile/terrain/<terrain_db>/objects/<int:object_id>")
@require_mobile_token
def update_object(terrain_db: str, object_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    payload = request.get_json(silent=True) or {}
    try:
        payload_id = int(payload.get("id"))
        if payload_id != object_id:
            raise ValueError("Object ID cannot be changed in edit mode.")
        object_typ = _nullable_text(payload.get("object_typ"))
        superior_object = _nullable_int(str(payload.get("superior_object") if payload.get("superior_object") is not None else ""))
        notes = _nullable_text(payload.get("notes"))
        su_ids = _parse_su_ids(payload.get("su_ids") or [])
        if not object_typ:
            raise ValueError("Object type is required.")
    except Exception as e:
        return _json_error(str(e), 400)

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if not _object_exists(cur, object_id):
                    return _json_error("Object not found.", 404)
                if superior_object is not None:
                    if not _superior_exists(cur, superior_object):
                        return _json_error(f"Superior object #{superior_object} does not exist.", 400)
                    if _would_create_cycle(cur, object_id, superior_object):
                        return _json_error("Invalid superior object: would create a cycle.", 400)
                _validate_sus(cur, su_ids, object_id)
                _save_object(cur, object_id, object_typ, superior_object, notes, su_ids, existing=True)
                detail = _load_object_detail(cur, object_id)
        return jsonify({"message": f'Object "{object_id}" was updated.', "object": detail})
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Object update failed for %s/%s: %s", terrain_db, object_id, e)
        return _json_error("Internal server error.", 500)


@objects_bp.delete("/api/mobile/terrain/<terrain_db>/objects/<int:object_id>")
@require_mobile_token
def delete_object(terrain_db: str, object_id: int):
    db_error = _validate_terrain_db(terrain_db)
    if db_error:
        return db_error

    try:
        with terrain_transaction(terrain_db) as conn:
            with conn.cursor() as cur:
                if not _object_exists(cur, object_id):
                    return _json_error("Object not found.", 404)
                if _has_children(cur, object_id):
                    return _json_error("Cannot delete: object has child objects.", 409)
                cur.execute("UPDATE tab_sj SET ref_object = NULL WHERE ref_object = %s", (object_id,))
                cur.execute("DELETE FROM tab_object WHERE id_object = %s", (object_id,))
        return jsonify({"message": f'Object "{object_id}" was deleted.'})
    except Exception as e:
        logger.exception("Object delete failed for %s/%s: %s", terrain_db, object_id, e)
        return _json_error("Internal server error.", 500)
