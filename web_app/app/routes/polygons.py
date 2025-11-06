# app/routes/polygons.py
# logic for archeological polygons

# app/routes/polygons.py
from io import BytesIO
import json
import zipfile

from flask import (
    Blueprint, request, render_template, redirect, url_for,
    flash, session, send_file
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
    get_polygons_list, insert_polygon_sql,
    insert_polygon_manual_sql, insert_binding_sql, rebuild_geom_sql,
    list_authors_sql, find_polygons_srid_sql, srtext_by_srid_sql, polygons_geojson_sql
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
                {'id': row[0], 'name': row[1], 'points': row[2], 'srid': row[3]}
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


# ---------- MANUAL CREATE (ID + name + ranges) ----------
@polygons_bp.route('/polygons/new-manual', methods=['POST'])
@require_selected_db
def new_polygon_manual():
    selected_db = session.get('selected_db')

    polygon_id_raw = request.form.get('id_polygon', '').strip()
    polygon_name   = request.form.get('polygon_name', '').strip()
    ranges_from    = request.form.getlist('range_from[]')
    ranges_to      = request.form.getlist('range_to[]')

    try:
        if not polygon_id_raw or not polygon_name:
            raise ValueError("Polygon ID and name are required.")
        try:
            polygon_id = int(polygon_id_raw)
        except Exception:
            raise ValueError("Polygon ID must be integer.")

        prepared_ranges = []
        for f, t in zip(ranges_from, ranges_to):
            f = (f or "").strip()
            t = (t or "").strip()
            if not f and not t:
                continue
            if not f or not t:
                raise ValueError("Each range must have BOTH FROM and TO.")
            f_i = int(f); t_i = int(t)
            if f_i > t_i:
                raise ValueError(f"Invalid range: {f_i} > {t_i}.")
            prepared_ranges.append((f_i, t_i))
        if not prepared_ranges:
            raise ValueError("Provide at least one range of points.")

        conn = get_terrain_connection(selected_db)
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                # polygon skeleton
                cur.execute(insert_polygon_manual_sql(), (polygon_id, polygon_name))
                # bindings
                for f_i, t_i in prepared_ranges:
                    cur.execute(insert_binding_sql(), (polygon_id, f_i, t_i))
                # rebuild
                cur.execute(rebuild_geom_sql(), (polygon_id,))
            conn.commit()
            flash(f"Polygon #{polygon_id} saved and geometry rebuilt.", "success")
            logger.info(f"[{selected_db}] polygon {polygon_id} created manually with {len(prepared_ranges)} ranges.")
        except Exception as e:
            conn.rollback()
            logger.error(f"[{selected_db}] manual polygon create error: {e}")
            flash(f"Error while saving polygon: {e}", "danger")
    except ValueError as ve:
        flash(str(ve), "warning")
    except Exception as e:
        flash(f"Unexpected error: {e}", "danger")

    return redirect(url_for('polygons.polygons'))


# ---------- TXT/CSV UPLOAD ----------
@polygons_bp.route('/upload-polygons', methods=['POST'])
@require_selected_db
def upload_polygons():
    selected_db = session.get('selected_db')
    file = request.files.get('file')
    epsg = request.form.get('epsg')

    if not file or not epsg:
        flash('You must select a file and an EPSG code.', 'danger')
        return redirect(url_for('polygons.polygons'))

    conn = get_terrain_connection(selected_db)
    try:
        uploaded_polygons, epsg_code = process_polygon_upload(file, epsg)
        with conn.cursor() as cur:
            for polygon_name, points in uploaded_polygons.items():
                sql_text = insert_polygon_sql(polygon_name, points, epsg_code)
                cur.execute(sql_text, (polygon_name,))
        conn.commit()
        logger.info(f"[{selected_db}] uploaded {len(uploaded_polygons)} polygon(s) (EPSG {epsg_code}).")
        flash('Polygon(s) were uploaded successfully.', 'success')
    except Exception as e:
        conn.rollback()
        logger.error(f"[{selected_db}] polygon upload error: {e}")
        flash(f'Error while uploading polygons: {str(e)}', 'danger')
    finally:
        conn.close()

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
            # only polygons that have at least one binding
            cur.execute("""
                SELECT DISTINCT ref_polygon
                FROM tab_polygon_geopts_binding
                ORDER BY ref_polygon
            """)
            ids = [r[0] for r in cur.fetchall()]
            for pid in ids:
                cur.execute(rebuild_geom_sql(), (pid,))
                rebuilt += 1
        conn.commit()
        flash(f"Geometry rebuilt for {rebuilt} polygon(s).", "success")
        logger.info(f"[{selected_db}] rebuilt geometry for {rebuilt} polygons.")
    except Exception as e:
        conn.rollback()
        logger.error(f"[{selected_db}] rebuild-all error: {e}")
        flash(f"Error during geometry rebuild: {e}", "danger")
    finally:
        conn.close()
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
            srid = cur.fetchone()[0]
            cur.execute(srtext_by_srid_sql(), (srid,))
            prj_wkt = (cur.fetchone() or [''])[0] or ''
            cur.execute(polygons_geojson_sql())
            results = cur.fetchall()

        # build SHP in-memory
        shp_io = BytesIO(); shx_io = BytesIO(); dbf_io = BytesIO()
        import shapefile  # pyshp
        with shapefile.Writer(
            shp=shp_io, shx=shx_io, dbf=dbf_io, shapeType=shapefile.POLYGON
        ) as shp:
            shp.field('name', 'C', size=254)

            for name, gjson in results:
                gj = json.loads(gjson)
                gtype = gj['type']
                if gtype == 'Polygon':
                    polys = [gj['coordinates']]
                elif gtype == 'MultiPolygon':
                    polys = gj['coordinates']
                else:
                    continue
                for rings in polys:
                    parts = []
                    for ring in rings:
                        pts = [(float(x), float(y)) for x, y in ring]
                        parts.append(pts)
                    shp.poly(parts)
                    shp.record(name)

        # zip outputs (+ .prj)
        zip_io = BytesIO()
        with zipfile.ZipFile(zip_io, 'w') as zipf:
            base = f"{selected_db}"
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
        conn.close()


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
