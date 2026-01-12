# web_app/app/routes/archeo_objects.py

from __future__ import annotations

import io
import json
from typing import Optional

from flask import (
    Blueprint,
    request,
    render_template,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
    make_response,
)
from weasyprint import HTML

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db

from app.queries import (
    # objects
    q_list_objects_with_sjs,
    q_get_object_with_sjs,
    q_object_exists,
    q_superior_exists,
    q_sj_exists,
    q_sj_belongs_to_other_object,
    q_unassign_sjs_not_in_list,
    q_assign_sjs_to_object,
    q_update_object,
    q_delete_object,
    q_has_children,
    # inhum grave
    q_has_inhum_grave,
    q_get_object_inhum_grave,
    q_upsert_object_inhum_grave,
    q_delete_object_inhum_grave,
)

archeo_objects_bp = Blueprint("archeo_objects", __name__)


# ----------------------------
# helpers
# ----------------------------

def _get_next_object_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id_object), 0) + 1 FROM tab_object;")
        return int(cur.fetchone()[0])


def _get_object_types(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT object_typ FROM gloss_object_type ORDER BY object_typ;")
        return [row[0] for row in cur.fetchall()]


def _get_object_superior(conn, id_object: int) -> Optional[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT superior_object FROM tab_object WHERE id_object = %s;", (id_object,))
        row = cur.fetchone()
        if not row:
            return None
        return row[0]


def _would_create_cycle(conn, id_object: int, superior_object: Optional[int]) -> bool:
    """
    Prevent cycles in superior_object chain (A->B->C->A).
    Application-level safety check.
    """
    if superior_object is None:
        return False
    if superior_object == id_object:
        return True

    seen = set()
    current = superior_object
    # Walk up parent chain; if we reach id_object, cycle would be created.
    while current is not None:
        if current == id_object:
            return True
        if current in seen:
            # existing cycle in DB (shouldn't happen) -> treat as cycle
            return True
        seen.add(current)
        current = _get_object_superior(conn, current)

    return False


def _parse_bool(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# ----------------------------
# routes
# ----------------------------

@archeo_objects_bp.route("/objects", methods=["GET", "POST"])
@require_selected_db
def objects():
    selected_db = session["selected_db"]
    form_data = None

    conn = get_terrain_connection(selected_db)
    try:
        suggested_id = _get_next_object_id(conn)
        object_types = _get_object_types(conn)

        # right-side table (existing objects)
        objects_rows = q_list_objects_with_sjs(conn)

        if request.method == "POST":
            form_data = request.form  # keep MultiDict for getlist()

            try:
                id_object = int(request.form.get("id_object"))
                object_typ = (request.form.get("object_typ") or "").strip()
                superior_raw = (request.form.get("superior_object") or "").strip()
                notes = (request.form.get("notes") or "").strip() or None
                sj_ids_raw = request.form.getlist("sj_ids[]")

                # inhum grave hidden inputs (create form)
                is_inhum_grave = _parse_bool(request.form.get("is_inhum_grave"))
                inhum_preservation = (request.form.get("inhum_preservation") or "").strip() or None
                inhum_orientation_dir = (request.form.get("inhum_orientation_dir") or "").strip() or None
                inhum_bone_map = (request.form.get("inhum_bone_map") or "").strip() or None
                inhum_notes = (request.form.get("inhum_notes") or "").strip() or None
                inhum_anthropo_present = _parse_bool(request.form.get("inhum_anthropo_present"))
                inhum_burial_box_type = (request.form.get("inhum_burial_box_type") or "").strip() or None

                if not object_typ:
                    flash("Object type is required.", "danger")
                    raise ValueError("Missing object_typ.")

                # unique ID
                if q_object_exists(conn, id_object):
                    flash(f"Object #{id_object} already exists.", "warning")
                    raise ValueError("Duplicate object id.")

                # SUs: >=2 and exist
                if len(sj_ids_raw) < 2:
                    flash("Object must contain at least two stratigraphic units (SUs).", "warning")
                    raise ValueError("Insufficient number of SUs.")

                sj_ids: list[int] = []
                for sj_id_str in sj_ids_raw:
                    sj_id = int(sj_id_str)
                    if not q_sj_exists(conn, sj_id):
                        flash(f"SU #{sj_id} does not exist.", "danger")
                        raise ValueError(f"Nonexistent SU {sj_id}.")
                    # On create, SU must not already belong to another object
                    if q_sj_belongs_to_other_object(conn, sj_id, id_object):
                        flash(f"SU #{sj_id} already belongs to a different object.", "danger")
                        raise ValueError("SU belongs to other object.")
                    sj_ids.append(sj_id)

                # superior validation (optional)
                superior_object: Optional[int] = None
                if superior_raw:
                    superior_object = int(superior_raw)
                    if not q_superior_exists(conn, superior_object):
                        flash(f"Superior object #{superior_object} does not exist.", "danger")
                        raise ValueError("Nonexistent superior object.")
                    if _would_create_cycle(conn, id_object, superior_object):
                        flash("Invalid superior object: would create a cycle.", "danger")
                        raise ValueError("Cycle detected.")

                # insert object
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO tab_object (id_object, object_typ, superior_object, notes)
                        VALUES (%s, %s, %s, %s);
                        """,
                        (id_object, object_typ, superior_object, notes),
                    )

                # assign SUs
                q_assign_sjs_to_object(conn, id_object, sj_ids)

                # insert inhum grave if present
                if is_inhum_grave:
                    # bone_map must be json if provided
                    if inhum_bone_map:
                        try:
                            json.loads(inhum_bone_map)
                        except Exception:
                            flash("Inhumation bone map is not valid JSON.", "danger")
                            raise ValueError("Invalid bone_map JSON.")

                    q_upsert_object_inhum_grave(
                        conn=conn,
                        id_object=id_object,
                        preservation=inhum_preservation,
                        orientation_dir=inhum_orientation_dir,
                        bone_map_json=inhum_bone_map,
                        notes_grave=inhum_notes,
                        anthropo_present=inhum_anthropo_present,
                        burial_box_type=inhum_burial_box_type,
                    )

                conn.commit()
                logger.info(f"[{selected_db}] Object #{id_object} created (inhum={is_inhum_grave}).")
                flash(f"Object #{id_object} has been created.", "success")
                return redirect(url_for("archeo_objects.objects"))

            except Exception as e:
                conn.rollback()
                logger.exception(f"[{selected_db}] Error while creating object: {e}")
                # re-render with form_data preserved

        return render_template(
            "objects.html",
            suggested_id=suggested_id,
            object_types=object_types,
            selected_db=selected_db,
            form_data=form_data,
            objects=objects_rows,
        )

    finally:
        try:
            conn.close()
        except Exception:
            pass


@archeo_objects_bp.route("/define-object-type", methods=["POST"])
@require_selected_db
def define_object_type():
    selected_db = session["selected_db"]
    data = request.get_json() or {}
    new_type = (data.get("object_typ") or "").strip()
    description = (data.get("description_typ") or "").strip()

    if not new_type:
        logger.warning(f"[{selected_db}] Attempt to create empty object type.")
        return jsonify({"error": "Object type name is missing."}), 400

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gloss_object_type (object_typ, description_typ)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (new_type, description),
            )
        conn.commit()
        logger.info(f"[{selected_db}] Added object type '{new_type}'.")
        return jsonify({"message": f"Type '{new_type}' has been saved."}), 200

    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] Error while saving object type '{new_type}': {e}")
        return jsonify({"error": f"Error while saving: {str(e)}"}), 500

    finally:
        try:
            conn.close()
        except Exception:
            pass


@archeo_objects_bp.get("/objects/api/<int:id_object>")
@require_selected_db
def api_get_object(id_object: int):
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        obj = q_get_object_with_sjs(conn, id_object)
        if not obj:
            return jsonify({"error": "Object not found."}), 404

        payload = {
            "id_object": obj[0],
            "object_typ": obj[1],
            "superior_object": obj[2],
            "notes": obj[3],
            "sj_ids": obj[4] or [],
        }

        g = q_get_object_inhum_grave(conn, id_object)
        if g:
            # (preservation, orientation_dir, bone_map, notes_grave, anthropo_present, burial_box_type)
            payload["inhum_grave"] = {
                "present": True,
                "preservation": g[0],
                "orientation_dir": g[1],
                "bone_map": g[2],
                "notes_grave": g[3],
                "anthropo_present": bool(g[4]) if g[4] is not None else False,
                "burial_box_type": g[5],
            }
        else:
            payload["inhum_grave"] = {"present": False}

        return jsonify(payload), 200

    finally:
        try:
            conn.close()
        except Exception:
            pass


@archeo_objects_bp.post("/objects/update")
@require_selected_db
def update_object():
    selected_db = session["selected_db"]
    data = request.get_json() or {}

    try:
        id_object = int(data.get("id_object"))
        object_typ = (data.get("object_typ") or "").strip()
        superior_raw = (data.get("superior_object") or "").strip()
        notes = (data.get("notes") or "").strip() or None
        sj_ids_raw = data.get("sj_ids") or []

        if not object_typ:
            return jsonify({"error": "Object type is required."}), 400

        sj_ids = [int(x) for x in sj_ids_raw]
        if len(sj_ids) < 2:
            return jsonify({"error": "Object must contain at least two SUs."}), 400

        superior_object: Optional[int] = None
        if superior_raw:
            superior_object = int(superior_raw)
            if superior_object == id_object:
                return jsonify({"error": "Superior object cannot be the same as the object itself."}), 400

        inhum = data.get("inhum_grave") or {}
        inhum_present = _parse_bool(inhum.get("present", False))

    except Exception as e:
        return jsonify({"error": f"Invalid input: {e}"}), 400

    conn = get_terrain_connection(selected_db)
    try:
        if not q_object_exists(conn, id_object):
            return jsonify({"error": f"Object #{id_object} does not exist."}), 404

        if superior_object is not None:
            if not q_superior_exists(conn, superior_object):
                return jsonify({"error": f"Superior object #{superior_object} does not exist."}), 400
            if _would_create_cycle(conn, id_object, superior_object):
                return jsonify({"error": "Invalid superior object: would create a cycle."}), 400

        # validate SUs and one-object rule
        for sj_id in sj_ids:
            if not q_sj_exists(conn, sj_id):
                return jsonify({"error": f"SU #{sj_id} does not exist."}), 400
            if q_sj_belongs_to_other_object(conn, sj_id, id_object):
                return jsonify({"error": f"SU #{sj_id} already belongs to a different object."}), 409

        # update base object
        q_update_object(conn, id_object, object_typ, superior_object, notes)

        # re-assign SUs
        q_unassign_sjs_not_in_list(conn, id_object, sj_ids)
        q_assign_sjs_to_object(conn, id_object, sj_ids)

        # inhum grave
        if inhum_present:
            preservation = (inhum.get("preservation") or "").strip() or None
            orientation_dir = (inhum.get("orientation_dir") or "").strip() or None
            notes_grave = (inhum.get("notes_grave") or "").strip() or None
            anthropo_present = _parse_bool(inhum.get("anthropo_present", False))
            burial_box_type = (inhum.get("burial_box_type") or "").strip() or None

            bone_map = inhum.get("bone_map")
            if bone_map is None or bone_map == "":
                bone_map_json = None
            elif isinstance(bone_map, (dict, list)):
                bone_map_json = json.dumps(bone_map)
            else:
                bone_map_json = str(bone_map)

            if bone_map_json:
                try:
                    json.loads(bone_map_json)
                except Exception:
                    return jsonify({"error": "Bone map is not valid JSON."}), 400

            q_upsert_object_inhum_grave(
                conn=conn,
                id_object=id_object,
                preservation=preservation,
                orientation_dir=orientation_dir,
                bone_map_json=bone_map_json,
                notes_grave=notes_grave,
                anthropo_present=anthropo_present,
                burial_box_type=burial_box_type,
            )
        else:
            # remove if existed
            if q_has_inhum_grave(conn, id_object):
                q_delete_object_inhum_grave(conn, id_object)

        conn.commit()
        logger.info(f"[{selected_db}] Object #{id_object} updated (inhum={inhum_present}).")
        return jsonify({"message": f"Object #{id_object} updated."}), 200

    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] update_object error: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        try:
            conn.close()
        except Exception:
            pass


@archeo_objects_bp.post("/objects/delete")
@require_selected_db
def delete_object():
    selected_db = session["selected_db"]
    data = request.get_json() or {}

    try:
        id_object = int(data.get("id_object"))
    except Exception:
        return jsonify({"error": "Invalid object id."}), 400

    conn = get_terrain_connection(selected_db)
    try:
        if not q_object_exists(conn, id_object):
            return jsonify({"error": f"Object #{id_object} does not exist."}), 404

        if q_has_children(conn, id_object):
            return jsonify({"error": "Cannot delete: object has child objects."}), 409

        # unassign all SUs first
        q_unassign_sjs_not_in_list(conn, id_object, keep_sj_ids=[])

        # inhum grave row will be deleted by ON DELETE CASCADE, but ok to be explicit
        if q_has_inhum_grave(conn, id_object):
            q_delete_object_inhum_grave(conn, id_object)

        q_delete_object(conn, id_object)

        conn.commit()
        logger.info(f"[{selected_db}] Object #{id_object} deleted.")
        return jsonify({"message": f"Object #{id_object} deleted."}), 200

    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] delete_object error: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        try:
            conn.close()
        except Exception:
            pass


@archeo_objects_bp.route("/list-objects")
@require_selected_db
def list_objects():
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        objects_rows = q_list_objects_with_sjs(conn)
        return render_template("list_objects.html", objects=objects_rows)
    except Exception as e:
        logger.exception(f"[{selected_db}] Error loading objects: {e}")
        flash(f"Error while loading objects: {e}", "danger")
        return render_template("list_objects.html", objects=[])
    finally:
        try:
            conn.close()
        except Exception:
            pass


@archeo_objects_bp.route("/generate-objects-pdf", methods=["POST"])
@require_selected_db
def generate_objects_pdf():
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        objects_rows = q_list_objects_with_sjs(conn)
        rendered = render_template("pdf_objects.html", objects=objects_rows)
        pdf_io = io.BytesIO()
        HTML(string=rendered).write_pdf(pdf_io)
        pdf_io.seek(0)

        response = make_response(pdf_io.read())
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = "inline; filename=objects.pdf"
        return response

    except Exception as e:
        logger.exception(f"[{selected_db}] Error while generating PDF: {e}")
        flash(f"Error while generating PDF: {e}", "danger")
        return redirect(url_for("archeo_objects.objects"))

    finally:
        try:
            conn.close()
        except Exception:
            pass
