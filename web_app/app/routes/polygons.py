# app/routes/polygons.py
# logic for archeological polygons

from io import BytesIO
import json
import zipfile
import shapefile  # pyshp

from flask import (
    Blueprint, request, render_template, redirect, url_for,
    flash, session, send_file, jsonify
)

from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db
from app.utils.geom_utils import process_polygon_upload
from app.utils import storage
from app.utils.validators import validate_extension, validate_mime, sha256_file
from app.utils.images import detect_mime, make_thumbnail, extract_exif
from config import Config

# SQLs from app/queries.py
from app.queries import (
    insert_polygon_manual_sql, delete_bindings_top_sql, delete_bindings_bottom_sql,
    insert_binding_top_sql, insert_binding_bottom_sql, rebuild_geom_sql, select_polygons_with_bindings_sql,
    srtext_by_srid_sql, polygons_geojson_sql, get_polygons_list, list_authors_sql, find_geopts_srid_sql, upsert_geopt_sql, 
    polygon_geoms_geojson_sql, find_polygons_srid_sql, polygons_geojson_top_bottom_sql, srtext_by_srid_sql
)


polygons_bp = Blueprint('polygons', __name__)

# Local mapping for polygon↔media link tables (so we don't touch media_map.py)
POLY_LINKS = {
    "photos":     {"table": "tabaid_polygon_photos",     "fk_media": "ref_photo"},
    "sketches":   {"table": "tabaid_polygon_sketches",   "fk_media": "ref_sketch"},
    "photograms": {"table": "tabaid_polygon_photograms", "fk_media": "ref_photogram"},
}
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



