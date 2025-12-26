# app/routes/sections.py
# logic for archeological sections (profiles)

import os
from psycopg2.extras import Json

from flask import Blueprint, request, render_template, redirect, url_for, flash, session

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db
from app.utils import storage
from app.utils.validators import validate_extension, validate_mime, sha256_file
from app.utils.images import detect_mime, make_thumbnail, extract_exif

# SQLs from app/queries.py (add these helpers as shown below)
from app.queries import (
    # listing
    get_sections_list_sql, list_authors_sql, list_sj_ids_sql,

    # manual create + bindings
    upsert_section_manual_sql,
    delete_section_geopts_bindings_sql,
    insert_section_geopts_binding_sql,
    delete_section_sj_links_sql,
    insert_section_sj_link_sql,

    # existence + media insert + links
    section_exists_sql,
    insert_photo_sql, insert_sketch_sql, insert_photogram_sql, insert_drawing_sql,
    link_section_photo_sql, link_section_sketch_sql, link_section_photogram_sql, link_section_drawing_sql
)

sections_bp = Blueprint("sections", __name__)

MEDIA_DIRS = Config.MEDIA_DIRS
ALLOWED_EXT = Config.ALLOWED_EXTENSIONS
ALLOWED_MIME = Config.ALLOWED_MIME

# Local mapping for SECTION ↔ media (similar idea as polygons)
SUPPORTED_SECTION_MEDIA = {"photos", "sketches", "photograms", "drawings"}


# ---------- helpers ----------
def _prep_ranges(arr_from, arr_to):
    """Validate and normalize ranges; returns list[(int from, int to)]."""
    out = []
    for f, t in zip(arr_from, arr_to):
        f = (f or "").strip()
        t = (t or "").strip()
        if not f and not t:
            continue
        if not f or not t:
            raise ValueError("Each range row must have BOTH FROM and TO.")
        f_i = int(f)
        t_i = int(t)
        if f_i > t_i:
            raise ValueError(f"Invalid range: {f_i} > {t_i}.")
        out.append((f_i, t_i))
    return out


def _parse_int_list(values):
    out = []
    for v in values:
        v = (v or "").strip()
        if not v:
            continue
        out.append(int(v))
    return out


# ---------- LIST + FORM PAGE ----------
@sections_bp.route("/sections", methods=["GET"])
@require_selected_db
def sections():
    selected_db = session.get("selected_db")

    conn = get_terrain_connection(selected_db)
    sections_rows = []
    authors = []
    sj_ids = []
    try:
        with conn.cursor() as cur:
            cur.execute(get_sections_list_sql())
            sections_rows = [
                {
                    "id": r[0],
                    "type": r[1],
                    "description": r[2],
                    "ranges_nr": r[3],
                    "sj_nr": r[4],
                }
                for r in cur.fetchall()
            ]

            cur.execute(list_authors_sql())
            authors = [r[0] for r in cur.fetchall()]

            cur.execute(list_sj_ids_sql())
            sj_ids = [r[0] for r in cur.fetchall()]

    except Exception as e:
        logger.error(f"[{selected_db}] list sections error: {e}")
        flash("Error while loading sections list.", "danger")
    finally:
        conn.close()

    return render_template(
        "sections.html",
        selected_db=selected_db,
        sections=sections_rows,
        authors=authors,
        sj_ids=sj_ids,
    )


