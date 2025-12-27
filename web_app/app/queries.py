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
    Minimal list for UI.

    Returns:
      id (row_number for display),
      name (polygon_name),
      npoints (sum of vertices in geom_top+geom_bottom),
      srid (from first non-null geom; NULL if SRID=0),
      parent (parent_name),
      allocation_reason (text),
      has_top (binding exists),
      has_bottom (binding exists)
    """
    return """
        SELECT
            ROW_NUMBER() OVER (ORDER BY p.polygon_name) AS id,
            p.polygon_name                              AS name,

            (COALESCE(ST_NPoints(p.geom_top), 0) +
             COALESCE(ST_NPoints(p.geom_bottom), 0))    AS npoints,

            NULLIF(
              ST_SRID(COALESCE(p.geom_top, p.geom_bottom)),
              0
            )                                           AS srid,

            p.parent_name                               AS parent,
            p.allocation_reason::text                   AS allocation_reason,

            EXISTS (
              SELECT 1
              FROM tab_polygon_geopts_binding_top bt
              WHERE bt.ref_polygon = p.polygon_name
              LIMIT 1
            )                                           AS has_top,

            EXISTS (
              SELECT 1
              FROM tab_polygon_geopts_binding_bottom bb
              WHERE bb.ref_polygon = p.polygon_name
              LIMIT 1
            )                                           AS has_bottom

        FROM tab_polygons p
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
    return "DELETE FROM tab_polygon_geopts_binding_top WHERE ref_polygon=%s;"

def delete_bindings_bottom_sql():
    return "DELETE FROM tab_polygon_geopts_binding_bottom WHERE ref_polygon=%s;"

def insert_binding_top_sql():
    return """
        INSERT INTO tab_polygon_geopts_binding_top (ref_polygon, pts_from, pts_to)
        VALUES (%s, %s, %s)
        ON CONFLICT (ref_polygon, pts_from, pts_to) DO NOTHING;
    """

def insert_binding_bottom_sql():
    return """
        INSERT INTO tab_polygon_geopts_binding_bottom (ref_polygon, pts_from, pts_to)
        VALUES (%s, %s, %s)
        ON CONFLICT (ref_polygon, pts_from, pts_to) DO NOTHING;
    """


def select_polygons_with_bindings_sql():
    return """
        SELECT DISTINCT ref_polygon
        FROM (
          SELECT ref_polygon FROM tab_polygon_geopts_binding_top
          UNION
          SELECT ref_polygon FROM tab_polygon_geopts_binding_bottom
        ) s
        ORDER BY ref_polygon;
    """

def rebuild_geom_sql():
    """
    Rebuilds both geom_top and geom_bottom from geodetic points for given polygon.
    Params: (polygon_name,)
    """
    return "SELECT rebuild_polygon_geoms_from_geopts(%s);"

def find_geopts_srid_sql():
    """
    Returns SRID assigned to tab_geopts.pts_geom typmod (after set_project_srid).
    Casts current_schema() to text to match PostGIS Find_SRID signature.
    """
    return "SELECT Find_SRID(current_schema()::text, 'tab_geopts'::text, 'pts_geom'::text);"


def upsert_geopt_sql():
    """
    Upsert into tab_geopts with XY transformed from source_epsg -> target_srid.
    Params: (x_src, y_src, h_src, source_epsg, target_srid, id_pts, h_src, code)
    Note: Z (h) is stored as provided (no vertical transform).
    """
    return """
        WITH p AS (
            SELECT ST_Transform(
                       ST_SetSRID(ST_MakePoint(%s, %s, %s), %s),
                       %s
                   ) AS g
        )
        INSERT INTO tab_geopts (id_pts, x, y, h, code)
        SELECT
            %s,
            ST_X(p.g),
            ST_Y(p.g),
            %s,
            CASE
              WHEN NULLIF(BTRIM(%s), '') IS NULL THEN NULL
              WHEN UPPER(BTRIM(%s)) IN ('SU','FX','EP','FP','NI','PF','SP')
                THEN UPPER(BTRIM(%s))::geopt_code
              ELSE NULL
            END
        FROM p
        ON CONFLICT (id_pts) DO UPDATE SET
            x    = EXCLUDED.x,
            y    = EXCLUDED.y,
            h    = EXCLUDED.h,
            code = EXCLUDED.code;
    """


