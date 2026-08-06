# web_app/app/routes/su.py
import os
import re
import json
from datetime import datetime
from psycopg2.extras import Json

import networkx as nx
from networkx.algorithms.dag import transitive_reduction
import matplotlib

matplotlib.use("Agg")  # backend without GUI (no Tk)

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import Counter, defaultdict

from flask import (
    Blueprint,
    request,
    render_template,
    redirect,
    url_for,
    flash,
    session,
    send_from_directory,
    jsonify,
)

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db, float_or_none
from app.utils.admin import get_hmatrix_dirs

from app.queries import (
    count_sj_by_type,
    count_sj_by_type_all,
    count_objects,
    count_sj_without_relation,
    count_total_sj,
    fetch_stratigraphy_relations,
    get_all_sj_with_types,
    get_all_objects,
    get_sj_with_object_refs,
    harris_su_detail_sql,
    q_get_object_with_sjs,
    q_get_object_inhum_grave,
    list_polygon_names_sql,
    list_su_table_sql,
    list_su_for_media_select_sql,
    insert_sj_polygon_link_sql,
    delete_su_sql,
    su_exists_sql,
    update_su_base_sql,
    delete_su_deposit_sql,
    delete_su_negativ_sql,
    delete_su_structure_sql,
    insert_su_deposit_sql,
    insert_su_negativ_sql,
    insert_su_structure_sql,
    delete_sj_polygon_links_sql,
    delete_sj_stratigraphy_links_sql,
    insert_sj_stratigraphy_sql,
)

from app.utils import (
    save_to_uploads,
    cleanup_upload,
    make_pk,
    validate_pk,
    validate_mime,
    validate_extension,
    detect_mime,
    final_paths,
    move_into_place,
    make_thumbnail,
    sha256_file,
    extract_exif,
    delete_media_files,
)

from app.utils.media_map import MEDIA_TABLES, LINK_TABLES_SJ

su_bp = Blueprint("su", __name__)


def _harris_links_filename(image_filename):
    return f"{image_filename}.links.json"


def _load_harris_links(selected_db, image_filename):
    if not image_filename:
        return []
    images_dir, _ = get_hmatrix_dirs(selected_db)
    path = os.path.join(images_dir, _harris_links_filename(os.path.basename(image_filename)))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    return data.get("areas") or []


def _save_harris_links(images_dir, image_filename, areas):
    path = os.path.join(images_dir, _harris_links_filename(image_filename))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"image": image_filename, "areas": areas}, handle, ensure_ascii=False)


def _date_or_none(value):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _percent_or_none(value):
    value = (value or "").strip().rstrip("%").strip()
    if not value:
        return None
    if not re.fullmatch(r"\d{1,3}", value):
        raise ValueError("Excavation extent must be a whole number from 0 to 100.")
    percent = int(value)
    if percent < 0 or percent > 100:
        raise ValueError("Excavation extent must be between 0 and 100.")
    return percent


def _su_id_list(value, current_id):
    ids = []
    seen = set()
    for token in re.split(r"[\s,;]+", value or ""):
        if not token:
            continue
        try:
            sj_id = int(token)
        except ValueError:
            raise ValueError(f"Invalid related SU ID: {token}")
        if sj_id == current_id:
            raise ValueError("An SU cannot have a stratigraphic relation to itself.")
        if sj_id not in seen:
            ids.append(sj_id)
            seen.add(sj_id)
    return ids


def _su_row_to_dict(row):
    recorded = row[4].isoformat() if row[4] else ""
    return {
        "id": int(row[0]),
        "typ": row[1] or "",
        "desc": row[2] or "",
        "interpretation": row[3] or "",
        "recorded": recorded,
        "author": row[5] or "",
        "docu_plan": bool(row[6]),
        "docu_vertical": bool(row[7]),
        "excav_extent": row[8] or "",
        "deposit_typ": row[9] or "",
        "color": row[10] or "",
        "boundary_visibility": row[11] or "",
        "structure": row[12] or "",
        "compactness": row[13] or "",
        "deposit_removed": row[14] or "",
        "negativ_typ": row[15] or "",
        "ident_niveau_cut": bool(row[16]),
        "shape_plan": row[17] or "",
        "shape_sides": row[18] or "",
        "shape_bottom": row[19] or "",
        "structure_typ": row[20] or "",
        "construction_typ": row[21] or "",
        "binder": row[22] or "",
        "basic_material": row[23] or "",
        "length_m": "" if row[24] is None else row[24],
        "width_m": "" if row[25] is None else row[25],
        "height_m": "" if row[26] is None else row[26],
        "polygon_names": list(row[27] or []),
        "above_ids": [int(v) for v in (row[28] or [])],
        "below_ids": [int(v) for v in (row[29] or [])],
        "equal_ids": [int(v) for v in (row[30] or [])],
    }


def _save_su_subtype(cur, sj_id, sj_typ, form):
    cur.execute(delete_su_deposit_sql(), (sj_id,))
    cur.execute(delete_su_negativ_sql(), (sj_id,))
    cur.execute(delete_su_structure_sql(), (sj_id,))

    if sj_typ == "deposit":
        cur.execute(
            insert_su_deposit_sql(),
            (
                sj_id,
                form.get("deposit_typ"),
                form.get("color"),
                form.get("boundary_visibility"),
                form.get("structure"),
                form.get("compactness"),
                form.get("deposit_removed"),
            ),
        )
    elif sj_typ == "negativ":
        cur.execute(
            insert_su_negativ_sql(),
            (
                sj_id,
                form.get("negativ_typ"),
                "ident_niveau_cut" in form,
                form.get("shape_plan"),
                form.get("shape_sides"),
                form.get("shape_bottom"),
            ),
        )
    elif sj_typ == "structure":
        cur.execute(
            insert_su_structure_sql(),
            (
                sj_id,
                form.get("structure_typ"),
                form.get("construction_typ"),
                form.get("binder"),
                form.get("basic_material"),
                float_or_none(form.get("length_m")),
                float_or_none(form.get("width_m")),
                float_or_none(form.get("height_m")),
            ),
        )
    else:
        raise ValueError("Invalid type of stratigraphic unit.")


