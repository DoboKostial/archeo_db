# app/routes/sections.py
# logic for archeological sections (profiles)

import os
from psycopg2.extras import Json
from io import BytesIO
import json
import zipfile
import shapefile

from flask import Blueprint, request, render_template, redirect, url_for, flash, session, send_file

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db
from app.utils import storage
from app.utils.validators import validate_extension, validate_mime, sha256_file
from app.utils.images import detect_mime, make_thumbnail, extract_exif

from app.utils.media_map import MEDIA_TABLES, LINK_TABLES_SECTION

from app.queries import (
    # list page data
    get_sections_list_sql,
    list_authors_sql,
    list_sj_ids_sql,

    # section + bindings
    upsert_section_manual_sql,
    delete_section_geopts_bindings_sql,
    insert_section_geopts_binding_sql,
    delete_section_sj_links_sql,
    insert_section_sj_link_sql,
    select_sections_with_bindings_sql,
    section_line_geojson_by_id_sql,
    find_geopts_srid_sql,
    srtext_by_srid_sql,
    sections_lines_geojson_sql,

    # existence
    section_exists_sql,
)

sections_bp = Blueprint("sections", __name__)

MEDIA_DIRS = Config.MEDIA_DIRS
ALLOWED_EXT = Config.ALLOWED_EXTENSIONS
ALLOWED_MIME = Config.ALLOWED_MIME

SUPPORTED_SECTION_MEDIA = set(LINK_TABLES_SECTION.keys())


# -------------------------
# Helpers
# -------------------------
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


def _require_fields(media_type: str, form) -> None:
    """
    Validates required form fields per media type
    according to your DB NOT NULL constraints.
    """
    required = {
        "photos": ["photo_typ", "datum", "author"],
        "sketches": ["sketch_typ", "author"],
        "drawings": ["author", "datum"],
        "photograms": ["photogram_typ"],
    }.get(media_type, [])

    missing = [k for k in required if not (form.get(k) or "").strip()]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def _build_insert_sql_and_vals(media_type: str, pk_name: str, mime: str, file_size: int, checksum: str, form, final_path: str):
    """
    Builds INSERT statement for a media row using MEDIA_TABLES mapping.
    Adds photo-specific computed metadata (EXIF/GPS) for tab_photos.
    Returns: (sql, vals)
    """
    m = MEDIA_TABLES[media_type]
    table = m["table"]
    id_col = m["id_col"]
    extra_cols = m.get("extra_cols", [])

    cols = [id_col] + extra_cols + ["mime_type", "file_size", "checksum_sha256"]
    vals = [pk_name]

    # extra cols from form (in map order)
    for c in extra_cols:
        vals.append((form.get(c) or "").strip() or None)

    # common
    vals += [mime, file_size, checksum]

    # Photo-only: add computed EXIF / GPS / shoot_datetime if available
    # Your tab_photos allows these to be NULL; exif_json has default, but we store it if we can.
    if media_type == "photos":
        shoot_dt = gps_lat = gps_lon = gps_alt = None
        exif_json = {}
        try:
            # If your extractor supports TIFF/JPEG, it will fill these.
            # If it fails, we keep NULLs.
            sdt, la, lo, al, exif = extract_exif(final_path)
            shoot_dt, gps_lat, gps_lon, gps_alt, exif_json = sdt, la, lo, al, (exif or {})
        except Exception:
            pass

        cols += ["shoot_datetime", "gps_lat", "gps_lon", "gps_alt", "exif_json"]
        vals += [shoot_dt, gps_lat, gps_lon, gps_alt, Json(exif_json)]

    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders});"
    return sql, vals


def _build_link_sql(media_type: str):
    """
    Builds INSERT statement for link table row using LINK_TABLES_SECTION mapping.
    Returns: (sql, fk_section_col, fk_media_col)
    """
    link = LINK_TABLES_SECTION[media_type]
    link_table = link["table"]
    fk_media = link["fk_media"]
    fk_section = link["fk_section"]

    sql = f"INSERT INTO {link_table} ({fk_section}, {fk_media}) VALUES (%s, %s);"
    return sql, fk_section, fk_media


