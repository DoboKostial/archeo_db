# # app/utils/geom_utils.py
# helpers for geometry things

#imports from standard library
import csv, tempfile
from psycopg2 import sql
# imports from app
from app.logger import logger
from app.database import get_terrain_connection

### functions
###
# After new DB creation we have default nonsense SRID assigned. This function defines and updates correct SRID
def update_geometry_srid(dbname: str, target_srid: int) -> None:
    logger.info(f"Updating SRID in DB '{dbname}' to {target_srid}")
    conn = get_terrain_connection(dbname)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT f_table_schema, f_table_name, f_geometry_column, coord_dimension, srid, type
                FROM geometry_columns
                WHERE f_table_schema = 'public'
            """)
            rows = cur.fetchall()

            for row in rows:
                schema, table, column, _, current_srid, geom_type = row

                if current_srid != int(target_srid):
                    logger.info(f"Changing SRID to {target_srid} in {schema}.{table}.{column} ({geom_type})")

                    try:
                        alter_sql = sql.SQL("""
                            ALTER TABLE {schema}.{table}
                            ALTER COLUMN {column}
                            TYPE geometry({geom_type}, {target_srid})
                            USING ST_Transform({column}, {target_srid})
                        """).format(
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table),
                            column=sql.Identifier(column),
                            geom_type=sql.SQL(geom_type),
                            target_srid=sql.Literal(int(target_srid))
                        )

                        cur.execute(alter_sql)
                    except Exception as inner_e:
                        logger.error(f"Error while changing SRID in {schema}.{table}.{column}: {inner_e}")
                        raise inner_e

        conn.commit()
        logger.info(f"SRID update in DB '{dbname}' finished")
    except Exception as e:
        logger.error(f"Error while updating SRID in DB '{dbname}': {e}")
        raise
    finally:
        conn.close()



# utility for upload and control of .csv file with polygon vertices
#    Reads CSV file and prepares the list of polygons.
#    Returns: (dict polygon_name -> [(x, y), ...]), int epsg_code
def process_polygon_upload(file, epsg_code: int):
    filename = getattr(file, "filename", "uploaded.csv")
    logger.info(f"Processing polygon CSV upload: {filename} (epsg={epsg_code})")

    polygons = {}

    try:
        # We store FileStorage on disk temporarily, while csv.reader needs path or file-like object
        with tempfile.NamedTemporaryFile(delete=False, mode='w+', encoding='utf-8') as tmp:
            file.stream.seek(0)
            content = file.read().decode('utf-8')
            tmp.write(content)
            tmp.flush()
            tmp.seek(0)

            reader = csv.reader(tmp)
            next(reader, None)  # skip header if present

            for row in reader:
                if len(row) < 5:
                    raise ValueError("The row in file does not have enough values (expected 5).")

                id_point, x, y, z, polygon_name = row
                x, y = float(x), float(y)

                if polygon_name not in polygons:
                    polygons[polygon_name] = []
                polygons[polygon_name].append((x, y))
    except Exception as e:
        logger.error(f"Error while processing polygon CSV '{filename}': {e}")
        raise

    # Close the polygon if not closed yet
    for poly_points in polygons.values():
        if poly_points and poly_points[0] != poly_points[-1]:
            poly_points.append(poly_points[0])

    logger.info(f"Polygon CSV processed: {len(polygons)} polygon(s)")
    return polygons, int(epsg_code)



#   This prepares the list (glossary) of polygons from points records:
#    {polygon_name: [(x, y), (x, y), ...]}
def prepare_polygons(points):
    logger.info(f"Preparing polygons from {len(points)} points")
    polygons = {}

    for point in points:
        description = point['description']
        x = point['x']
        y = point['y']

        if description not in polygons:
            polygons[description] = []
        polygons[description].append((x, y))

    # Close the polygons automatically
    for description, pts in polygons.items():
        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])

    logger.info(f"Prepared {len(polygons)} polygon(s) from points")
    return polygons