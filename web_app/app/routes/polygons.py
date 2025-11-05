# web_app/app/routes/polygons.py
from io import BytesIO
import zipfile
import shapefile  # pyshp

from flask import (
    Blueprint, request, render_template, redirect, url_for,
    flash, session, send_file
)

from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db
from app.utils.geom_utils import process_polygon_upload
from app.queries import get_polygons_list, insert_polygon_sql

polygons_bp = Blueprint('polygons', __name__)


@polygons_bp.route('/polygons/new-manual', methods=['GET', 'POST'])
@require_selected_db
def new_polygon_manual():
    selected_db = session.get('selected_db')

    if request.method == 'GET':
        return render_template('polygons_new_manual.html', selected_db=selected_db)

    # POST
    polygon_id_raw = request.form.get('id_polygon', '').strip()
    polygon_name   = request.form.get('polygon_name', '').strip()

    # ranges: přijdou jako paralelní pole
    ranges_from = request.form.getlist('range_from[]')
    ranges_to   = request.form.getlist('range_to[]')

    # Validace vstupů
    try:
        if not polygon_id_raw or not polygon_name:
            raise ValueError("ID polygonu i název jsou povinné.")

        try:
            polygon_id = int(polygon_id_raw)
        except Exception:
            raise ValueError("ID polygonu musí být celé číslo.")

        # připrav platné rozsahy
        prepared_ranges = []
        for f, t in zip(ranges_from, ranges_to):
            f = f.strip(); t = t.strip()
            if not f and not t:
                continue
            if not f or not t:
                raise ValueError("Rozsah bodů musí mít vyplněno FROM i TO.")
            try:
                f_i = int(f); t_i = int(t)
            except Exception:
                raise ValueError("Hodnoty FROM/TO musí být celá čísla.")
            if f_i > t_i:
                raise ValueError(f"Neplatný rozsah: {f_i} > {t_i}.")
            prepared_ranges.append((f_i, t_i))

        if not prepared_ranges:
            raise ValueError("Zadej alespoň jeden rozsah bodů.")

        # uložení do DB
        conn = get_terrain_connection(selected_db)
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                # 1) založ polygon s daným ID (geom = NULL zatím)
                cur.execute("""
                    INSERT INTO tab_polygons (id, polygon_name, geom)
                    VALUES (%s, %s, NULL)
                """, (polygon_id, polygon_name))

                # 2) založ bindingy (víc řádků, každý rozsah)
                for f_i, t_i in prepared_ranges:
                    cur.execute("""
                        INSERT INTO tab_polygon_geopts_binding (ref_polygon, pts_from, pts_to)
                        VALUES (%s, %s, %s)
                    """, (polygon_id, f_i, t_i))

                # 3) rebuild geometrie z tab_geopts
                cur.execute("SELECT rebuild_polygon_geom_from_geopts(%s)", (polygon_id,))

            conn.commit()
            flash(f"Polygon #{polygon_id} uložen. Geometrie byla přegenerována.", "success")
            logger.info(f"[{selected_db}] polygon {polygon_id} created manually with {len(prepared_ranges)} ranges.")
        except Exception as e:
            conn.rollback()
            # pokud duplicitní ID, or FK problém
            logger.error(f"[{selected_db}] error creating polygon manually: {e}")
            raise
        finally:
            conn.close()

    except ValueError as ve:
        flash(str(ve), "warning")
        return redirect(url_for('polygons.new_polygon_manual'))
    except Exception as e:
        flash(f"Chyba při ukládání polygonu: {e}", "danger")
        return redirect(url_for('polygons.new_polygon_manual'))

    return redirect(url_for('polygons.polygons'))



@polygons_bp.route('/polygons', methods=['GET'])
@require_selected_db
def polygons():
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)
    polys = []

    try:
        with conn.cursor() as cur:
            cur.execute(get_polygons_list())
            polys = [
                {'name': row[0], 'points': row[1], 'epsg': row[2]}
                for row in cur.fetchall()
            ]
        logger.info(f"Listed polygons from DB '{selected_db}': {len(polys)} item(s).")
    except Exception as e:
        logger.error(f"Error while listing polygons from DB '{selected_db}': {e}")
        flash('Error while loading polygons list.', 'danger')
    finally:
        conn.close()

    return render_template('polygons.html', polygons=polys, selected_db=selected_db)


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
        # Parse CSV and get polygons dictionary
        uploaded_polygons, epsg_code = process_polygon_upload(file, epsg)

        with conn.cursor() as cur:
            for polygon_name, points in uploaded_polygons.items():
                sql_text, params = insert_polygon_sql(polygon_name, points, epsg_code)
                cur.execute(sql_text, params)

        conn.commit()
        logger.info(f"Uploaded {len(uploaded_polygons)} polygon(s) into DB '{selected_db}' (EPSG {epsg_code}).")
        flash('Polygon(s) were uploaded successfully.', 'success')

    except Exception as e:
        conn.rollback()
        logger.error(f"Error while uploading polygons into DB '{selected_db}': {e}")
        flash(f'Error while uploading polygons: {str(e)}', 'danger')
    finally:
        conn.close()

    return redirect(url_for('polygons.polygons'))


# This enpoint creates shapefile .zip with all polygons for further use in GIS
@polygons_bp.route('/download-polygons')
@require_selected_db
def download_polygons():
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)

    try:
        with conn.cursor() as cur:
            # SRID + PRJ (WKT) pro shapefile
            cur.execute("SELECT Find_SRID(current_schema(), 'tab_polygons','geom')")
            srid = cur.fetchone()[0]
            cur.execute("SELECT srtext FROM spatial_ref_sys WHERE srid = %s", (srid,))
            prj_wkt = (cur.fetchone() or [''])[0] or ''

            # GeoJSON pro přesné prstence (podporuje i MultiPolygon)
            cur.execute("""
                SELECT polygon_name, ST_AsGeoJSON(geom)
                FROM tab_polygons
                WHERE geom IS NOT NULL
            """)
            results = cur.fetchall()

        # In-memory SHP streams
        shp_io = BytesIO(); shx_io = BytesIO(); dbf_io = BytesIO()

        import json
        import shapefile  # pyshp

        with shapefile.Writer(shp=shp_io, shx=shx_io, dbf=dbf_io, shapeType=shapefile.POLYGON) as shp:
            shp.field('name', 'C', size=254)

            for name, gjson in results:
                gj = json.loads(gjson)
                gtype = gj['type']
                coords_all = []

                if gtype == 'Polygon':
                    # list of linear rings: [ exterior, hole1, hole2, ... ]
                    coords_all.append(gj['coordinates'])
                elif gtype == 'MultiPolygon':
                    # list of polygons, each is list of rings
                    coords_all.extend(gj['coordinates'])
                else:
                    continue  # ignore non-polygonal (shouldn't happen)

                # pyshp expects one polygon per record, but can have multiple parts (rings)
                # export each polygon from a MultiPolygon as separate record
                for poly_rings in coords_all:
                    parts = []
                    for ring in poly_rings:
                        pts = [(float(x), float(y)) for x, y in ring]
                        parts.append(pts)
                    shp.poly(parts)
                    shp.record(name)

        # ZIP everything (+ .prj)
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
        flash(f'Error while generating SHP: {str(e)}', 'danger')
        return redirect(url_for('polygons.polygons'))
    finally:
        conn.close()
