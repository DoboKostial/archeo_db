# app/routes/polygons.py
# logic for archeological polygons

from io import BytesIO
import zipfile
import json
import os
from datetime import date

import shapefile  # pyshp
from flask import (
    Blueprint, request, render_template, redirect, url_for,
    flash, session, send_file
)

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db

# --- storage / media utils ---
from app.utils.images import detect_mime, make_thumbnail, extract_exif
from app.utils.storage import sanitize_filename_keep_ext
from app.utils.validators import is_allowed_mime, compute_sha256

# --- QUERIES (add missing helpers to app/queries/polygons.py) ---
from app.queries.polygons import (
    # already provided by you:
    get_polygons_list,              # () -> SQL str: name, npoints, srid
    insert_polygon_sql,             # (polygon_name, points, source_epsg) -> SQL str with %s for name

    # add these helpers into queries.py:
    insert_polygon_manual_sql,      # () -> SQL str: INSERT INTO tab_polygons (id, polygon_name, geom) VALUES (%s,%s,NULL)
    insert_binding_sql,             # () -> SQL str: INSERT INTO tab_polygon_geopts_binding(ref_polygon, pts_from, pts_to) VALUES (%s,%s,%s)
    rebuild_geom_sql,               # () -> SQL str: SELECT rebuild_polygon_geom_from_geopts(%s)
    list_authors_sql,               # () -> SQL str: SELECT mail FROM gloss_personalia ORDER BY mail
    find_polygons_srid_sql,         # () -> SQL str: SELECT Find_SRID(current_schema(),'tab_polygons','geom')
    srtext_by_srid_sql,             # () -> SQL str with %s: SELECT srtext FROM spatial_ref_sys WHERE srid=%s
    polygons_geojson_sql,           # () -> SQL str: SELECT polygon_name, ST_AsGeoJSON(geom) FROM tab_polygons WHERE geom IS NOT NULL

    # media inserts + bindings:
    insert_photo_sql,               # () -> SQL str with placeholders for tab_photos insert
    bind_photo_to_polygon_sql,      # () -> SQL str: INSERT INTO tabaid_polygon_photos(ref_polygon, ref_photo) VALUES (%s,%s)
    insert_sketch_sql,              # () -> SQL str with placeholders for tab_sketches insert
    bind_sketch_to_polygon_sql,     # () -> SQL str: INSERT INTO tabaid_polygon_sketches(ref_polygon, ref_sketch) VALUES (%s,%s)
    insert_photogram_sql,           # () -> SQL str with placeholders for tab_photograms insert
    bind_photogram_to_polygon_sql,  # () -> SQL str: INSERT INTO tabaid_polygon_photograms(ref_polygon, ref_photogram) VALUES (%s,%s)
)

polygons_bp = Blueprint('polygons', __name__)


# ---------- small helpers (pure Python) ----------

def _db_prefix_from_dbname(dbname: str) -> str:
    """Extract leading numeric prefix from DB name, e.g. '456_Holesovice' -> '456_'."""
    import re
    m = re.match(r"^(\d+)_", dbname or "")
    return f"{m.group(1)}_" if m else ""


def _save_media_file(selected_db: str, subfolder: str, raw_filename, file_storage, thumb_max: int):
    """
    Save uploaded file to DATA_DIR/<db>/<subfolder>/<prefixed_name>,
    create thumbnail if raster. Returns (final_path, final_name, mime, size, checksum, thumb_ok).
    """
    db_dir = os.path.join(Config.DATA_DIR, selected_db)
    target_dir = os.path.join(db_dir, subfolder)
    thumbs_dir = os.path.join(target_dir, 'thumbs')
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(thumbs_dir, exist_ok=True)

    pref = _db_prefix_from_dbname(selected_db)
    safe_name = sanitize_filename_keep_ext(raw_filename)
    final_name = pref + safe_name
    final_path = os.path.join(target_dir, final_name)

    if os.path.exists(final_path):
        raise ValueError(f"File name collision: {final_name}")

    file_storage.save(final_path)

    mime = detect_mime(final_path)
    if not is_allowed_mime(mime):
        try: os.remove(final_path)
        except Exception: pass
        raise ValueError(f"MIME not allowed: {mime}")

    size = os.path.getsize(final_path)
    checksum = compute_sha256(final_path)

    thumb_ok = False
    try:
        thumb_path = os.path.join(thumbs_dir, os.path.splitext(final_name)[0] + ".jpg")
        thumb_ok = make_thumbnail(final_path, thumb_path, thumb_max)
    except Exception as te:
        logger.warning(f"Thumbnail failed for {final_name}: {te}")

    return final_path, final_name, mime, size, checksum, thumb_ok


