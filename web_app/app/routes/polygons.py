# app/routes/polygons.py
# logic for archeological polygons

from io import BytesIO
import os
from psycopg2.extras import Json
import json
import zipfile
import shapefile  # pyshp

from flask import Blueprint, request, render_template, redirect, url_for, flash, session, send_file, jsonify

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db
from app.utils.geom_utils import process_polygon_upload
from app.utils import storage
from app.utils.validators import validate_extension, validate_mime, sha256_file
from app.utils.images import detect_mime, make_thumbnail, extract_exif

# SQLs from app/queries.py
from app.queries import (
    insert_polygon_manual_sql, delete_bindings_top_sql, delete_bindings_bottom_sql,
    insert_binding_top_sql, insert_binding_bottom_sql, rebuild_geom_sql, select_polygons_with_bindings_sql,
    srtext_by_srid_sql, get_polygons_list, list_authors_sql, find_geopts_srid_sql, upsert_geopt_sql, 
    polygon_geoms_geojson_sql, find_polygons_srid_sql, polygons_geojson_top_bottom_sql, srtext_by_srid_sql, get_polygon_parent_sql, reparent_children_sql, delete_polygon_sql,
    polygon_exists_sql, insert_photo_sql, insert_sketch_sql, insert_photogram_sql, link_polygon_photo_sql, link_polygon_sketch_sql, link_polygon_photogram_sql
)


polygons_bp = Blueprint('polygons', __name__)

# Local mapping for polygon↔media link tables (so we don't touch media_map.py)
from app.utils.media_map import MEDIA_TABLES, LINK_TABLES_POLYGON

MEDIA_DIRS = Config.MEDIA_DIRS  # {"photos": "photos", ...}
ALLOWED_EXT = Config.ALLOWED_EXTENSIONS
ALLOWED_MIME = Config.ALLOWED_MIME


# ---------- LIST + FORM PAGE ----------
@polygons_bp.route('/polygons', methods=['GET'])
@require_selected_db
def polygons():
    selected_db = session.get('selected_db')

    # list polygons
    conn = get_terrain_connection(selected_db)
    polys = []
    authors = []
    try:
        with conn.cursor() as cur:
            cur.execute(get_polygons_list())
            polys = [
                {"id": row[0], "name": row[1], "points": row[2], "srid": row[3], "parent": row[4], "allocation_reason": row[5], "has_top": row[6], "has_bottom": row[7]}
                for row in cur.fetchall()
            ]
            cur.execute(list_authors_sql())
            authors = [r[0] for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"[{selected_db}] list polygons error: {e}")
        flash('Error while loading polygons list.', 'danger')
    finally:
        conn.close()

    return render_template('polygons.html', polygons=polys, selected_db=selected_db, authors=authors)


# ---------- MANUAL POLYGON CREATE (ID + name + ranges) ----------

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
        f_i = int(f); t_i = int(t)
        if f_i > t_i:
            raise ValueError(f"Invalid range: {f_i} > {t_i}.")
        out.append((f_i, t_i))
    return out