# -------------------------------------------------------------------
# SU: main page (new SU + SU list + attach media)
# -------------------------------------------------------------------
@su_bp.route("/add-su", methods=["GET", "POST"])
@su_bp.route("/add-sj", methods=["GET", "POST"])  # backward compatibility
@require_selected_db
def add_su():
    selected_db = session["selected_db"]
    open_edit_su_id = request.args.get("edit_su", type=int)
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    # values needed for rendering (always)
    suggested_id = None
    authors = []
    polygons = []
    su_for_media = []
    sus = []
    form_data = {}

    try:
        # Suggested next SU id
        cur.execute("SELECT COALESCE(MAX(id_sj), 0) + 1 FROM tab_sj;")
        suggested_id = cur.fetchone()[0]

        # Authors list
        cur.execute("SELECT mail FROM gloss_personalia ORDER BY mail;")
        authors = [row[0] for row in cur.fetchall()]

        # Polygons list for in-page filtering
        cur.execute(list_polygon_names_sql())
        polygons = [r[0] for r in cur.fetchall()]

        # SU list for Attach graphic documentation
        cur.execute(list_su_for_media_select_sql())
        su_for_media = [
            {"id": int(r[0]), "typ": (r[1] or ""), "desc": (r[2] or "")} for r in cur.fetchall()
        ]

        # Full SU list; the template paginates it client-side.
        cur.execute(list_su_table_sql())
        sus = [_su_row_to_dict(r) for r in cur.fetchall()]

        # Overview counts
        cur.execute(count_total_sj())
        sj_count_total = cur.fetchone()[0]

        cur.execute(*count_sj_by_type("deposit"))
        sj_count_deposit = cur.fetchone()[0]

        cur.execute(*count_sj_by_type("negativ"))
        sj_count_negativ = cur.fetchone()[0]

        cur.execute(*count_sj_by_type("structure"))
        sj_count_structure = cur.fetchone()[0]

        if request.method == "POST":
            try:
                id_sj = int(request.form.get("id_sj") or "0")
                if id_sj <= 0:
                    raise ValueError("Invalid SU ID.")

                # uniqueness
                cur.execute("SELECT 1 FROM tab_sj WHERE id_sj = %s;", (id_sj,))
                if cur.fetchone():
                    flash(
                        f"ID of stratigraphic unit #{id_sj} already exists. Please provide another ID.",
                        "warning",
                    )
                    form_data = request.form.to_dict(flat=True)
                    return render_template(
                        "add_su.html",
                        selected_db=selected_db,
                        suggested_id=suggested_id,
                        authors=authors,
                        polygons=polygons,
                        su_for_media=su_for_media,
                        sus=sus,
                        sj_count_total=sj_count_total,
                        sj_count_deposit=sj_count_deposit,
                        sj_count_negativ=sj_count_negativ,
                        sj_count_structure=sj_count_structure,
                        form_data=form_data,
                        open_edit_su_id=open_edit_su_id,
                    )

                sj_typ = (request.form.get("sj_typ") or "").strip().lower()
                description = request.form.get("description")
                interpretation = request.form.get("interpretation")
                author = request.form.get("author")
                recorded = datetime.now().date()  # DDL uses date
                docu_plan = "docu_plan" in request.form
                docu_vertical = "docu_vertical" in request.form
                excav_extent = _percent_or_none(request.form.get("excav_extent"))

                # Insert into tab_sj (base)
                cur.execute(
                    """
                    INSERT INTO tab_sj
                      (id_sj, sj_typ, description, interpretation, author, recorded, docu_plan, docu_vertical, excav_extent)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (id_sj, sj_typ, description, interpretation, author, recorded, docu_plan, docu_vertical, excav_extent),
                )

                # Insert into type-specific tables
                if sj_typ == "deposit":
                    cur.execute(
                        """
                        INSERT INTO tab_sj_deposit
                          (id_deposit, deposit_typ, color, boundary_visibility, "structure", compactness, deposit_removed)
                        VALUES
                          (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            id_sj,
                            request.form.get("deposit_typ"),
                            request.form.get("color"),
                            request.form.get("boundary_visibility"),
                            request.form.get("structure"),
                            request.form.get("compactness"),
                            request.form.get("deposit_removed"),
                        ),
                    )
                elif sj_typ == "negativ":
                    cur.execute(
                        """
                        INSERT INTO tab_sj_negativ
                          (id_negativ, negativ_typ, ident_niveau_cut, shape_plan, shape_sides, shape_bottom)
                        VALUES
                          (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            id_sj,
                            request.form.get("negativ_typ"),
                            "ident_niveau_cut" in request.form,
                            request.form.get("shape_plan"),
                            request.form.get("shape_sides"),
                            request.form.get("shape_bottom"),
                        ),
                    )
                elif sj_typ == "structure":
                    cur.execute(
                        """
                        INSERT INTO tab_sj_structure
                          (id_structure, structure_typ, construction_typ, binder, basic_material, length_m, width_m, height_m)
                        VALUES
                          (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            id_sj,
                            request.form.get("structure_typ"),
                            request.form.get("construction_typ"),
                            request.form.get("binder"),
                            request.form.get("basic_material"),
                            float_or_none(request.form.get("length_m")),
                            float_or_none(request.form.get("width_m")),
                            float_or_none(request.form.get("height_m")),
                        ),
                    )
                else:
                    raise ValueError("Invalid type of stratigraphic unit.")

                # NEW: link SU to polygons (M:N)
                polygon_names = request.form.getlist("polygon_names")
                polygon_names = [(p or "").strip() for p in polygon_names if (p or "").strip()]
                if polygon_names:
                    sql_link = insert_sj_polygon_link_sql()
                    for poly_name in polygon_names:
                        # validate polygon exists (cheap and clear error)
                        cur.execute("SELECT 1 FROM tab_polygons WHERE polygon_name=%s;", (poly_name,))
                        if not cur.fetchone():
                            raise ValueError(f'Polygon "{poly_name}" does not exist.')
                        cur.execute(sql_link, (id_sj, poly_name))

                # Stratigraphic relations (store exactly as user says)
                # above_* means: current SU is above related SU -> relation '>'
                # below_* means: current SU is below related SU -> relation '<'
                relation_inputs = [
                    (">", request.form.get("above_1")),
                    (">", request.form.get("above_2")),
                    ("<", request.form.get("below_1")),
                    ("<", request.form.get("below_2")),
                    ("=", request.form.get("equal")),
                ]

                for rel, sj_str in relation_inputs:
                    sj_str = (sj_str or "").strip()
                    if not sj_str:
                        continue
                    try:
                        related_sj = int(sj_str)
                    except ValueError:
                        flash(
                            f"Invalid stratigraphic unit ID '{sj_str}' for relation '{rel}' — relation not saved.",
                            "warning",
                        )
                        continue

                    cur.execute(
                        """
                        INSERT INTO tab_sj_stratigraphy (ref_sj1, relation, ref_sj2)
                        VALUES (%s, %s, %s)
                        """,
                        (id_sj, rel, related_sj),
                    )

                conn.commit()
                flash(f"SU #{id_sj} has been saved.", "success")
                logger.info(f"[{selected_db}] SU saved id={id_sj} type={sj_typ}")

                return redirect(url_for("su.add_su"))

            except Exception as e:
                conn.rollback()
                flash(f"Error while saving SU: {e}", "danger")
                logger.error(f"[{selected_db}] add_su save error: {e}")
                form_data = request.form.to_dict(flat=True)

        return render_template(
            "add_su.html",
            selected_db=selected_db,
            suggested_id=suggested_id,
            authors=authors,
            polygons=polygons,
            su_for_media=su_for_media,
            sus=sus,
            sj_count_total=sj_count_total,
            sj_count_deposit=sj_count_deposit,
            sj_count_negativ=sj_count_negativ,
            sj_count_structure=sj_count_structure,
            form_data=form_data,
            open_edit_su_id=open_edit_su_id,
        )

    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


