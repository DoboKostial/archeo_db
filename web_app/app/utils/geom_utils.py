# # app/utils/geom_utils.py
# helpers for geometry things

#imports from standard library
from typing import Optional
import io, csv
import psycopg2
from psycopg2 import sql, errors
# imports from app
from app.logger import logger
from app.database import get_terrain_connection

###
### utils functions
###

# After new DB creation we have no SRID assigned. This function sets
# project SRID for ALL geometry columns in the freshly created DB by
# delegating to the DB function 'set_project_srid'.
#If 'schema' is None, DB-side default (current_schema()) is used.
# Requires that the terrain_db_template already contains:
# - CREATE EXTENSION IF NOT EXISTS postgis;
# - CREATE FUNCTION set_project_srid(target_srid int, in_schema text DEFAULT current_schema()) RETURNS void 
#   and updates correct SRID
def update_geometry_srid(dbname: str, target_srid: int, schema: Optional[str] = None) -> None:
    logger.info(f"Updating SRID in DB '{dbname}' to EPSG:{target_srid}")
    conn = get_terrain_connection(dbname)
    conn.autocommit = True  # we only run a single SELECT; safe & simple

    try:
        with conn.cursor() as cur:
            # Prefer 2-arg variant if schema explicitly provided, otherwise 1-arg default
            if schema:
                logger.info(f"Calling set_project_srid({target_srid}, schema='{schema}')")
                cur.execute("SELECT set_project_srid(%s, %s)", (int(target_srid), schema))
            else:
                logger.info(f"Calling set_project_srid({target_srid})")
                cur.execute("SELECT set_project_srid(%s)", (int(target_srid),))

        logger.info(f"SRID update in DB '{dbname}' finished")
    except errors.UndefinedFunction:
        logger.error(
            "DB function set_project_srid(...) not found. "
            "Make sure your terrain_db_template defines it and PostGIS extension is present."
        )
        raise
    except Exception as e:
        logger.error(f"Error while updating SRID in DB '{dbname}': {e}")
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _compress_consecutive_ids(ids):
    """Given sorted unique ids [1,2,3,7,8] -> [(1,3),(7,8)]"""
    if not ids:
        return []
    ranges = []
    start = prev = ids[0]
    for v in ids[1:]:
        if v == prev + 1:
            prev = v
            continue
        ranges.append((start, prev))
        start = prev = v
    ranges.append((start, prev))
    return ranges


def process_polygon_upload(file):
    """
    Parse TXT/CSV from total station:
      id_pts,x,y,h,code,polygon_name

    Returns:
      {
        "sonda1": {
          "points": [(1,x,y,h,"VP"), (2,...), ...],
          "ranges": [(1,3), (10,12)]  # consecutive id blocks
        },
        ...
      }
    """
    filename = getattr(file, "filename", "uploaded.txt")
    logger.info(f"Processing polygon upload file: {filename}")

    # Read as text (robust for typical UTF-8 / Windows exports)
    file.stream.seek(0)
    raw = file.stream.read()
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)

    # csv.reader over in-memory string
    buf = io.StringIO(text)
    reader = csv.reader(buf, delimiter=',')

    out = {}

    for row in reader:
        if not row:
            continue

        # Strip whitespace in each column
        row = [c.strip() for c in row if c is not None]
        if len(row) == 0:
            continue

        # Skip comments / separators
        if row[0].startswith("#"):
            continue

        if len(row) < 6:
            raise ValueError("Invalid row: expected 6 columns: id_pts,x,y,h,code,polygon_name")

        id_pts_s, x_s, y_s, h_s, code, polygon_name = row[:6]

        # normalize polygon name (last column)
        polygon_name = (polygon_name or "").strip()
        if not polygon_name:
            raise ValueError("Polygon name (last column) is empty in at least one row.")

        try:
            id_pts = int(id_pts_s)
            x = float(x_s)
            y = float(y_s)
            h = float(h_s)
        except Exception as e:
            raise ValueError(f"Cannot parse numeric values in row: {row} ({e})")

        rec = out.setdefault(polygon_name, {"points": [], "ids": set()})
        rec["points"].append((id_pts, x, y, h, code))
        rec["ids"].add(id_pts)

    # Build ranges from ids
    final = {}
    for polygon_name, rec in out.items():
        ids_sorted = sorted(rec["ids"])
        ranges = _compress_consecutive_ids(ids_sorted)
        final[polygon_name] = {
            "points": rec["points"],
            "ranges": ranges
        }

    logger.info(f"Polygon upload parsed: {len(final)} polygon(s)")
    return final



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