# ---------- Main view: GET + POST (manual / upload / rebuild / media) ----------

@polygons_bp.route('/polygons', methods=['GET', 'POST'])
@require_selected_db
def polygons():
    selected_db = session.get('selected_db')

    # ----------------- POST branches -----------------
    if request.method == 'POST':

        # A) Manual polygon creation (by ranges)
        if request.form.get('id_polygon'):
            polygon_id_raw = (request.form.get('id_polygon') or '').strip()
            polygon_name   = (request.form.get('polygon_name') or '').strip()
            ranges_from = request.form.getlist('range_from[]')
            ranges_to   = request.form.getlist('range_to[]')

            try:
                if not polygon_name:
                    raise ValueError("Polygon name is required.")
                try:
                    polygon_id = int(polygon_id_raw)
                except Exception:
                    raise ValueError("Polygon ID must be an integer.")

                prepared = []
                for f, t in zip(ranges_from, ranges_to):
                    f = (f or '').strip(); t = (t or '').strip()
                    if not f and not t:
                        continue
                    if not f or not t:
                        raise ValueError("Each range must have both FROM and TO.")
                    try:
                        f_i = int(f); t_i = int(t)
                    except Exception:
                        raise ValueError("Range bounds must be integers.")
                    if f_i > t_i:
                        raise ValueError(f"Invalid range {f_i}>{t_i}.")
                    prepared.append((f_i, t_i))
                if not prepared:
                    raise ValueError("Provide at least one range of points.")

                conn = get_terrain_connection(selected_db)
                conn.autocommit = False
                try:
                    with conn.cursor() as cur:
                        # insert skeleton polygon (id + name, geom=NULL)
                        cur.execute(insert_polygon_manual_sql(), (polygon_id, polygon_name))

                        # bindings
                        for f_i, t_i in prepared:
                            cur.execute(insert_binding_sql(), (polygon_id, f_i, t_i))

                        # rebuild geometry
                        cur.execute(rebuild_geom_sql(), (polygon_id,))

                    conn.commit()
                    flash(f"Polygon #{polygon_id} saved and geometry rebuilt.", "success")
                except Exception as e:
                    conn.rollback()
                    logger.error(f"[{selected_db}] manual polygon creation failed: {e}")
                    flash(f"Error while saving polygon: {e}", "danger")
                finally:
                    conn.close()

            except ValueError as ve:
                flash(str(ve), "warning")

            return redirect(url_for('polygons.polygons'))

        # B) TXT/CSV upload (uses queries.insert_polygon_sql)
        if request.files.get('file'):
            upload_file = request.files.get('file')
            epsg = (request.form.get('epsg') or '').strip()
            if not epsg:
                flash('You must select an EPSG code.', 'danger')
                return redirect(url_for('polygons.polygons'))

            conn = get_terrain_connection(selected_db)
            try:
                # NOTE: process_polygon_upload lives in app/utils/geom_utils – ponecháváme
                from app.utils.geom_utils import process_polygon_upload
                uploaded_polygons, epsg_code = process_polygon_upload(upload_file, epsg)

                with conn:
                    with conn.cursor() as cur:
                        for polygon_name, points in uploaded_polygons.items():
                            sql_text = insert_polygon_sql(polygon_name, points, epsg_code)
                            # your helper returns SQL with a single %s placeholder for polygon_name
                            cur.execute(sql_text, (polygon_name,))

                flash(f"Uploaded {len(uploaded_polygons)} polygon(s).", "success")
            except Exception as e:
                logger.error(f"[{selected_db}] upload polygons failed: {e}")
                flash(f"Error while uploading polygons: {e}", "danger")
            finally:
                conn.close()

            return redirect(url_for('polygons.polygons'))

        # C) Rebuild geometry for one polygon (button per row)
        if request.form.get('rebuild_polygon_id'):
            rebuild_id_raw = (request.form.get('rebuild_polygon_id') or '').strip()
            try:
                polygon_id = int(rebuild_id_raw)
            except Exception:
                flash("Invalid polygon ID for rebuild.", "warning")
                return redirect(url_for('polygons.polygons'))

            conn = get_terrain_connection(selected_db)
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(rebuild_geom_sql(), (polygon_id,))
                flash(f"Geometry rebuilt for polygon #{polygon_id}.", "success")
            except Exception as e:
                logger.error(f"[{selected_db}] rebuild error for polygon {polygon_id}: {e}")
                flash(f"Error while rebuilding geometry: {e}", "danger")
            finally:
                conn.close()

            return redirect(url_for('polygons.polygons'))

        # D) Media uploads bound to polygon (photos / sketches / photograms)
        if request.form.get('media_target') == 'polygon':
            media_kind = (request.form.get('media_kind') or '').strip()  # 'photo' | 'sketch' | 'photogram'
            try:
                polygon_id = int(request.form.get('polygon_id') or '0')
            except Exception:
                flash("Polygon ID must be an integer.", "warning")
                return redirect(url_for('polygons.polygons'))

            author = (request.form.get('author') or '').strip()
            datum_str = (request.form.get('datum') or '').strip() or str(date.today())
            notes = (request.form.get('notes') or '').strip()

            photo_typ = (request.form.get('photo_typ') or '').strip()
            sketch_typ = (request.form.get('sketch_typ') or '').strip()
            photogram_typ = (request.form.get('photogram_typ') or '').strip()

            files = request.files.getlist('files[]')
            if not files:
                flash("No files selected.", "warning")
                return redirect(url_for('polygons.polygons'))

            subfolder_map = {'photo': 'photos', 'sketch': 'sketches', 'photogram': 'photograms'}
            subfolder = subfolder_map.get(media_kind)
            if not subfolder:
                flash("Unsupported media kind.", "danger")
                return redirect(url_for('polygons.polygons'))

            if media_kind in ('photo', 'sketch') and not author:
                flash("Author is required for this media type.", "warning")
                return redirect(url_for('polygons.polygons'))
            if media_kind == 'photo' and not photo_typ:
                flash("Photo type is required.", "warning")
                return redirect(url_for('polygons.polygons'))
            if media_kind == 'sketch' and not sketch_typ:
                flash("Sketch type is required.", "warning")
                return redirect(url_for('polygons.polygons'))
            if media_kind == 'photogram' and not photogram_typ:
                flash("Photogram type is required.", "warning")
                return redirect(url_for('polygons.polygons'))

            successes, failures = 0, []
            conn = get_terrain_connection(selected_db)
            conn.autocommit = False
            try:
                for fs in files:
                    if not fs or not fs.filename:
                        continue
                    raw_name = fs.filename
                    try:
                        _, final_name, mime, size, checksum, _ = _save_media_file(
                            selected_db, subfolder, raw_name, fs,
                            thumb_max=getattr(Config, 'THUMB_MAX_SIDE', 512)
                        )

                        with conn.cursor() as cur:
                            if media_kind == 'photo':
                                # enrich via EXIF
                                photo_path = os.path.join(Config.DATA_DIR, selected_db, 'photos', final_name)
                                shoot_dt, gps_lat, gps_lon, gps_alt, exif_json = extract_exif(photo_path)
                                cur.execute(
                                    insert_photo_sql(),
                                    (
                                        final_name, photo_typ, datum_str, author, notes or '',
                                        mime, size, checksum,
                                        shoot_dt, gps_lat, gps_lon, gps_alt, json.dumps(exif_json, ensure_ascii=False)
                                    )
                                )
                                cur.execute(bind_photo_to_polygon_sql(), (polygon_id, final_name))

                            elif media_kind == 'sketch':
                                cur.execute(
                                    insert_sketch_sql(),
                                    (final_name, sketch_typ, author, datum_str, notes or '', mime, size, checksum)
                                )
                                cur.execute(bind_sketch_to_polygon_sql(), (polygon_id, final_name))

                            else:  # photogram
                                cur.execute(
                                    insert_photogram_sql(),
                                    (final_name, photogram_typ, notes or '', mime, size, checksum)
                                )
                                cur.execute(bind_photogram_to_polygon_sql(), (polygon_id, final_name))

                        successes += 1

                    except Exception as fe:
                        failures.append(f"{raw_name}: {fe}")

                if failures:
                    conn.rollback()
                    flash(f"Uploaded 0 file(s), {len(failures)} failed: " + "; ".join(failures), "danger")
                else:
                    conn.commit()
                    flash(f"Uploaded {successes} file(s).", "success")

            except Exception as e:
                conn.rollback()
                logger.error(f"[{selected_db}] media upload failed: {e}")
                flash(f"Error during media upload: {e}", "danger")
            finally:
                conn.close()

            return redirect(url_for('polygons.polygons'))

        flash("Unsupported action.", "warning")
        return redirect(url_for('polygons.polygons'))

    # ----------------- GET: render -----------------
    authors = []
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(list_authors_sql())
            authors = [r[0] for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"Authors list failed: {e}")
    finally:
        conn.close()

    # NOTE: your get_polygons_list() currently returns: name, npoints, srid
    # For listing + 'rebuild' action we also need the polygon ID. Consider
    # updating the query helper to include p.id as the first column.
    conn = get_terrain_connection(selected_db)
    polygons = []
    try:
        with conn.cursor() as cur:
            cur.execute(get_polygons_list())
            # Expect shape: (id, name, points, epsg) — adjust your helper accordingly.
            for row in cur.fetchall():
                # If your current helper returns only (name, points, srid),
                # you can temporarily synthesize a row without ID, but
                # 'Rebuild geometry' button needs the id.
                if len(row) == 4:
                    pid, name, pts, epsg = row
                else:
                    # fallback: no id available (disable rebuild in template if needed)
                    pid, name, pts, epsg = None, row[0], row[1], row[2]
                polygons.append({'id': pid, 'name': name, 'points': pts, 'epsg': epsg})
    finally:
        conn.close()

    return render_template('polygons.html',
                           selected_db=selected_db,
                           polygons=polygons,
                           authors=authors)


# ---------- SHP export (all polygons) ----------

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

        shp_io = BytesIO(); shx_io = BytesIO(); dbf_io = BytesIO()
        with shapefile.Writer(shp=shp_io, shx=shx_io, dbf=dbf_io, shapeType=shapefile.POLYGON) as shp:
            shp.field('name', 'C', size=254)
            for name, gjson in results:
                gj = json.loads(gjson)
                gtype = gj['type']
                polygons = []
                if gtype == 'Polygon':
                    polygons.append(gj['coordinates'])
                elif gtype == 'MultiPolygon':
                    polygons.extend(gj['coordinates'])
                else:
                    continue
                for poly_rings in polygons:
                    parts = []
                    for ring in poly_rings:
                        pts = [(float(x), float(y)) for x, y in ring]
                        parts.append(pts)
                    shp.poly(parts)
                    shp.record(name)

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
        logger.error(f"Error while generating SHP for DB '{selected_db}': {e}")
        flash(f'Error while generating SHP: {e}', 'danger')
        return redirect(url_for('polygons.polygons'))
    finally:
        conn.close()
