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


@polygons_bp.route('/download-polygons')
@require_selected_db
def download_polygons():
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT polygon_name, ST_AsText(geom)
                FROM tab_polygons;
            """)
            results = cur.fetchall()

        # In-memory SHP streams
        shp_io = BytesIO()
        shx_io = BytesIO()
        dbf_io = BytesIO()

        # Build SHP in memory
        with shapefile.Writer(
            shp=shp_io, shx=shx_io, dbf=dbf_io, shapeType=shapefile.POLYGON
        ) as shp:
            shp.field('name', 'C')

            for name, wkt in results:
                # naive WKT POLYGON parser (no holes)
                coords = []
                coord_text = wkt.replace('POLYGON((', '').replace('))', '')
                for part in coord_text.split(','):
                    x, y = map(float, part.strip().split())
                    coords.append((x, y))
                shp.poly([coords])
                shp.record(name)

        # Build ZIP in memory
        zip_io = BytesIO()
        with zipfile.ZipFile(zip_io, 'w') as zipf:
            zipf.writestr(f"{selected_db}.shp", shp_io.getvalue())
            zipf.writestr(f"{selected_db}.shx", shx_io.getvalue())
            zipf.writestr(f"{selected_db}.dbf", dbf_io.getvalue())

            # Optional .prj (WGS84)
            prj = (
                'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
                'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
            )
            zipf.writestr(f"{selected_db}.prj", prj)

        zip_io.seek(0)
        logger.info(f"Prepared SHP ZIP for polygons from DB '{selected_db}'.")
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