# -------------------------------------------------------------------
# SU: delete (with confirm modal in UI)
# -------------------------------------------------------------------
@su_bp.post("/su/delete")
@require_selected_db
def delete_su():
    selected_db = session["selected_db"]
    sj_id_raw = (request.form.get("id_sj") or "").strip()

    try:
        sj_id = int(sj_id_raw)
    except ValueError:
        flash("Invalid SU ID.", "warning")
        return redirect(url_for("su.add_su"))

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # 0) delete stratigraphy relations explicitly (no FK now)
            cur.execute(
                "DELETE FROM tab_sj_stratigraphy WHERE ref_sj1=%s OR ref_sj2=%s;",
                (sj_id, sj_id),
            )

            # 1) try delete base row
            try:
                cur.execute(delete_su_sql(), (sj_id,))
            except Exception:
                conn.rollback()
                with conn.cursor() as cur2:
                    # subtype tables might block if FK is not ON DELETE CASCADE
                    cur2.execute("DELETE FROM tab_sj_deposit WHERE id_deposit=%s;", (sj_id,))
                    cur2.execute("DELETE FROM tab_sj_negativ WHERE id_negativ=%s;", (sj_id,))
                    cur2.execute("DELETE FROM tab_sj_structure WHERE id_structure=%s;", (sj_id,))
                    # also ensure stratigraphy removed even after rollback
                    cur2.execute(
                        "DELETE FROM tab_sj_stratigraphy WHERE ref_sj1=%s OR ref_sj2=%s;",
                        (sj_id, sj_id),
                    )
                    cur2.execute(delete_su_sql(), (sj_id,))


        conn.commit()
        flash(f"SU #{sj_id} deleted.", "success")
        logger.info(f"[{selected_db}] SU deleted id={sj_id}")

    except Exception as e:
        conn.rollback()
        flash(f"Error while deleting SU: {e}", "danger")
        logger.error(f"[{selected_db}] SU delete error: {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("su.add_su"))


# -------------------------------------------------------------------
# SU: edit attributes
# -------------------------------------------------------------------
@su_bp.post("/su/edit")
@require_selected_db
def edit_su():
    selected_db = session["selected_db"]

    try:
        sj_id = int(request.form.get("id_sj") or "0")
        if sj_id <= 0:
            raise ValueError("Invalid SU ID.")

        sj_typ = (request.form.get("sj_typ") or "").strip().lower()
        if sj_typ not in {"deposit", "negativ", "structure"}:
            raise ValueError("Invalid type of stratigraphic unit.")

        recorded = _date_or_none(request.form.get("recorded"))
        description = request.form.get("description")
        interpretation = request.form.get("interpretation")
        author = request.form.get("author")
        docu_plan = "docu_plan" in request.form
        docu_vertical = "docu_vertical" in request.form
        excav_extent = _percent_or_none(request.form.get("excav_extent"))

        polygon_names = [
            (p or "").strip()
            for p in request.form.getlist("polygon_names")
            if (p or "").strip()
        ]
        above_ids = _su_id_list(request.form.get("above_ids"), sj_id)
        below_ids = _su_id_list(request.form.get("below_ids"), sj_id)
        equal_ids = _su_id_list(request.form.get("equal_ids"), sj_id)

    except Exception as e:
        flash(f"Invalid SU edit data: {e}", "warning")
        return redirect(url_for("su.add_su"))

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute(su_exists_sql(), (sj_id,))
            if not cur.fetchone():
                raise ValueError(f"SU #{sj_id} not found.")

            cur.execute(
                update_su_base_sql(),
                (
                    sj_typ,
                    description,
                    interpretation,
                    author,
                    recorded,
                    docu_plan,
                    docu_vertical,
                    excav_extent,
                    sj_id,
                ),
            )

            _save_su_subtype(cur, sj_id, sj_typ, request.form)

            cur.execute(delete_sj_polygon_links_sql(), (sj_id,))
            if polygon_names:
                cur.execute(list_polygon_names_sql())
                available_polygons = {r[0] for r in cur.fetchall()}
                missing = [p for p in polygon_names if p not in available_polygons]
                if missing:
                    raise ValueError("Unknown polygon(s): " + ", ".join(missing))

                insert_link_sql = insert_sj_polygon_link_sql()
                for polygon_name in polygon_names:
                    cur.execute(insert_link_sql, (sj_id, polygon_name))

            cur.execute(delete_sj_stratigraphy_links_sql(), (sj_id, sj_id))
            insert_relation_sql = insert_sj_stratigraphy_sql()
            for related_id in above_ids:
                cur.execute(insert_relation_sql, (sj_id, ">", related_id))
            for related_id in below_ids:
                cur.execute(insert_relation_sql, (sj_id, "<", related_id))
            for related_id in equal_ids:
                cur.execute(insert_relation_sql, (sj_id, "=", related_id))

        conn.commit()
        flash(f"SU #{sj_id} updated.", "success")
        logger.info(f"[{selected_db}] SU updated id={sj_id} type={sj_typ}")

    except Exception as e:
        conn.rollback()
        flash(f"Error while updating SU: {e}", "danger")
        logger.error(f"[{selected_db}] SU edit error: {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("su.add_su"))


# -------------------------------------------------------------------
# SU: media upload (Attach graphic documentation uses selected SU)
# -------------------------------------------------------------------
@su_bp.post("/su/<int:sj_id>/upload/<media_type>")
@require_selected_db
def upload_su_media(sj_id, media_type):
    selected_db = session["selected_db"]

    if media_type not in MEDIA_TABLES:
        flash("Invalid media type.", "danger")
        return redirect(request.referrer or url_for("su.add_su"))

    files = request.files.getlist("files")
    if not files:
        flash("No files provided.", "warning")
        return redirect(request.referrer or url_for("su.add_su"))

    # verify SU exists (clear error, avoids FS garbage)
    conn_chk = get_terrain_connection(selected_db)
    try:
        with conn_chk.cursor() as cur_chk:
            cur_chk.execute("SELECT 1 FROM tab_sj WHERE id_sj=%s;", (sj_id,))
            if not cur_chk.fetchone():
                flash(f"SU #{sj_id} not found.", "danger")
                return redirect(request.referrer or url_for("su.add_su"))
    finally:
        try:
            conn_chk.close()
        except Exception:
            pass

    meta_cols = MEDIA_TABLES[media_type]["extra_cols"]
    ok, failed = 0, []

    for f in files:
        tmp_path = None
        final_path = None
        thumb_path = None

        try:
            # 1) temporary storing
            tmp_path, _tmp_size = save_to_uploads(Config.UPLOAD_FOLDER, f)

            # 2) extension / pk
            pk_name = make_pk(selected_db, f.filename)  # e.g. "456_IMG_25.jpg"
            validate_pk(pk_name)
            ext = pk_name.rsplit(".", 1)[-1].lower()
            validate_extension(ext, Config.ALLOWED_EXTENSIONS)

            # 3) final storage + collision
            media_dir = Config.MEDIA_DIRS[media_type]
            final_path, thumb_path = final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)
            if os.path.exists(final_path):
                raise ValueError(f"File already exists: {pk_name}")

            # 4) move + mime + checksum + thumb
            move_into_place(tmp_path, final_path)
            tmp_path = None

            mime = detect_mime(final_path)
            validate_mime(mime, Config.ALLOWED_MIME)
            checksum = sha256_file(final_path)

            try:
                make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
            except Exception:
                pass

            # 5) EXIF (only photos JPEG/TIFF)
            shoot_dt = gps_lat = gps_lon = gps_alt = None
            exif_json = {}
            if media_type == "photos" and mime in ("image/jpeg", "image/tiff"):
                sdt, la, lo, al, exif = extract_exif(final_path)
                shoot_dt, gps_lat, gps_lon, gps_alt, exif_json = sdt, la, lo, al, exif

            # 6) insert into tab_<type> + link to tabaid_*
            t = MEDIA_TABLES[media_type]
            table, id_col = t["table"], t["id_col"]
            vals = [request.form.get(k) or None for k in meta_cols]

            conn = get_terrain_connection(selected_db)
            cur = conn.cursor()
            try:
                if media_type == "photos":
                    cur.execute(
                        f"""INSERT INTO {table}
                            ({id_col}, {", ".join(meta_cols)},
                             mime_type, file_size, checksum_sha256,
                             shoot_datetime, gps_lat, gps_lon, gps_alt, exif_json)
                           VALUES (%s, {", ".join(['%s']*len(meta_cols))}, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [
                            pk_name,
                            *vals,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                            shoot_dt,
                            gps_lat,
                            gps_lon,
                            gps_alt,
                            Json(exif_json),
                        ],
                    )
                else:
                    cur.execute(
                        f"""INSERT INTO {table}
                            ({id_col}, {", ".join(meta_cols)},
                             mime_type, file_size, checksum_sha256)
                           VALUES (%s, {", ".join(['%s']*len(meta_cols))}, %s, %s, %s)""",
                        [pk_name, *vals, mime, os.path.getsize(final_path), checksum],
                    )

                link = LINK_TABLES_SJ[media_type]
                cur.execute(
                    f"INSERT INTO {link['table']} ({link['fk_sj']}, {link['fk_media']}) VALUES (%s, %s)",
                    (sj_id, pk_name),
                )

                conn.commit()
                ok += 1

            except Exception:
                conn.rollback()
                # cleanup FS garbage if DB fails
                try:
                    delete_media_files(final_path, thumb_path)
                except Exception:
                    pass
                raise

            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            failed.append(f"{f.filename}: {e}")
            logger.warning(f"[{selected_db}] SU media upload failed ({media_type}) file={f.filename}: {e}")

        finally:
            if tmp_path:
                try:
                    cleanup_upload(tmp_path)
                except Exception:
                    pass

    if failed:
        flash(
            f"Uploaded {ok} file(s), {len(failed)} failed: " + "; ".join(failed),
            "warning" if ok else "danger",
        )
    else:
        flash(f"Uploaded {ok} file(s).", "success")

    logger.info(
        f"[{selected_db}] su-media upload: su={sj_id} type={media_type} ok={ok} failed={len(failed)}"
    )
    return redirect(request.referrer or url_for("su.add_su"))


@su_bp.post("/su/<int:sj_id>/unlink/<media_type>/<pk_name>")
@require_selected_db
def unlink_su_media(sj_id, media_type, pk_name):
    """
    Removes only M:N relation SU ↔ media (file and tab_<type> record remain).
    """
    selected_db = session["selected_db"]

    if media_type not in LINK_TABLES_SJ:
        flash("Invalid media type.", "danger")
        return redirect(request.referrer or url_for("su.add_su"))

    link = LINK_TABLES_SJ[media_type]
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()
    try:
        cur.execute(
            f"DELETE FROM {link['table']} WHERE {link['fk_sj']}=%s AND {link['fk_media']}=%s",
            (sj_id, pk_name),
        )
        conn.commit()
        flash("Link removed.", "success" if cur.rowcount else "warning")
    except Exception as e:
        conn.rollback()
        flash(f"Unlink failed: {e}", "danger")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    return redirect(request.referrer or url_for("su.add_su"))


# -------------------------------------------------------------------
# Harris Matrix (kept as-is; you can move it to a separate blueprint later)
# -------------------------------------------------------------------
@su_bp.route("/harrismatrix", methods=["GET", "POST"])
@require_selected_db
def harrismatrix():
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    try:
        cur.execute(count_sj_by_type_all())
        sj_type_counts = cur.fetchall()

        cur.execute(count_total_sj())
        total_sj_count = cur.fetchone()[0]

        cur.execute(count_objects())
        object_count = cur.fetchone()[0]

        cur.execute(count_sj_without_relation())
        sj_without_relation = cur.fetchone()[0]

    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    harris_image = session.get("harrismatrix_image")
    harris_links = _load_harris_links(selected_db, harris_image)

    return render_template(
        "harrismatrix.html",
        selected_db=selected_db,
        total_sj_count=total_sj_count,
        object_count=object_count,
        sj_without_relation=sj_without_relation,
        sj_type_counts=sj_type_counts,
        harris_image=harris_image,
        harris_links=harris_links,
    )


def _date_to_iso(value):
    return value.isoformat() if value else None


def _number_or_none(value):
    if value is None:
        return None
    return float(value) if hasattr(value, "__float__") else value


def _harris_su_payload(row):
    return {
        "id_sj": int(row[0]),
        "sj_typ": row[1],
        "description": row[2],
        "interpretation": row[3],
        "recorded": _date_to_iso(row[4]),
        "author": row[5],
        "docu_plan": bool(row[6]),
        "docu_vertical": bool(row[7]),
        "excav_extent": row[8],
        "ref_object": row[9],
        "deposit": {
            "deposit_typ": row[10],
            "color": row[11],
            "boundary_visibility": row[12],
            "structure": row[13],
            "compactness": row[14],
            "deposit_removed": row[15],
        },
        "negative": {
            "negativ_typ": row[16],
            "ident_niveau_cut": bool(row[17]),
            "shape_plan": row[18],
            "shape_sides": row[19],
            "shape_bottom": row[20],
        },
        "structure": {
            "structure_typ": row[21],
            "construction_typ": row[22],
            "binder": row[23],
            "basic_material": row[24],
            "length_m": _number_or_none(row[25]),
            "width_m": _number_or_none(row[26]),
            "height_m": _number_or_none(row[27]),
        },
        "polygon_names": list(row[28] or []),
        "above_ids": [int(v) for v in (row[29] or [])],
        "below_ids": [int(v) for v in (row[30] or [])],
        "equal_ids": [int(v) for v in (row[31] or [])],
    }


def _harris_object_payload(obj, inhum_grave):
    payload = {
        "id_object": int(obj[0]),
        "object_typ": obj[1],
        "superior_object": obj[2],
        "notes": obj[3],
        "sj_ids": [int(v) for v in (obj[4] or [])],
    }

    if inhum_grave:
        payload["inhum_grave"] = {
            "present": True,
            "preservation": inhum_grave[0],
            "orientation_dir": inhum_grave[1],
            "bone_map": inhum_grave[2],
            "notes_grave": inhum_grave[3],
            "anthropo_present": bool(inhum_grave[4]) if inhum_grave[4] is not None else False,
            "burial_box_type": inhum_grave[5],
        }
    else:
        payload["inhum_grave"] = {"present": False}

    return payload


@su_bp.get("/harrismatrix/api/su/<int:sj_id>")
@require_selected_db
def harrismatrix_su_detail(sj_id):
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(harris_su_detail_sql(), (sj_id,))
            row = cur.fetchone()
        if not row:
            return jsonify({"error": f"SU #{sj_id} not found."}), 404
        return jsonify(_harris_su_payload(row))
    finally:
        try:
            conn.close()
        except Exception:
            pass


@su_bp.get("/harrismatrix/api/object/<int:object_id>")
@require_selected_db
def harrismatrix_object_detail(object_id):
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        obj = q_get_object_with_sjs(conn, object_id)
        if not obj:
            return jsonify({"error": f"Object #{object_id} not found."}), 404
        inhum_grave = q_get_object_inhum_grave(conn, object_id)
        return jsonify(_harris_object_payload(obj, inhum_grave))
    finally:
        try:
            conn.close()
        except Exception:
            pass


class DSU:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # deterministic: lower ID is representative
        if ra < rb:
            self.parent[rb] = ra
        else:
            self.parent[ra] = rb


def _natural_node_key(node, label_map=None):
    label = str(label_map.get(node, node) if label_map else node)
    parts = []
    for part in re.split(r"(\d+)", label):
        if part.isdigit():
            parts.append((0, int(part)))
        elif part:
            parts.append((1, part))
    return parts


def _format_harris_cycle(cycle, label_map):
    if not cycle:
        return ""

    nodes = [edge[0] for edge in cycle]
    nodes.append(cycle[-1][1])
    return " -> ".join(label_map.get(node, str(node)) for node in nodes)


def _build_harris_matrix_data(rels, all_sj_rows):
    """Build a top-to-bottom Hasse graph from stored SU relations."""
    normalized_rels = []
    dsu = DSU()

    for raw_a, raw_rel, raw_b in rels:
        rel = (raw_rel or "").strip()
        if rel not in {">", "<", "="}:
            raise ValueError(f"Invalid stratigraphic relation: {raw_rel!r}")

        a, b = int(raw_a), int(raw_b)
        normalized_rels.append((a, rel, b))
        if rel == "=":
            dsu.union(a, b)

    all_sj = set()
    sj_type_map = {}
    for row in all_sj_rows:
        sj_id = int(row[0])
        all_sj.add(sj_id)
        sj_type_map[sj_id] = (row[1] or "").lower()

    related_sj = {node for a, _, b in normalized_rels for node in (a, b)}
    groups = {}
    for node in sorted(all_sj | related_sj):
        rep = dsu.find(node)
        groups.setdefault(rep, set()).add(node)

    label_map = {
        rep: "=".join(str(member) for member in sorted(members))
        for rep, members in sorted(groups.items())
    }
    node_type_map = {
        rep: _majority_su_type(members, sj_type_map)
        for rep, members in groups.items()
    }

    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(groups))

    for a, rel, b in normalized_rels:
        if rel == "=":
            continue

        u, v = dsu.find(a), dsu.find(b)
        if u == v:
            continue

        if rel == ">":
            graph.add_edge(u, v)
        else:
            graph.add_edge(v, u)

    if not nx.is_directed_acyclic_graph(graph):
        try:
            cycle = nx.find_cycle(graph, orientation="original")
        except nx.NetworkXNoCycle:
            cycle = []
        detail = _format_harris_cycle(cycle, label_map)
        message = "A cycle was found in stratigraphic relations."
        if detail:
            message = f"{message} Cycle: {detail}"
        raise ValueError(message)

    hasse_graph = transitive_reduction(graph)
    hasse_graph.add_nodes_from(graph.nodes)

    return hasse_graph, label_map, node_type_map, dsu


def _majority_su_type(members, sj_type_map):
    counts = Counter(
        sj_type_map.get(member, "")
        for member in sorted(members)
        if sj_type_map.get(member, "")
    )
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _color_or_default(value, default):
    color = (value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return color
    return default


def _harris_levels(graph):
    levels = {}
    for node in nx.topological_sort(graph):
        predecessors = list(graph.predecessors(node))
        levels[node] = max((levels[pred] + 1 for pred in predecessors), default=0)
    return levels


def _fallback_harris_layout(graph, label_map):
    if graph.number_of_nodes() == 0:
        return {}

    levels = _harris_levels(graph)
    nodes_by_level = defaultdict(list)
    for node, level in levels.items():
        nodes_by_level[level].append(node)
    for nodes in nodes_by_level.values():
        nodes.sort(key=lambda node: _natural_node_key(node, label_map))

    positions = {}
    x_spacing = 1.7
    y_spacing = 1.05

    for level in sorted(nodes_by_level):
        nodes = nodes_by_level[level]
        if level == min(nodes_by_level):
            row_width = len(nodes) - 1
            assigned = [
                (node, (index - row_width / 2) * x_spacing)
                for index, node in enumerate(nodes)
            ]
        else:
            groups_by_parent = defaultdict(list)
            for node in nodes:
                parents = tuple(
                    sorted(
                        graph.predecessors(node),
                        key=lambda pred: _natural_node_key(pred, label_map),
                    )
                )
                groups_by_parent[parents].append(node)

            assigned = []
            for parents, children in sorted(
                groups_by_parent.items(),
                key=lambda item: (
                    _parent_x(item[0], positions),
                    [_natural_node_key(node, label_map) for node in item[1]],
                ),
            ):
                base_x = _parent_x(parents, positions)
                width = len(children) - 1
                for index, node in enumerate(children):
                    assigned.append((node, base_x + (index - width / 2) * x_spacing))

            assigned = _separate_harris_level(assigned, x_spacing, label_map)

        for node, x in assigned:
            y = -level * y_spacing
            positions[node] = (x, y)

    return positions


def _parent_x(parents, positions):
    xs = [positions[parent][0] for parent in parents if parent in positions]
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _separate_harris_level(assigned, min_spacing, label_map):
    if len(assigned) < 2:
        return assigned

    ordered = sorted(
        assigned,
        key=lambda item: (item[1], _natural_node_key(item[0], label_map)),
    )
    original_center = sum(x for _, x in ordered) / len(ordered)
    separated = []
    previous_x = None
    for node, x in ordered:
        if previous_x is not None and x < previous_x + min_spacing:
            x = previous_x + min_spacing
        separated.append((node, x))
        previous_x = x

    new_center = sum(x for _, x in separated) / len(separated)
    shift = original_center - new_center
    return [(node, x + shift) for node, x in separated]


def _graphviz_harris_layout(graph, label_map):
    if graph.number_of_nodes() == 0:
        return {}

    dot_graph = nx.DiGraph()
    dot_graph.graph["graph"] = {
        "rankdir": "TB",
        "nodesep": "0.7",
        "ranksep": "0.55",
        "splines": "line",
    }
    dot_graph.graph["node"] = {
        "shape": "box",
        "fixedsize": "true",
        "width": "0.9",
        "height": "0.45",
    }

    for node in graph.nodes:
        dot_graph.add_node(node, label=label_map.get(node, str(node)))
    dot_graph.add_edges_from(graph.edges)

    try:
        raw_positions = nx.drawing.nx_pydot.graphviz_layout(dot_graph, prog="dot")
    except Exception as exc:
        logger.info(f"Graphviz Harris layout unavailable, using fallback layout: {exc}")
        return None

    if len(raw_positions) != graph.number_of_nodes():
        return None

    xs = [float(point[0]) for point in raw_positions.values()]
    center_x = (min(xs) + max(xs)) / 2
    scale = 72.0

    return {
        node: ((float(point[0]) - center_x) / scale, float(point[1]) / scale)
        for node, point in raw_positions.items()
    }


def _harris_matrix_layout(graph, label_map):
    positions = _graphviz_harris_layout(graph, label_map)
    if positions is not None:
        return positions
    return _fallback_harris_layout(graph, label_map)


def _harris_figure_size(positions):
    if not positions:
        return (6, 4)

    xs = [point[0] for point in positions.values()]
    ys = [point[1] for point in positions.values()]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    return (
        min(max(width * 1.6 + 3, 7), 18),
        min(max(height * 1.3 + 2.5, 5), 24),
    )


def _harris_object_boxes(positions, obj_rows, sj_obj_rows, dsu):
    obj_to_reps = {}
    for sj_id, obj_id in sj_obj_rows:
        if obj_id is None:
            continue
        rep = dsu.find(int(sj_id))
        obj_to_reps.setdefault(obj_id, set()).add(rep)

    boxes = []
    for oid, typ, _ in sorted(obj_rows, key=lambda row: row[0]):
        reps = [rep for rep in obj_to_reps.get(oid, set()) if rep in positions]
        if not reps:
            continue

        xs = [positions[rep][0] for rep in reps]
        ys = [positions[rep][1] for rep in reps]
        pad_x = 0.65
        pad_y = 0.45
        x0, x1 = min(xs) - pad_x, max(xs) + pad_x
        y0, y1 = min(ys) - pad_y, max(ys) + pad_y
        boxes.append(
            {
                "id": int(oid),
                "typ": typ or "",
                "x0": x0,
                "x1": x1,
                "y0": y0,
                "y1": y1,
                "label": f"Obj {oid}" + (f" ({typ})" if typ else ""),
            }
        )

    return boxes


def _draw_harris_object_boxes(ax, object_boxes):
    for box in object_boxes:
        rect = mpatches.FancyBboxPatch(
            (box["x0"], box["y0"]),
            box["x1"] - box["x0"],
            box["y1"] - box["y0"],
            boxstyle="round,pad=0.02,rounding_size=0.04",
            linewidth=1.0,
            edgecolor="#767676",
            facecolor="none",
            alpha=0.55,
            zorder=0,
        )
        ax.add_patch(rect)

        ax.text(
            box["x1"] - 0.05,
            box["y1"] - 0.05,
            box["label"],
            ha="right",
            va="top",
            fontsize=9,
            color="#333333",
            zorder=3,
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8),
        )


def _harris_node_box(label, x, y):
    width = max(0.82, 0.18 * len(label) + 0.48)
    height = 0.46
    return x - width / 2, y - height / 2, x + width / 2, y + height / 2


def _draw_harris_nodes(ax, positions, label_map, node_type_map, color_map):
    for node, (x, y) in positions.items():
        label = label_map.get(node, str(node))
        x0, y0, x1, y1 = _harris_node_box(label, x, y)
        node_type = node_type_map.get(node, "")

        rect = mpatches.Rectangle(
            (x0, y0),
            x1 - x0,
            y1 - y0,
            facecolor=color_map.get(node_type, "#E9E9E9"),
            edgecolor="#555555",
            linewidth=0.9,
            zorder=5,
        )
        ax.add_patch(rect)
        ax.text(
            x,
            y,
            label,
            ha="center",
            va="center",
            fontsize=10,
            color="#1f1f1f",
            zorder=6,
        )


def _harris_label_ids(label):
    ids = []
    seen = set()
    for token in re.findall(r"\d+", str(label)):
        value = int(token)
        if value not in seen:
            ids.append(value)
            seen.add(value)
    return ids


def _pct_bbox(ax, fig, x0, y0, x1, y1):
    fig_width, fig_height = fig.canvas.get_width_height()
    p0 = ax.transData.transform((x0, y0))
    p1 = ax.transData.transform((x1, y1))

    left_px = max(0.0, min(p0[0], p1[0]))
    right_px = min(float(fig_width), max(p0[0], p1[0]))
    bottom_px = max(0.0, min(p0[1], p1[1]))
    top_px = min(float(fig_height), max(p0[1], p1[1]))

    if right_px <= left_px or top_px <= bottom_px:
        return None

    return {
        "left": round((left_px / fig_width) * 100, 4),
        "top": round(((fig_height - top_px) / fig_height) * 100, 4),
        "width": round(((right_px - left_px) / fig_width) * 100, 4),
        "height": round(((top_px - bottom_px) / fig_height) * 100, 4),
    }


def _harris_click_areas(ax, fig, positions, label_map, object_boxes):
    areas = []
    fig.canvas.draw()

    for node, (x, y) in positions.items():
        label = label_map.get(node, str(node))
        bbox = _harris_node_box(label, x, y)
        pct = _pct_bbox(ax, fig, *bbox)
        ids = _harris_label_ids(label)
        if not pct or not ids:
            continue
        areas.append(
            {
                **pct,
                "kind": "su",
                "id": ids[0],
                "ids": ids,
                "label": label,
            }
        )

    for box in object_boxes:
        pct = _pct_bbox(ax, fig, box["x0"], box["y0"], box["x1"], box["y1"])
        if not pct:
            continue
        areas.append(
            {
                **pct,
                "kind": "object",
                "id": box["id"],
                "ids": [box["id"]],
                "label": box["label"],
            }
        )

    return areas


def _save_harris_matrix_image(
    graph,
    positions,
    label_map,
    node_type_map,
    color_map,
    filepath,
    *,
    draw_objects=False,
    obj_rows=None,
    sj_obj_rows=None,
    dsu=None,
):
    fig, ax = plt.subplots(figsize=_harris_figure_size(positions))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.axis("off")

    object_boxes = []
    if draw_objects and obj_rows and sj_obj_rows and dsu:
        object_boxes = _harris_object_boxes(positions, obj_rows, sj_obj_rows, dsu)
        _draw_harris_object_boxes(ax, object_boxes)

    for source, target in graph.edges:
        x0, y0 = positions[source]
        x1, y1 = positions[target]
        ax.plot([x0, x1], [y0, y1], color="#202020", linewidth=1.2, zorder=1)

    _draw_harris_nodes(ax, positions, label_map, node_type_map, color_map)

    if positions:
        xs = [point[0] for point in positions.values()]
        ys = [point[1] for point in positions.values()]
        ax.set_xlim(min(xs) - 1.0, max(xs) + 1.0)
        ax.set_ylim(min(ys) - 0.8, max(ys) + 0.8)
        ax.set_aspect("equal", adjustable="box")

    fig.subplots_adjust(left=0.03, right=0.97, top=0.97, bottom=0.03)
    click_areas = _harris_click_areas(ax, fig, positions, label_map, object_boxes)

    fig.savefig(filepath, format="png", dpi=180)
    plt.close(fig)
    return click_areas


@su_bp.route("/generate-harrismatrix", methods=["POST"])
@require_selected_db
def generate_harrismatrix():
    selected_db = session.get("selected_db")
    if not selected_db:
        flash("No terrain DB selected.", "danger")
        return redirect(url_for("su.harrismatrix"))

    color_map = {
        "deposit": _color_or_default(request.form.get("deposit_color"), "#ADD8E6"),
        "negativ": _color_or_default(request.form.get("negative_color"), "#90EE90"),
        "negative": _color_or_default(request.form.get("negative_color"), "#90EE90"),
        "structure": _color_or_default(request.form.get("structure_color"), "#FFD700"),
    }
    draw_objects = bool(request.form.get("draw_objects"))

    conn = None
    try:
        conn = get_terrain_connection(selected_db)

        rels = fetch_stratigraphy_relations(conn)
        all_sj_rows = get_all_sj_with_types(conn)
        harris_graph, label_map, node_type_map, dsu = _build_harris_matrix_data(
            rels,
            all_sj_rows,
        )

        if harris_graph.number_of_nodes() == 0:
            flash("No stratigraphic units found.", "warning")
            return redirect(url_for("su.harrismatrix"))

        positions = _harris_matrix_layout(harris_graph, label_map)
        obj_rows = []
        sj_obj_rows = []
        if draw_objects:
            obj_rows = get_all_objects(conn)
            sj_obj_rows = get_sj_with_object_refs(conn)

        images_dir, _ = get_hmatrix_dirs(selected_db)
        os.makedirs(images_dir, exist_ok=True)
        filename = f"{selected_db}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(images_dir, filename)
        click_areas = _save_harris_matrix_image(
            harris_graph,
            positions,
            label_map,
            node_type_map,
            color_map,
            filepath,
            draw_objects=draw_objects,
            obj_rows=obj_rows,
            sj_obj_rows=sj_obj_rows,
            dsu=dsu,
        )

        session["harrismatrix_image"] = filename
        session.pop("harrismatrix_links", None)
        _save_harris_links(images_dir, filename, click_areas)
        flash("Harris Matrix was generated.", "success")
        return redirect(url_for("su.harrismatrix"))

    except ValueError as e:
        logger.warning(f"[{selected_db}] Invalid Harris Matrix data: {e}")
        flash(str(e), "danger")
        return redirect(url_for("su.harrismatrix"))
    except Exception as e:
        logger.error(f"[{selected_db}] Error while generating Harris Matrix: {e}")
        flash(f"Error while generating Harris Matrix: {str(e)}", "danger")
        return redirect(url_for("su.harrismatrix"))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@su_bp.route("/harrismatrix/img/<path:filename>")
@require_selected_db
def harrismatrix_image(filename):
    selected_db = session.get("selected_db")
    images_dir, _ = get_hmatrix_dirs(selected_db)
    return send_from_directory(images_dir, filename)