# -------------------------
# LIST + FORM PAGE
# -------------------------
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


# -------------------------
# MANUAL SECTION CREATE
# -------------------------
@sections_bp.route("/sections/new-manual", methods=["POST"])
@require_selected_db
def new_section_manual():
    selected_db = session.get("selected_db")

    id_section_raw = (request.form.get("id_section") or "").strip()
    section_type = (request.form.get("section_type") or "").strip()
    description = (request.form.get("description") or "").strip()

    pts_from = request.form.getlist("range_from[]")
    pts_to = request.form.getlist("range_to[]")
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
                # 1) upsert section
                cur.execute(upsert_section_manual_sql(), (id_section, section_type, description))

                # 2) replace geopts bindings
                cur.execute(delete_section_geopts_bindings_sql(), (id_section,))
                for f_i, t_i in ranges:
                    cur.execute(insert_section_geopts_binding_sql(), (id_section, f_i, t_i))

                # 3) replace SJ links
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


# -------------------------
# DELETE SECTION
# -------------------------
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


# -------------------------
# GRAPHIC DOCUMENTATION (UPLOAD)
# Uses media_map.py: MEDIA_TABLES + LINK_TABLES_SECTION
# -------------------------
@sections_bp.post("/sections/upload/<media_type>")
@require_selected_db
def upload_section_media(media_type):
    selected_db = session.get("selected_db")

    if media_type not in SUPPORTED_SECTION_MEDIA or media_type not in MEDIA_TABLES:
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

    # Validate required metadata for this media type
    try:
        _require_fields(media_type, request.form)
    except ValueError as ve:
        flash(str(ve), "warning")
        return redirect(url_for("sections.sections"))

    # Verify section exists
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

    ok, failed = 0, []

    for f in files:
        tmp_path = None
        final_path = None
        thumb_path = None

        try:
            # 1) temp store
            tmp_path, _tmp_size = storage.save_to_uploads(Config.UPLOAD_FOLDER, f)

            # 2) PK + extension validation
            pk_name = storage.make_pk(selected_db, f.filename)
            storage.validate_pk(pk_name)
            ext = pk_name.rsplit(".", 1)[-1].lower()
            validate_extension(ext, ALLOWED_EXT)

            # 3) final paths + collision
            media_dir = MEDIA_DIRS[media_type]
            final_path, thumb_path = storage.final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)
            if os.path.exists(final_path):
                raise ValueError(f"File already exists: {pk_name}")

            # 4) move into place then MIME validate
            storage.move_into_place(tmp_path, final_path)
            tmp_path = None

            mime = detect_mime(final_path)
            validate_mime(mime, ALLOWED_MIME)
            checksum = sha256_file(final_path)

            # 5) thumbnail best-effort
            try:
                make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
            except Exception:
                pass

            # 6) DB insert + link (transaction per file)
            file_size = os.path.getsize(final_path)

            sql_ins, vals_ins = _build_insert_sql_and_vals(
                media_type=media_type,
                pk_name=pk_name,
                mime=mime,
                file_size=file_size,
                checksum=checksum,
                form=request.form,
                final_path=final_path,
            )

            sql_link, _fk_section, _fk_media = _build_link_sql(media_type)

            conn2 = get_terrain_connection(selected_db)
            conn2.autocommit = False
            try:
                with conn2.cursor() as cur2:
                    cur2.execute(sql_ins, vals_ins)
                    cur2.execute(sql_link, (id_section, pk_name))
                conn2.commit()
                ok += 1
            except Exception:
                conn2.rollback()
                # cleanup file if DB failed
                try:
                    storage.delete_media_files(final_path, thumb_path)
                except Exception:
                    pass
                raise
            finally:
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

    logger.info(f"[{selected_db}] section-media upload: section={id_section} type={media_type} ok={ok} failed={len(failed)}")
    return redirect(url_for("sections.sections"))