def polygon_geoms_geojson_sql():
    """
    Returns (geom_top_geojson, geom_bottom_geojson) for a polygon_name.
    Geoms are transformed to EPSG:4326 and forced to 2D for Leaflet.
    Params: (polygon_name,)
    """
    return """
        SELECT
            CASE
              WHEN geom_top IS NULL THEN NULL
              ELSE ST_AsGeoJSON(ST_Force2D(ST_Transform(geom_top, 4326)))
            END AS top_gj,
            CASE
              WHEN geom_bottom IS NULL THEN NULL
              ELSE ST_AsGeoJSON(ST_Force2D(ST_Transform(geom_bottom, 4326)))
            END AS bottom_gj
        FROM tab_polygons
        WHERE polygon_name = %s;
    """


def find_polygons_srid_sql():
    """
    Returns SRID of tab_polygons geometry typmod.
    Prefer geom_top, fallback to geom_bottom.
    Casts to text to satisfy Find_SRID signature.
    """
    return """
        SELECT NULLIF(Find_SRID(current_schema()::text, 'tab_polygons'::text, 'geom_top'::text), 0) AS srid
        UNION ALL
        SELECT NULLIF(Find_SRID(current_schema()::text, 'tab_polygons'::text, 'geom_bottom'::text), 0) AS srid
        LIMIT 1;
    """


def polygons_geojson_top_bottom_sql():
    """
    Returns (polygon_name, top_geojson, bottom_geojson) for all polygons.
    Geoms are forced to 2D for shapefile.
    """
    return """
        SELECT
            polygon_name,
            CASE
              WHEN geom_top IS NULL THEN NULL
              ELSE ST_AsGeoJSON(ST_Force2D(geom_top))
            END AS top_gj,
            CASE
              WHEN geom_bottom IS NULL THEN NULL
              ELSE ST_AsGeoJSON(ST_Force2D(geom_bottom))
            END AS bottom_gj
        FROM tab_polygons
        WHERE geom_top IS NOT NULL OR geom_bottom IS NOT NULL
        ORDER BY polygon_name;
    """

# parent a children are important when deleting polygons - children are "reparented" to grandfather
def get_polygon_parent_sql():
    """Get parent_name for polygon. Params: (polygon_name,)"""
    return """
        SELECT parent_name
        FROM tab_polygons
        WHERE polygon_name = %s;
    """

def reparent_children_sql():
    """
    Re-parent direct children of a polygon to a new parent (possibly NULL).
    Params: (new_parent_name, old_parent_name)
    """
    return """
        UPDATE tab_polygons
        SET parent_name = %s
        WHERE parent_name = %s;
    """


def delete_polygon_sql():
    """Delete polygon by name. Params: (polygon_name,)"""
    return "DELETE FROM tab_polygons WHERE polygon_name = %s;"


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

# -------------------------
# SQLs for media handling
# -------------------------

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

def insert_drawing_sql():
    """
    Insert one drawing metadata row.

    Params:
      (id_drawing, author, datum, notes,
       mime_type, file_size, checksum_sha256)
    """
    return """
        INSERT INTO tab_drawings (
            id_drawing, author, datum, notes,
            mime_type, file_size, checksum_sha256
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """


# -------------------------
# Polygons ↔ media helpers
# -------------------------

def polygon_exists_sql():
    """Check polygon exists by polygon_name. Params: (polygon_name,)"""
    return "SELECT 1 FROM tab_polygons WHERE polygon_name = %s;"


def link_polygon_photo_sql():
    """Params: (polygon_name, id_photo)"""
    return """
        INSERT INTO tabaid_polygon_photos (ref_polygon, ref_photo)
        VALUES (%s, %s);
    """

def link_polygon_sketch_sql():
    """Params: (polygon_name, id_sketch)"""
    return """
        INSERT INTO tabaid_polygon_sketches (ref_polygon, ref_sketch)
        VALUES (%s, %s);
    """