# ---------- MANUAL POLYGON CREATE (name + allocation + TOP/BOTTOM ranges) ----------
@polygons_bp.route('/polygons/new-manual', methods=['POST'])
@require_selected_db
def new_polygon_manual():
    selected_db = session.get('selected_db')

    polygon_name = (request.form.get('polygon_name') or '').strip()
    parent_name  = (request.form.get('parent_name') or '').strip()
    allocation   = (request.form.get('allocation_reason') or '').strip()  # ENUM allocation_reason
    notes        = (request.form.get('notes') or '').strip()

    # TOP ranges
    top_from = request.form.getlist('top_range_from[]')
    top_to   = request.form.getlist('top_range_to[]')

    # BOTTOM ranges
    bot_from = request.form.getlist('bottom_range_from[]')
    bot_to   = request.form.getlist('bottom_range_to[]')

    try:
        if not polygon_name:
            raise ValueError("Polygon name is required.")
        if not allocation:
            raise ValueError("Allocation reason is required.")

        allowed_alloc = {
            "physical_separation",
            "research_phase",
            "horizontal_stratigraphy",
            "other",
        }
        if allocation not in allowed_alloc:
            raise ValueError("Invalid allocation reason.")

        if parent_name and parent_name == polygon_name:
            raise ValueError("Parent polygon cannot be the same as polygon name.")

        top_ranges = _prep_ranges(top_from, top_to)
        bot_ranges = _prep_ranges(bot_from, bot_to)

        if not top_ranges and not bot_ranges:
            raise ValueError("Provide at least one TOP or BOTTOM range of points.")

        conn = get_terrain_connection(selected_db)
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                # 1) Insert/Upsert polygon metadata
                cur.execute(insert_polygon_manual_sql(), (polygon_name, parent_name, allocation, notes))

                # 2) Replace bindings idempotently (clear then insert)
                cur.execute(delete_bindings_top_sql(), (polygon_name,))
                cur.execute(delete_bindings_bottom_sql(), (polygon_name,))

                for f_i, t_i in top_ranges:
                    cur.execute(insert_binding_top_sql(), (polygon_name, f_i, t_i))
                for f_i, t_i in bot_ranges:
                    cur.execute(insert_binding_bottom_sql(), (polygon_name, f_i, t_i))

                # 3) Rebuild geom_top / geom_bottom from tab_geopts
                cur.execute(rebuild_geom_sql(), (polygon_name,))

            conn.commit()
            flash(f'Polygon “{polygon_name}” saved and geometry rebuilt.', 'success')
            logger.info(
                f'[{selected_db}] polygon "{polygon_name}" saved: '
                f'{len(top_ranges)} TOP range(s), {len(bot_ranges)} BOTTOM range(s), allocation={allocation}.'
            )
        except Exception as e:
            conn.rollback()
            logger.error(f'[{selected_db}] manual polygon create error: {e}')
            flash(f'Error while saving polygon: {e}', 'danger')
        finally:
            try:
                conn.close()
            except Exception:
                pass

    except ValueError as ve:
        flash(str(ve), 'warning')
    except Exception as e:
        flash(f'Unexpected error: {e}', 'danger')

    return redirect(url_for('polygons.polygons'))



# ---------- TXT/CSV UPLOAD (geopts + bindings + rebuild) ----------
@polygons_bp.route('/upload-polygons', methods=['POST'])
@require_selected_db
def upload_polygons():
    selected_db = session.get('selected_db')

    file = request.files.get('file')
    epsg = request.form.get('epsg')
    side = (request.form.get('side') or '').strip().lower()  # 'top' | 'bottom'

    parent_name = (request.form.get('parent_name') or '').strip()
    allocation  = (request.form.get('allocation_reason') or '').strip()
    notes       = (request.form.get('notes') or '').strip()

    if not file or not epsg or side not in {"top", "bottom"}:
        flash('You must select a file, EPSG and side (TOP/BOTTOM).', 'danger')
        return redirect(url_for('polygons.polygons'))

    allowed_alloc = {
        "physical_separation",
        "research_phase",
        "horizontal_stratigraphy",
        "other",
    }
    if allocation not in allowed_alloc:
        flash('Invalid allocation reason.', 'warning')
        return redirect(url_for('polygons.polygons'))

    epsg_code = int(epsg)

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False

    try:
        # Parse file -> per polygon: points + consecutive ranges based on id_pts
        # { polygon_name: {"points": [(id_pts,x,y,h,code),...], "ranges":[(from,to),...] } }
        parsed = process_polygon_upload(file)

        if not parsed:
            flash('No valid rows found in file.', 'warning')
            return redirect(url_for('polygons.polygons'))

        with conn.cursor() as cur:
            # Determine project SRID from tab_geopts.pts_geom typmod (after set_project_srid)
            cur.execute(find_geopts_srid_sql())
            target_srid = (cur.fetchone() or [None])[0]
            if not target_srid or int(target_srid) <= 0:
                # fallback: if typmod SRID is still unknown, we will just "assign" source coords
                target_srid = epsg_code

            # Choose binding SQL by side
            if side == "top":
                delete_bindings_sql = delete_bindings_top_sql()
                insert_binding_sql = insert_binding_top_sql()
            else:
                delete_bindings_sql = delete_bindings_bottom_sql()
                insert_binding_sql = insert_binding_bottom_sql()

            polygons_done = 0
            points_done = 0
            ranges_done = 0

            for polygon_name, data in parsed.items():
                points = data["points"]
                ranges = data["ranges"]

                if not polygon_name:
                    continue

                # Upsert polygon metadata (allocation is required by DDL)
                cur.execute(insert_polygon_manual_sql(), (polygon_name, parent_name, allocation, notes))

                # Upsert points into tab_geopts (transform XY from source EPSG to target SRID)
                for (id_pts, x, y, h, code) in points:
                    cur.execute(
                        upsert_geopt_sql(),
                        (x, y, h, epsg_code, int(target_srid), id_pts, h, code)
                    )
                    points_done += 1


                # Replace bindings for given side (idempotent)
                cur.execute(delete_bindings_sql, (polygon_name,))
                for f_i, t_i in ranges:
                    cur.execute(insert_binding_sql, (polygon_name, f_i, t_i))
                    ranges_done += 1

                # Rebuild both geom_top/geom_bottom (function handles missing side gracefully)
                cur.execute(rebuild_geom_sql(), (polygon_name,))
                polygons_done += 1

        conn.commit()
        logger.info(
            f"[{selected_db}] upload-polygons: polygons={polygons_done}, points={points_done}, "
            f"ranges={ranges_done}, source_epsg={epsg_code}, side={side}, target_srid={target_srid}"
        )
        flash(f"Uploaded {polygons_done} polygon(s); inserted/updated {points_done} point(s).", 'success')

    except Exception as e:
        conn.rollback()
        logger.error(f"[{selected_db}] polygon upload error: {e}")
        flash(f'Error while uploading polygons: {str(e)}', 'danger')
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for('polygons.polygons'))