# -------------------------
# Geo routines for sections - validation and SHP creation
# -------------------------
## Rebuilds Polyline geometry for section/cut. Actualy it only validates while its not stored
@sections_bp.route("/sections/rebuild-all", methods=["POST"])
@require_selected_db
def rebuild_all_sections():
    selected_db = session.get("selected_db")
    conn = get_terrain_connection(selected_db)

    validated = 0
    skipped = 0

    try:
        with conn.cursor() as cur:
            cur.execute(select_sections_with_bindings_sql())
            ids = [r[0] for r in cur.fetchall()]

            for sid in ids:
                cur.execute(section_line_geojson_by_id_sql(), (sid,))
                gj = (cur.fetchone() or [None])[0]
                if gj:
                    validated += 1
                else:
                    skipped += 1

        conn.commit()
        flash(
            f"Geometry validated for {validated} section(s). "
            f"Skipped {skipped} (not enough points).",
            "success" if validated else "warning",
        )
        logger.info(f"[{selected_db}] sections validate: ok={validated} skipped={skipped}")
    except Exception as e:
        conn.rollback()
        logger.error(f"[{selected_db}] sections rebuild-all/validate error: {e}")
        flash(f"Error during geometry validation: {e}", "danger")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("sections.sections"))

## This constructs SHP and provide it for donwload
@sections_bp.route("/download-sections")
@require_selected_db
def download_sections():
    selected_db = session.get("selected_db")
    conn = get_terrain_connection(selected_db)

    try:
        with conn.cursor() as cur:
            # SRID + PRJ from tab_geopts geometry typmod
            cur.execute(find_geopts_srid_sql())
            srid = (cur.fetchone() or [None])[0]

            prj_wkt = ""
            if srid:
                cur.execute(srtext_by_srid_sql(), (srid,))
                prj_wkt = (cur.fetchone() or [""])[0] or ""

            # all lines (GeoJSON)
            cur.execute(sections_lines_geojson_sql())
            results = cur.fetchall()  # (id_section, line_gj)

        # Build SHP in-memory
        shp_io = BytesIO()
        shx_io = BytesIO()
        dbf_io = BytesIO()

        with shapefile.Writer(shp=shp_io, shx=shx_io, dbf=dbf_io, shapeType=shapefile.POLYLINE) as shp:
            shp.field("id", "N", decimal=0)

            for sid, line_gj in results:
                if not line_gj:
                    continue
                gj = json.loads(line_gj)
                gtype = gj.get("type")

                if gtype == "LineString":
                    coords = gj.get("coordinates") or []
                    pts = [(float(x), float(y)) for x, y in coords]
                    if len(pts) < 2:
                        continue
                    shp.line([pts])   # one-part polyline
                    shp.record(int(sid))

                elif gtype == "MultiLineString":
                    # write each part as a separate shape record with same id
                    for coords in gj.get("coordinates", []):
                        pts = [(float(x), float(y)) for x, y in coords]
                        if len(pts) < 2:
                            continue
                        shp.line([pts])
                        shp.record(int(sid))

                # else: ignore unsupported types silently

        # Zip outputs (+ .prj)
        zip_io = BytesIO()
        with zipfile.ZipFile(zip_io, "w") as zipf:
            base = f"{selected_db}_sections"
            zipf.writestr(f"{base}.shp", shp_io.getvalue())
            zipf.writestr(f"{base}.shx", shx_io.getvalue())
            zipf.writestr(f"{base}.dbf", dbf_io.getvalue())
            if prj_wkt:
                zipf.writestr(f"{base}.prj", prj_wkt)

        zip_io.seek(0)
        return send_file(
            zip_io,
            mimetype="application/zip",
            download_name=f"{selected_db}_sections.zip",
            as_attachment=True,
        )

    except Exception as e:
        logger.error(f"[{selected_db}] sections SHP export error: {e}")
        flash(f"Error while generating SHP: {e}", "danger")
        return redirect(url_for("sections.sections"))
    finally:
        try:
            conn.close()
        except Exception:
            pass