def link_polygon_photogram_sql():
    """Params: (polygon_name, id_photogram)"""
    return """
        INSERT INTO tabaid_polygon_photograms (ref_polygon, ref_photogram)
        VALUES (%s, %s);
    """

def polygons_geojson_top_bottom_sql():
    return """
        SELECT
            polygon_name,
            CASE WHEN geom_top IS NOT NULL
              THEN ST_AsGeoJSON(ST_Transform(ST_Force2D(geom_top), 4326))
              ELSE NULL END AS top_gj,
            CASE WHEN geom_bottom IS NOT NULL
              THEN ST_AsGeoJSON(ST_Transform(ST_Force2D(geom_bottom), 4326))
              ELSE NULL END AS bottom_gj
        FROM tab_polygons
        ORDER BY polygon_name;
    """


def polygons_hierarchy_sql():
    """Returns (polygon_name, parent_name) for hierarchy diagram."""
    return """
        SELECT polygon_name, parent_name
        FROM tab_polygons
        ORDER BY polygon_name;
    """

# ----------------------------------------------------
# Sections: SQL helpers (manual create + bindings + SJ links)
# ----------------------------------------------------

def get_sections_list_sql():
    """
    Listing for /sections:
      - srid_txt: SRID inferred from geopts used by section (— / <srid> / mixed)
      - ranges_txt: e.g. "1-4, 7-9, 12-13"
      - sj_nr: count of linked SJs
    """
    return """
        WITH r AS (
            SELECT
                b.ref_section::int4 AS id_section,
                STRING_AGG((b.pts_from::text || '-' || b.pts_to::text), ', ' ORDER BY b.pts_from, b.pts_to) AS ranges_txt
            FROM tab_section_geopts_binding b
            GROUP BY b.ref_section::int4
        ),
        sj AS (
            SELECT
                x.ref_section::int4 AS id_section,
                COUNT(*)::int AS sj_nr
            FROM tabaid_sj_section x
            GROUP BY x.ref_section::int4
        ),
        sr AS (
            SELECT
                b.ref_section::int4 AS id_section,
                CASE
                    WHEN COUNT(g.id_pts) = 0 THEN '—'
                    WHEN COUNT(DISTINCT ST_SRID(g.pts_geom)) = 1 THEN MIN(ST_SRID(g.pts_geom))::text
                    ELSE 'mixed'
                END AS srid_txt
            FROM tab_section_geopts_binding b
            LEFT JOIN tab_geopts g
              ON g.id_pts BETWEEN b.pts_from AND b.pts_to
            GROUP BY b.ref_section::int4
        )
        SELECT
            s.id_section,
            s.section_type,
            s.description,
            COALESCE(sr.srid_txt, '—') AS srid_txt,
            COALESCE(r.ranges_txt, '—') AS ranges_txt,
            COALESCE(sj.sj_nr, 0) AS sj_nr
        FROM tab_section s
        LEFT JOIN r  ON r.id_section  = s.id_section
        LEFT JOIN sj ON sj.id_section = s.id_section
        LEFT JOIN sr ON sr.id_section = s.id_section
        ORDER BY s.id_section;
    """


def list_sj_ids_sql():
    """Simple list of SJ IDs for multi-select."""
    return "SELECT id_sj FROM tab_sj ORDER BY id_sj;"


def upsert_section_manual_sql():
    """
    Upsert section metadata.
    Params: (id_section, section_type, description)
    """
    return """
        INSERT INTO tab_section (id_section, section_type, description)
        VALUES (%s, %s, NULLIF(%s,''))
        ON CONFLICT (id_section)
        DO UPDATE SET
          section_type = EXCLUDED.section_type,
          description  = EXCLUDED.description;
    """


def delete_section_geopts_bindings_sql():
    """Params: (id_section,)"""
    return "DELETE FROM tab_section_geopts_binding WHERE ref_section = %s;"