# making GeoJSON for export to leaflet (showing geometry in modal window)

@polygons_bp.route('/polygons/geojson', methods=['GET'])
@require_selected_db
def polygon_geojson():
    selected_db = session.get('selected_db')
    name = (request.args.get('name') or '').strip()

    if not name:
        return jsonify({"error": "Missing polygon name"}), 400

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(polygon_geoms_geojson_sql(), (name,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Polygon not found"}), 404

            top_gj, bottom_gj = row[0], row[1]

        # return JSON objects (GeoJSON), not strings
        payload = {
            "name": name,
            "top": json.loads(top_gj) if top_gj else None,
            "bottom": json.loads(bottom_gj) if bottom_gj else None,
        }
        return jsonify(payload)

    except Exception as e:
        logger.error(f"[{selected_db}] polygon_geojson error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@polygons_bp.route('/polygons/delete', methods=['POST'])
@require_selected_db
def delete_polygon():
    selected_db = session.get('selected_db')
    polygon_name = (request.form.get('polygon_name') or '').strip()

    if not polygon_name:
        flash("Missing polygon name.", "warning")
        return redirect(url_for('polygons.polygons'))

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # 1) read parent of the polygon we are deleting
            cur.execute(get_polygon_parent_sql(), (polygon_name,))
            row = cur.fetchone()
            if not row:
                flash(f'Polygon "{polygon_name}" not found.', "warning")
                conn.rollback()
                return redirect(url_for('polygons.polygons'))

            parent_of_deleted = row[0]  # may be NULL

            # 2) re-parent direct children to the deleted polygon's parent (or NULL)
            cur.execute(reparent_children_sql(), (parent_of_deleted, polygon_name))

            # 3) delete polygon (bindings will cascade)
            cur.execute(delete_polygon_sql(), (polygon_name,))

        conn.commit()
        flash(f'Polygon "{polygon_name}" deleted. Children were re-linked to its parent.', "success")
        logger.info(
            f'[{selected_db}] polygon "{polygon_name}" deleted; children reparented to {parent_of_deleted!r}'
        )

    except Exception as e:
        conn.rollback()
        logger.error(f'[{selected_db}] polygon delete error: {e}')
        flash(f'Error while deleting polygon: {e}', "danger")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for('polygons.polygons'))




# ---------- REBUILD ALL POLYGONS GEOMETRY ----------
@polygons_bp.route('/polygons/rebuild-all', methods=['POST'])
@require_selected_db
def rebuild_all_polygons():
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)
    rebuilt = 0
    try:
        with conn.cursor() as cur:
            # polygons that have at least one TOP/BOTTOM binding
            cur.execute(select_polygons_with_bindings_sql())
            names = [r[0] for r in cur.fetchall()]

            for polygon_name in names:
                cur.execute(rebuild_geom_sql(), (polygon_name,))
                rebuilt += 1

        conn.commit()
        flash(f"Geometry rebuilt for {rebuilt} polygon(s).", "success")
        logger.info(f"[{selected_db}] rebuilt geometry for {rebuilt} polygons.")
    except Exception as e:
        conn.rollback()
        logger.error(f"[{selected_db}] rebuild-all error: {e}")
        flash(f"Error during geometry rebuild: {e}", "danger")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for('polygons.polygons'))