# ---------- MANUAL SECTION CREATE (id + type + description + point ranges + SJ links) ----------
@sections_bp.route("/sections/new-manual", methods=["POST"])
@require_selected_db
def new_section_manual():
    selected_db = session.get("selected_db")

    id_section_raw = (request.form.get("id_section") or "").strip()
    section_type = (request.form.get("section_type") or "").strip()
    description = (request.form.get("description") or "").strip()

    # point ranges
    pts_from = request.form.getlist("range_from[]")
    pts_to = request.form.getlist("range_to[]")

    # optional SJ bindings (M:N)
    sj_list_raw = request.form.getlist("ref_sj[]")

    try:
        if not id_section_raw:
            raise ValueError("Section ID is required.")
        id_section = int(id_section_raw)

        allowed_types = {"standard", "cumulative", "synthetic", "other"}
        if section_type not in allowed_types:
            raise ValueError("Invalid section type.")

        ranges = _prep_ranges(pts_from, pts_to)
        if not ranges:
            raise ValueError("Provide at least one range of points (FROM–TO).")

        sj_ids = _parse_int_list(sj_list_raw)

        conn = get_terrain_connection(selected_db)
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                # 1) upsert section metadata
                cur.execute(upsert_section_manual_sql(), (id_section, section_type, description))

                # 2) replace geopts bindings idempotently
                cur.execute(delete_section_geopts_bindings_sql(), (id_section,))
                for f_i, t_i in ranges:
                    cur.execute(insert_section_geopts_binding_sql(), (id_section, f_i, t_i))

                # 3) replace SJ links (optional)
                cur.execute(delete_section_sj_links_sql(), (id_section,))
                for sj in sj_ids:
                    cur.execute(insert_section_sj_link_sql(), (sj, id_section))

            conn.commit()
            flash(f'Section "{id_section}" saved.', "success")
            logger.info(
                f'[{selected_db}] section "{id_section}" saved: '
                f"type={section_type}, ranges={len(ranges)}, sj_links={len(sj_ids)}"
            )

        except Exception as e:
            conn.rollback()
            logger.error(f"[{selected_db}] manual section create error: {e}")
            flash(f"Error while saving section: {e}", "danger")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    except ValueError as ve:
        flash(str(ve), "warning")
    except Exception as e:
        flash(f"Unexpected error: {e}", "danger")

    return redirect(url_for("sections.sections"))


# ---------- DELETE SECTION ----------
@sections_bp.route("/sections/delete", methods=["POST"])
@require_selected_db
def delete_section():
    selected_db = session.get("selected_db")
    id_section_raw = (request.form.get("id_section") or "").strip()

    if not id_section_raw:
        flash("Missing section id.", "warning")
        return redirect(url_for("sections.sections"))

    try:
        id_section = int(id_section_raw)
    except ValueError:
        flash("Invalid section id.", "warning")
        return redirect(url_for("sections.sections"))

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tab_section WHERE id_section = %s;", (id_section,))
        conn.commit()
        flash(f'Section "{id_section}" deleted.', "success")
        logger.info(f'[{selected_db}] section "{id_section}" deleted.')
    except Exception as e:
        conn.rollback()
        logger.error(f"[{selected_db}] section delete error: {e}")
        flash(f"Error while deleting section: {e}", "danger")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("sections.sections"))