def insert_section_geopts_binding_sql():
    """Params: (id_section, pts_from, pts_to)"""
    return """
        INSERT INTO tab_section_geopts_binding (ref_section, pts_from, pts_to)
        VALUES (%s, %s, %s)
        ON CONFLICT (ref_section, pts_from, pts_to) DO NOTHING;
    """


def delete_section_sj_links_sql():
    """Delete M:N links SECTION→SJ. Params: (id_section,)"""
    return "DELETE FROM tabaid_sj_section WHERE ref_section = %s;"


def insert_section_sj_link_sql():
    """
    Insert one SECTION↔SJ link.
    Params: (ref_sj, ref_section)
    Tip: if you add UNIQUE(ref_sj, ref_section), you can safely DO NOTHING on conflict.
    """
    return """
        INSERT INTO tabaid_sj_section (ref_sj, ref_section)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING;
    """


def section_exists_sql():
    """Check section exists. Params: (id_section,)"""
    return "SELECT 1 FROM tab_section WHERE id_section = %s;"


# -------------------------
# Sections ↔ media helpers
# -------------------------

def link_section_photo_sql():
    """Params: (id_section, id_photo)"""
    return """
        INSERT INTO tabaid_section_photos (ref_section, ref_photo)
        VALUES (%s, %s);
    """

def link_section_sketch_sql():
    """Params: (id_section, id_sketch)"""
    return """
        INSERT INTO tabaid_section_sketches (ref_section, ref_sketch)
        VALUES (%s, %s);
    """

def link_section_photogram_sql():
    """Params: (id_section, id_photogram)"""
    return """
        INSERT INTO tabaid_section_photograms (ref_section, ref_photogram)
        VALUES (%s, %s);
    """

def link_section_drawing_sql():
    """Params: (id_section, id_drawing)"""
    return """
        INSERT INTO tabaid_section_drawings (ref_section, ref_drawing)
        VALUES (%s, %s);
    """

def select_sections_with_bindings_sql():
    """
    Returns section IDs that have at least one binding row.
    """
    return """
        SELECT DISTINCT ref_section::int4
        FROM tab_section_geopts_binding
        ORDER BY ref_section::int4;
    """


def section_line_geojson_by_id_sql():
    """
    Returns one row: (line_geojson) for given section id, built from bindings + tab_geopts.
    Line is built ascending by id_pts, duplicates removed.
    Params: (id_section,)
    """
    return """
        WITH pts AS (
            SELECT
                g.id_pts,
                g.pts_geom
            FROM tab_section_geopts_binding b
            JOIN tab_geopts g
              ON g.id_pts BETWEEN b.pts_from AND b.pts_to
            WHERE b.ref_section::int4 = %s
        ),
        dpts AS (
            SELECT DISTINCT ON (id_pts) id_pts, pts_geom
            FROM pts
            ORDER BY id_pts
        )
        SELECT
            CASE
              WHEN COUNT(*) < 2 THEN NULL
              ELSE ST_AsGeoJSON(ST_Force2D(ST_MakeLine(pts_geom ORDER BY id_pts)))
            END AS line_gj
        FROM dpts;
    """


def sections_lines_geojson_sql():
    """
    Returns (id_section, line_geojson) for ALL sections, built from bindings + tab_geopts.
    Line is built ascending by id_pts, duplicates removed.
    """
    return """
        WITH pts AS (
            SELECT
                b.ref_section::int4 AS id_section,
                g.id_pts,
                g.pts_geom
            FROM tab_section_geopts_binding b
            JOIN tab_geopts g
              ON g.id_pts BETWEEN b.pts_from AND b.pts_to
        ),
        dpts AS (
            SELECT DISTINCT ON (id_section, id_pts)
                id_section, id_pts, pts_geom
            FROM pts
            ORDER BY id_section, id_pts
        )
        SELECT
            id_section,
            CASE
              WHEN COUNT(*) < 2 THEN NULL
              ELSE ST_AsGeoJSON(ST_Force2D(ST_MakeLine(pts_geom ORDER BY id_pts)))
            END AS line_gj
        FROM dpts
        GROUP BY id_section
        ORDER BY id_section;
    """