# ---------- MEDIA UPLOAD (photos/sketches/photograms) ----------
def _handle_media_upload(kind: str):
    """
    Common handler for photos/sketches/photograms uploads bound to a polygon.
    Uses ONLY existing utils functions.
    """
    assert kind in ("photos", "sketches", "photograms")
    selected_db = session.get('selected_db')
    dbname = selected_db  # used for make_pk()

    ref_polygon_raw = request.form.get('ref_polygon', '').strip()
    if not ref_polygon_raw:
        raise ValueError("Polygon ID is required.")
    try:
        ref_polygon = int(ref_polygon_raw)
    except Exception:
        raise ValueError("Polygon ID must be integer.")

    # common meta
    notes = (request.form.get('notes') or '').strip()

    # kind-specific extras
    extras = {}
    if kind == "photos":
        extras["photo_typ"] = (request.form.get('photo_typ') or '').strip()
        extras["datum"]     = (request.form.get('datum') or '').strip()  # 'YYYY-MM-DD'
        extras["author"]    = (request.form.get('author') or '').strip()
    elif kind == "sketches":
        extras["sketch_typ"] = (request.form.get('sketch_typ') or '').strip()
        extras["author"]     = (request.form.get('author') or '').strip()
        extras["datum"]      = (request.form.get('datum') or '').strip()
    else:  # photograms
        extras["photogram_typ"] = (request.form.get('photogram_typ') or '').strip()
        extras["ref_sketch"]    = (request.form.get('ref_sketch') or '').strip() or None

    # files
    files = request.files.getlist('files[]')
    if not files:
        raise ValueError("Select at least one file.")

    saved = 0
    failed = []

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for fs in files:
                try:
                    # Build PK based on DB prefix + sanitized original name
                    pk = storage.make_pk(dbname, fs.filename)

                    # Save to uploads tmp
                    tmp_path, fsize = storage.save_to_uploads(Config.UPLOAD_FOLDER, fs)

                    # Validate by ext + MIME
                    ext = pk.rsplit('.', 1)[-1].lower()
                    validate_extension(ext, ALLOWED_EXT)
                    mime = detect_mime(tmp_path)
                    validate_mime(mime, ALLOWED_MIME)

                    # Checksums
                    checksum = sha256_file(tmp_path)

                    # Final paths
                    subdir = MEDIA_DIRS[kind]
                    final_path, thumb_path = storage.final_paths(Config.DATA_DIR, dbname, subdir, pk)

                    # Extract EXIF only for photos
                    shoot_dt = gps_lat = gps_lon = gps_alt = None
                    exif_json = None
                    if kind == "photos" and mime == "image/jpeg":
                        shoot_dt, gps_lat, gps_lon, gps_alt, exif_json = extract_exif(tmp_path)

                    # Move into place
                    storage.move_into_place(tmp_path, final_path)

                    # Thumbnail if raster
                    try:
                        make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
                    except Exception:
                        # thumb is not critical
                        pass

                    # Insert media row + bind to polygon
                    if kind == "photos":
                        # tab_photos insert
                        cur.execute("""
                            INSERT INTO tab_photos(
                                id_photo, photo_typ, datum, author, notes,
                                mime_type, file_size, checksum_sha256,
                                shoot_datetime, gps_lat, gps_lon, gps_alt, exif_json
                            )
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            pk, extras["photo_typ"] or '', extras["datum"] or None, extras["author"] or None, notes or None,
                            mime, fsize, checksum,
                            shoot_dt, gps_lat, gps_lon, gps_alt, json.dumps(exif_json) if exif_json is not None else None
                        ))
                        # bind
                        cur.execute(f"""
                            INSERT INTO {POLY_LINKS['photos']['table']} (ref_polygon, {POLY_LINKS['photos']['fk_media']})
                            VALUES (%s, %s)
                        """, (ref_polygon, pk))

                    elif kind == "sketches":
                        cur.execute("""
                            INSERT INTO tab_sketches(
                                id_sketch, sketch_typ, author, datum, notes,
                                mime_type, file_size, checksum_sha256
                            )
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            pk, extras["sketch_typ"] or '', extras["author"] or None, extras["datum"] or None, notes or None,
                            mime, fsize, checksum
                        ))
                        cur.execute(f"""
                            INSERT INTO {POLY_LINKS['sketches']['table']} (ref_polygon, {POLY_LINKS['sketches']['fk_media']})
                            VALUES (%s, %s)
                        """, (ref_polygon, pk))

                    else:  # photograms
                        cur.execute("""
                            INSERT INTO tab_photograms(
                                id_photogram, photogram_typ, ref_sketch, notes,
                                mime_type, file_size, checksum_sha256
                            )
                            VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            pk, extras["photogram_typ"] or '', extras["ref_sketch"], notes or None,
                            mime, fsize, checksum
                        ))
                        cur.execute(f"""
                            INSERT INTO {POLY_LINKS['photograms']['table']} (ref_polygon, {POLY_LINKS['photograms']['fk_media']})
                            VALUES (%s, %s)
                        """, (ref_polygon, pk))

                    saved += 1

                except Exception as e:
                    # clean tmp if still there
                    try:
                        storage.cleanup_upload(tmp_path)
                    except Exception:
                        pass
                    logger.warning(f"[{selected_db}] media upload failed for {fs.filename}: {e}")
                    failed.append(f"{fs.filename}: {e}")

        conn.commit()
        if saved:
            flash(f"Uploaded {saved} file(s)." + (f" {len(failed)} failed." if failed else ""), "success")
        if failed:
            flash("Failed: " + "; ".join(failed), "warning")

    except Exception as e:
        conn.rollback()
        logger.error(f"[{selected_db}] media upload fatal error: {e}")
        flash(f"Upload failed: {e}", "danger")

    finally:
        try:
            storage.cleanup_upload(tmp_path)  # best-effort
        except Exception:
            pass
        conn.close()


@polygons_bp.route('/polygons/upload/photos', methods=['POST'])
@require_selected_db
def upload_polygon_photos():
    try:
        _handle_media_upload("photos")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for('polygons.polygons'))


@polygons_bp.route('/polygons/upload/sketches', methods=['POST'])
@require_selected_db
def upload_polygon_sketches():
    try:
        _handle_media_upload("sketches")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for('polygons.polygons'))


@polygons_bp.route('/polygons/upload/photograms', methods=['POST'])
@require_selected_db
def upload_polygon_photograms():
    try:
        _handle_media_upload("photograms")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for('polygons.polygons'))