# ---------- GRAPHIC MEDIA FOR SECTIONS ----------
@sections_bp.post("/sections/upload/<media_type>")
@require_selected_db
def upload_section_media(media_type):
    selected_db = session["selected_db"]

    if media_type not in SUPPORTED_SECTION_MEDIA:
        flash("Invalid media type.", "danger")
        return redirect(url_for("sections.sections"))

    id_section_raw = (request.form.get("id_section") or "").strip()
    if not id_section_raw:
        flash("You must select a section first.", "warning")
        return redirect(url_for("sections.sections"))

    try:
        id_section = int(id_section_raw)
    except ValueError:
        flash("Invalid section id.", "danger")
        return redirect(url_for("sections.sections"))

    files = request.files.getlist("files")
    if not files:
        flash("No files provided.", "warning")
        return redirect(url_for("sections.sections"))

    # verify section exists
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(section_exists_sql(), (id_section,))
            if not cur.fetchone():
                flash(f'Section "{id_section}" not found.', "danger")
                return redirect(url_for("sections.sections"))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    notes = (request.form.get("notes") or "").strip() or None

    # shared metadata per type
    if media_type == "photos":
        photo_typ = (request.form.get("photo_typ") or "").strip()
        datum = (request.form.get("datum") or "").strip() or None
        author = (request.form.get("author") or "").strip() or None
    elif media_type == "sketches":
        sketch_typ = (request.form.get("sketch_typ") or "").strip()
        author = (request.form.get("author") or "").strip() or None
        datum = (request.form.get("datum") or "").strip() or None
    elif media_type == "photograms":
        photogram_typ = (request.form.get("photogram_typ") or "").strip()
    else:  # drawings
        drawing_typ = (request.form.get("drawing_typ") or "").strip()
        author = (request.form.get("author") or "").strip() or None
        datum = (request.form.get("datum") or "").strip() or None

    ok, failed = 0, []

    for f in files:
        tmp_path = None
        final_path = None
        thumb_path = None

        try:
            # A) temp store
            tmp_path, _tmp_size = storage.save_to_uploads(Config.UPLOAD_FOLDER, f)

            # B) pk + ext validation
            pk_name = storage.make_pk(selected_db, f.filename)
            storage.validate_pk(pk_name)
            ext = pk_name.rsplit(".", 1)[-1].lower()
            validate_extension(ext, ALLOWED_EXT)

            # C) final paths + collision
            media_dir = MEDIA_DIRS[media_type]
            final_path, thumb_path = storage.final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)
            if os.path.exists(final_path):
                raise ValueError(f"File already exists: {pk_name}")

            # D) move into place then MIME validate
            storage.move_into_place(tmp_path, final_path)
            tmp_path = None

            mime = detect_mime(final_path)
            validate_mime(mime, ALLOWED_MIME)
            checksum = sha256_file(final_path)

            # thumb best-effort
            try:
                make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
            except Exception:
                pass

            # EXIF for photos only
            shoot_dt = gps_lat = gps_lon = gps_alt = None
            exif_json = {}
            if media_type == "photos" and mime in ("image/jpeg", "image/tiff"):
                sdt, la, lo, al, exif = extract_exif(final_path)
                shoot_dt, gps_lat, gps_lon, gps_alt, exif_json = sdt, la, lo, al, exif

            # E) DB insert + link (commit per file)
            conn2 = get_terrain_connection(selected_db)
            cur2 = conn2.cursor()
            try:
                if media_type == "photos":
                    cur2.execute(
                        insert_photo_sql(),
                        (
                            pk_name,
                            photo_typ or "",
                            datum,
                            author,
                            notes,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                            shoot_dt, gps_lat, gps_lon, gps_alt,
                            Json(exif_json),
                        ),
                    )
                    cur2.execute(link_section_photo_sql(), (id_section, pk_name))

                elif media_type == "sketches":
                    cur2.execute(
                        insert_sketch_sql(),
                        (
                            pk_name,
                            sketch_typ or "",
                            author,
                            datum,
                            notes,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                        ),
                    )
                    cur2.execute(link_section_sketch_sql(), (id_section, pk_name))

                elif media_type == "photograms":
                    cur2.execute(
                        insert_photogram_sql(),
                        (
                            pk_name,
                            photogram_typ or "",
                            notes,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                        ),
                    )
                    cur2.execute(link_section_photogram_sql(), (id_section, pk_name))

                else:  # drawings
                    cur2.execute(
                        insert_drawing_sql(),
                        (
                            pk_name,
                            drawing_typ or "",
                            author,
                            datum,
                            notes,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                        ),
                    )
                    cur2.execute(link_section_drawing_sql(), (id_section, pk_name))

                conn2.commit()
                ok += 1

            except Exception:
                conn2.rollback()
                try:
                    storage.delete_media_files(final_path, thumb_path)
                except Exception:
                    pass
                raise

            finally:
                try:
                    cur2.close()
                except Exception:
                    pass
                try:
                    conn2.close()
                except Exception:
                    pass

        except Exception as e:
            failed.append(f"{f.filename}: {e}")
            logger.warning(f"[{selected_db}] section media upload failed ({media_type}) {f.filename}: {e}")

        finally:
            if tmp_path:
                try:
                    storage.cleanup_upload(tmp_path)
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
        f"[{selected_db}] section-media upload: section={id_section} type={media_type} ok={ok} failed={len(failed)}"
    )
    return redirect(url_for("sections.sections"))