# ---------- SHP EXPORT ----------
@polygons_bp.route('/download-polygons')
@require_selected_db
def download_polygons():
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)

    try:
        with conn.cursor() as cur:
            cur.execute(find_polygons_srid_sql())
            srid_row = cur.fetchone()
            srid = srid_row[0] if srid_row else None

            prj_wkt = ''
            if srid:
                cur.execute(srtext_by_srid_sql(), (srid,))
                prj_wkt = (cur.fetchone() or [''])[0] or ''

            cur.execute(polygons_geojson_top_bottom_sql())
            results = cur.fetchall()  # (name, top_gj, bottom_gj)

        # Build SHP in-memory
        shp_io = BytesIO()
        shx_io = BytesIO()
        dbf_io = BytesIO()

        
        with shapefile.Writer(shp=shp_io, shx=shx_io, dbf=dbf_io, shapeType=shapefile.POLYGON) as shp:
            shp.field('name', 'C', size=254)
            shp.field('side', 'C', size=10)  # 'top' | 'bottom'

            for name, top_gj, bottom_gj in results:
                # helper to write one geojson polygon/multipolygon
                def _write_geojson(gj_str, side):
                    if not gj_str:
                        return
                    gj = json.loads(gj_str)
                    gtype = gj.get('type')

                    if gtype == 'Polygon':
                        polys = [gj['coordinates']]
                    elif gtype == 'MultiPolygon':
                        polys = gj['coordinates']
                    else:
                        return

                    for rings in polys:
                        parts = []
                        for ring in rings:
                            pts = [(float(x), float(y)) for x, y in ring]
                            parts.append(pts)
                        shp.poly(parts)
                        shp.record(name, side)

                _write_geojson(top_gj, 'top')
                _write_geojson(bottom_gj, 'bottom')

        # Zip outputs (+ .prj)
        zip_io = BytesIO()
        with zipfile.ZipFile(zip_io, 'w') as zipf:
            base = f"{selected_db}_polygons"
            zipf.writestr(f"{base}.shp", shp_io.getvalue())
            zipf.writestr(f"{base}.shx", shx_io.getvalue())
            zipf.writestr(f"{base}.dbf", dbf_io.getvalue())
            if prj_wkt:
                zipf.writestr(f"{base}.prj", prj_wkt)

        zip_io.seek(0)
        return send_file(
            zip_io,
            mimetype='application/zip',
            download_name=f"{selected_db}_polygons.zip",
            as_attachment=True
        )

    except Exception as e:
        logger.error(f"[{selected_db}] SHP export error: {e}")
        flash(f'Error while generating SHP: {str(e)}', 'danger')
        return redirect(url_for('polygons.polygons'))
    finally:
        try:
            conn.close()
        except Exception:
            pass

# ---------- GRAPHIC MEDIA FOR POLYGONS ----------

