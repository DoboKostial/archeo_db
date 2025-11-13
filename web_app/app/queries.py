#############################
# app/queries.py
# all SQL queries in app in one file (= called in app by needs)
#############################

#
# here queries for administrative/general purpose section
#
def get_user_password_hash(conn, email):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT password_hash 
            FROM app_users 
            WHERE mail = %s
              AND enabled = true
        """, (email,))
        result = cur.fetchone()
        return result[0] if result else None


def is_user_enabled(conn, email):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT enabled FROM app_users WHERE mail = %s
        """, (email,))
        result = cur.fetchone()
        return result[0] if result else None


def get_user_name_and_last_login(conn, email):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT name, last_login 
            FROM app_users 
            WHERE mail = %s
        """, (email,))
        return cur.fetchone()


def update_user_password_hash(conn, email, password_hash):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE app_users
            SET password_hash = %s
            WHERE mail = %s
        """, (password_hash, email))
        conn.commit()


def get_user_name_by_email(conn, email):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT name 
            FROM app_users 
            WHERE mail = %s
        """, (email,))
        result = cur.fetchone()
        return result[0] if result else None


def get_full_user_data(conn, email):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT name, mail, last_login
            FROM app_users
            WHERE mail = %s
        """, (email,))
        return cur.fetchone()


def get_random_citation(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT citation
            FROM random_citation
            ORDER BY RANDOM()
            LIMIT 1
        """)
        result = cur.fetchone()
        return result[0] if result else None


def update_last_login(conn, email):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE app_users
            SET last_login = CURRENT_DATE
            WHERE mail = %s
        """, (email,))
        conn.commit()


# For index/dashboard
def get_pg_version():
    return "SELECT version()"


def get_terrain_db_sizes():
    return """
        SELECT datname, pg_database_size(datname)
        FROM pg_database
        WHERE datname ~ '^[0-9]'
    """


# this is getting user role used for session RBAC
def get_user_role():
    return "SELECT group_role FROM app_users WHERE mail = %s"


def get_terrain_db_list(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT datname
            FROM pg_database
            WHERE datname ~ '^[0-9]'
              AND datistemplate = false
              AND datallowconn = true
            ORDER BY datname
        """)
        return [row[0] for row in cur.fetchall()]


def get_all_users():
    return """
        SELECT name, mail, group_role, enabled, last_login 
        FROM app_users
        ORDER BY name
    """


def get_enabled_user_name_by_email(conn, email):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT name 
            FROM app_users 
            WHERE mail = %s AND enabled = true
        """, (email,))
        result = cur.fetchone()
        return result[0] if result else None


# -------------------------------------------------------------------
# queries for data manipulation in terrain DBs
# -------------------------------------------------------------------

def count_sj_by_type(sj_typ):
    # this function returns (sql, params), to parametrise securely
    return "SELECT COUNT(*) FROM tab_sj WHERE sj_typ = %s;", (sj_typ,)


def count_sj_by_type_all():
    return """
        SELECT sj_typ, COUNT(*) 
        FROM tab_sj 
        GROUP BY sj_typ;
    """


def count_total_sj():
    return "SELECT COUNT(*) FROM tab_sj;"


def count_objects():
    return "SELECT COUNT(DISTINCT ref_object) FROM tab_sj WHERE ref_object IS NOT NULL;"


def count_sj_without_relation():
    return """
        SELECT COUNT(*) FROM tab_sj s
        LEFT JOIN (
            SELECT ref_sj1 AS sj FROM tab_sj_stratigraphy
            UNION
            SELECT ref_sj2 AS sj FROM tab_sj_stratigraphy
        ) rel ON s.id_sj = rel.sj
        WHERE rel.sj IS NULL;
    """


def get_stratigraphy_relations():
    return "SELECT ref_sj1, relation, ref_sj2 FROM tab_sj_stratigraphy;"


def get_sj_types_and_objects():
    return "SELECT id_sj, sj_typ, ref_object FROM tab_sj;"