@polygons_bp.post("/polygons/upload/<media_type>")
@require_selected_db
def upload_polygon_media(media_type):
    selected_db = session["selected_db"]

    # 1) validate media_type
    if media_type not in MEDIA_TABLES:
        flash("Invalid media type.", "danger")
        return redirect(url_for("polygons.polygons"))
    if media_type not in LINK_TABLES_POLYGON:
        flash("This media type is not supported for polygons.", "danger")
        return redirect(url_for("polygons.polygons"))

    # 2) polygon_name (TEXT PK)
    polygon_name = (request.form.get("polygon_name") or "").strip()
    if not polygon_name:
        flash("You must select a polygon first.", "warning")
        return redirect(url_for("polygons.polygons"))

    # 3) files input (name="files" multiple)
    files = request.files.getlist("files")
    if not files:
        flash("No files provided.", "warning")
        return redirect(url_for("polygons.polygons"))

    # 4) verify polygon exists
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(polygon_exists_sql(), (polygon_name,))
            if not cur.fetchone():
                flash(f'Polygon "{polygon_name}" not found.', "danger")
                return redirect(url_for("polygons.polygons"))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # 5) metadata from form (compatible with existing INSERT SQLs)
    notes = (request.form.get("notes") or "").strip() or None

    # read once (same for all uploaded files in this submit)
    if media_type == "photos":
        photo_typ = (request.form.get("photo_typ") or "").strip()
        datum = (request.form.get("datum") or "").strip() or None  # YYYY-MM-DD
        author = (request.form.get("author") or "").strip() or None
    elif media_type == "sketches":
        sketch_typ = (request.form.get("sketch_typ") or "").strip()
        author = (request.form.get("author") or "").strip() or None
        datum = (request.form.get("datum") or "").strip() or None
    else:  # photograms
        photogram_typ = (request.form.get("photogram_typ") or "").strip()

    ok, failed = 0, []

    for f in files:
        tmp_path = None
        final_path = None
        thumb_path = None

        try:
            # A) temp store
            tmp_path, tmp_size = storage.save_to_uploads(Config.UPLOAD_FOLDER, f)

            # B) pk + ext validation
            pk_name = storage.make_pk(selected_db, f.filename)
            storage.validate_pk(pk_name)
            ext = pk_name.rsplit(".", 1)[-1].lower()
            validate_extension(ext, Config.ALLOWED_EXTENSIONS)

            # C) final paths + collision
            media_dir = Config.MEDIA_DIRS[media_type]
            final_path, thumb_path = storage.final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)
            if os.path.exists(final_path):
                raise ValueError(f"File already exists: {pk_name}")

            # D) move into place then MIME validate
            storage.move_into_place(tmp_path, final_path)
            tmp_path = None

            mime = detect_mime(final_path)
            validate_mime(mime, Config.ALLOWED_MIME)
            checksum = sha256_file(final_path)

            # thumb best-effort
            try:
                make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
            except Exception:
                pass

            # E) EXIF for photos only (JPEG/TIFF)
            shoot_dt = gps_lat = gps_lon = gps_alt = None
            exif_json = {}
            if media_type == "photos" and mime in ("image/jpeg", "image/tiff"):
                sdt, la, lo, al, exif = extract_exif(final_path)
                shoot_dt, gps_lat, gps_lon, gps_alt, exif_json = sdt, la, lo, al, exif

            # F) DB insert + link (commit per file)
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
                        )
                    )
                    cur2.execute(link_polygon_photo_sql(), (polygon_name, pk_name))

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
                        )
                    )
                    cur2.execute(link_polygon_sketch_sql(), (polygon_name, pk_name))

                else:  # photograms (ref_sketch ignored for now)
                    cur2.execute(
                        insert_photogram_sql(),
                        (
                            pk_name,
                            photogram_typ or "",
                            notes,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                        )
                    )
                    cur2.execute(link_polygon_photogram_sql(), (polygon_name, pk_name))

                conn2.commit()
                ok += 1

            except Exception:
                conn2.rollback()
                # cleanup FS garbage if DB fails
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
            logger.warning(f"[{selected_db}] polygon media upload failed ({media_type}) {f.filename}: {e}")

        finally:
            if tmp_path:
                try:
                    storage.cleanup_upload(tmp_path)
                except Exception:
                    pass

    if failed:
        flash(
            f"Uploaded {ok} file(s), {len(failed)} failed: " + "; ".join(failed),
            "warning" if ok else "danger"
        )
    else:
        flash(f"Uploaded {ok} file(s).", "success")

    logger.info(f"[{selected_db}] polygon-media upload: polygon={polygon_name} type={media_type} ok={ok} failed={len(failed)}")
    return redirect(url_for("polygons.polygons"))