def fetch_stratigraphy_relations(conn):
    sql = """
        SELECT ref_sj1, relation, ref_sj2
        FROM tab_sj_stratigraphy;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()



# --- Harris / SU & Objects queries ---

def get_all_sj_with_types(conn):
    """Return [(id_sj, sj_typ), ...]."""
    with conn.cursor() as cur:
        cur.execute("SELECT id_sj, sj_typ FROM tab_sj;")
        return cur.fetchall()

def get_sj_with_object_refs(conn):
    """Return [(id_sj, ref_object), ...] only rows with ref_object IS NOT NULL."""
    with conn.cursor() as cur:
        cur.execute("SELECT id_sj, ref_object FROM tab_sj WHERE ref_object IS NOT NULL;")
        return cur.fetchall()

def get_all_objects(conn):
    """Return [(id_object, object_typ, superior_object), ...]."""
    with conn.cursor() as cur:
        cur.execute("SELECT id_object, object_typ, superior_object FROM tab_object;")
        return cur.fetchall()
    


# Here queries for polygons handling
# app/queries/polygons.py
# Centralized SQL helpers for polygons & their media bindings.
# Keep ALL raw SQL here so routes stay clean and testable.

# --------------------------
# Listing / reading polygons
# --------------------------

def get_polygons_list():
    """
    Returns (id, polygon_name, number_of_points, srid) for all polygons.
    `ST_SRID(geom)` may be NULL if geom is not yet built.
    """
    return """
        SELECT
            p.id,
            p.polygon_name,
            COALESCE(ST_NPoints(p.geom), 0) AS npoints,
            ST_SRID(p.geom)                 AS srid
        FROM tab_polygons AS p
        ORDER BY p.polygon_name;
    """


# ----------------------------------------------------
# CSV/TXT upload -> direct insert of a polygon geometry
# ----------------------------------------------------

def insert_polygon_sql(polygon_name, points, source_epsg):
    """
    Your original helper (kept compatible):
    Builds a single INSERT with the points inlined as ST_MakePoint(x,y).
    NOTE: It currently transforms to 4326; you later normalize SRID in DB
    via set_project_srid/update_geometry_srid, so this is OK.
    """
    return f"""
        INSERT INTO tab_polygons (polygon_name, geom)
        VALUES (
            %s,
            ST_Transform(
                ST_SetSRID(
                    ST_MakePolygon(
                        ST_MakeLine(ARRAY[
                            {','.join([f"ST_MakePoint({x}, {y})" for x, y in points])}
                        ])
                    ),
                    {int(source_epsg)}
                ),
                4326
            )
        );
    """


# ----------------------------------------------------
# Polygons: SQL helpers (manual create + bindings + rebuild)
# ----------------------------------------------------

def insert_polygon_manual_sql():
    """
    Insert/Upsert polygon metadata (no geometries). 'parent_name' optional.
    Params: (polygon_name, parent_name, allocation_reason, notes)
    """
    return """
        INSERT INTO tab_polygons (polygon_name, parent_name, allocation_reason, notes)
        VALUES (%s, NULLIF(%s,''), %s, NULLIF(%s,''))
        ON CONFLICT (polygon_name)
        DO UPDATE SET
            parent_name = EXCLUDED.parent_name,
            allocation_reason = EXCLUDED.allocation_reason,
            notes = EXCLUDED.notes;
    """

def delete_bindings_top_sql():
    """Delete all TOP bindings for a polygon. Params: (polygon_name,)"""
    return "DELETE FROM tab_polygon_geopts_binding_top WHERE ref_polygon=%s;"

def delete_bindings_bottom_sql():
    """Delete all BOTTOM bindings for a polygon. Params: (polygon_name,)"""
    return "DELETE FROM tab_polygon_geopts_binding_bottom WHERE ref_polygon=%s;"

def insert_binding_top_sql():
    """
    Insert one TOP range (FROM..TO) for a polygon.
    Params: (ref_polygon, pts_from, pts_to)
    """
    return """
        INSERT INTO tab_polygon_geopts_binding_top (ref_polygon, pts_from, pts_to)
        VALUES (%s, %s, %s)
        ON CONFLICT (ref_polygon, pts_from, pts_to) DO NOTHING;
    """

def insert_binding_bottom_sql():
    """
    Insert one BOTTOM range (FROM..TO) for a polygon.
    Params: (ref_polygon, pts_from, pts_to)
    """
    return """
        INSERT INTO tab_polygon_geopts_binding_bottom (ref_polygon, pts_from, pts_to)
        VALUES (%s, %s, %s)
        ON CONFLICT (ref_polygon, pts_from, pts_to) DO NOTHING;
    """

def rebuild_geom_sql():
    """
    Rebuilds both geom_top and geom_bottom from geodetic points for given polygon.
    Params: (polygon_name,)
    """
    return "SELECT rebuild_polygon_geoms_from_geopts(%s);"

def select_polygons_with_bindings_sql():
    """Select polygon names that have any TOP/BOTTOM bindings."""
    return """
        SELECT DISTINCT ref_polygon
        FROM (
          SELECT ref_polygon FROM tab_polygon_geopts_binding_top
          UNION
          SELECT ref_polygon FROM tab_polygon_geopts_binding_bottom
        ) s
        ORDER BY ref_polygon;
    """


# -----------------------
# Authors (for <select>)
# -----------------------

def list_authors_sql():
    """
    Returns authors' emails for dropdowns.
    """
    return "SELECT mail FROM gloss_personalia ORDER BY mail;"


# -------------------------
# Shapefile export helpers
# -------------------------

def find_polygons_srid_sql():
    """
    Returns the SRID of tab_polygons.geom for the current schema.
    """
    return "SELECT Find_SRID(current_schema(), 'tab_polygons', 'geom');"


def srtext_by_srid_sql():
    """
    Returns SR-Text (WKT) from spatial_ref_sys for a given SRID.
    Params: (srid,)
    """
    return "SELECT srtext FROM spatial_ref_sys WHERE srid = %s;"


def polygons_geojson_sql():
    """
    Returns (polygon_name, ST_AsGeoJSON(geom)) for all polygons with non-NULL geom.
    """
    return """
        SELECT polygon_name, ST_AsGeoJSON(geom)
        FROM tab_polygons
        WHERE geom IS NOT NULL;
    """


# ------------------------------------
# Media: Photos / Sketches / Photograms
# ------------------------------------
# Expected tables/columns (based on our earlier DDL discussion):
#
# tab_photos(
#   id_photo VARCHAR PRIMARY KEY,
#   photo_typ TEXT NOT NULL,
#   datum DATE NOT NULL,
#   author VARCHAR NOT NULL REFERENCES gloss_personalia(mail),
#   notes TEXT,
#   mime_type TEXT NOT NULL,
#   file_size BIGINT NOT NULL,
#   checksum_sha256 TEXT NOT NULL,
#   shoot_datetime TIMESTAMPTZ NULL,
#   gps_lat DOUBLE PRECISION NULL,
#   gps_lon DOUBLE PRECISION NULL,
#   gps_alt DOUBLE PRECISION NULL,
#   exif_json JSONB NULL
# )
#
# tabaid_polygon_photos(ref_polygon INT REFERENCES tab_polygons(id), ref_photo VARCHAR REFERENCES tab_photos(id_photo))
#
# tab_sketches(
#   id_sketch VARCHAR PRIMARY KEY,
#   sketch_typ TEXT NOT NULL,
#   author VARCHAR NOT NULL REFERENCES gloss_personalia(mail),
#   datum DATE NOT NULL,
#   notes TEXT,
#   mime_type TEXT NOT NULL,
#   file_size BIGINT NOT NULL,
#   checksum_sha256 TEXT NOT NULL
# )
#
# tabaid_polygon_sketches(ref_polygon INT REFERENCES tab_polygons(id), ref_sketch VARCHAR REFERENCES tab_sketches(id_sketch))
#
# tab_photograms(
#   id_photogram VARCHAR PRIMARY KEY,
#   photogram_typ TEXT NOT NULL,
#   ref_sketch VARCHAR NULL REFERENCES tab_sketches(id_sketch),
#   notes TEXT,
#   mime_type TEXT NOT NULL,
#   file_size BIGINT NOT NULL,
#   checksum_sha256 TEXT NOT NULL
# )
#
# tabaid_polygon_photograms(ref_polygon INT REFERENCES tab_polygons(id), ref_photogram VARCHAR REFERENCES tab_photograms(id_photogram))


def insert_photo_sql():
    """
    Insert one photo metadata row.
    Params:
      (id_photo, photo_typ, datum, author, notes,
       mime_type, file_size, checksum_sha256,
       shoot_datetime, gps_lat, gps_lon, gps_alt, exif_json)
    """
    return """
        INSERT INTO tab_photos (
            id_photo, photo_typ, datum, author, notes,
            mime_type, file_size, checksum_sha256,
            shoot_datetime, gps_lat, gps_lon, gps_alt, exif_json
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s, %s
        );
    """


def bind_photo_to_polygon_sql():
    """
    Bind an existing photo to a polygon (M:N).
    Params: (ref_polygon, ref_photo)
    """
    return """
        INSERT INTO tabaid_polygon_photos (ref_polygon, ref_photo)
        VALUES (%s, %s);
    """


def insert_sketch_sql():
    """
    Insert one sketch metadata row.
    Params:
      (id_sketch, sketch_typ, author, datum, notes,
       mime_type, file_size, checksum_sha256)
    """
    return """
        INSERT INTO tab_sketches (
            id_sketch, sketch_typ, author, datum, notes,
            mime_type, file_size, checksum_sha256
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
    """


def bind_sketch_to_polygon_sql():
    """
    Bind an existing sketch to a polygon (M:N).
    Params: (ref_polygon, ref_sketch)
    """
    return """
        INSERT INTO tabaid_polygon_sketches (ref_polygon, ref_sketch)
        VALUES (%s, %s);
    """


def insert_photogram_sql():
    """
    Insert one photogram metadata row.
    Params:
      (id_photogram, photogram_typ, notes,
       mime_type, file_size, checksum_sha256)
    Note: ref_sketch is optional and managed elsewhere if needed.
    """
    return """
        INSERT INTO tab_photograms (
            id_photogram, photogram_typ, notes,
            mime_type, file_size, checksum_sha256
        )
        VALUES (%s, %s, %s, %s, %s, %s);
    """


def bind_photogram_to_polygon_sql():
    """
    Bind an existing photogram to a polygon (M:N).
    Params: (ref_polygon, ref_photogram)
    """
    return """
        INSERT INTO tabaid_polygon_photograms (ref_polygon, ref_photogram)
        VALUES (%s, %s);
    """


