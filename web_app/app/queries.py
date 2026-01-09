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
# SQLs for SUs (stratigraphic units)
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

def list_polygon_names_sql():
    return "SELECT polygon_name FROM tab_polygons ORDER BY polygon_name;"


def list_su_for_media_select_sql():
    """
    Used for Attach graphic documentation section.
    Keep it simple: show last SUs first.
    """
    return """
        SELECT id_sj, COALESCE(sj_typ, ''), COALESCE(description, '')
        FROM tab_sj
        ORDER BY id_sj DESC;
    """


def list_last_su_sql(limit=10):
    return f"""
        SELECT id_sj, COALESCE(sj_typ, ''), COALESCE(description, ''), recorded, COALESCE(author,'')
        FROM tab_sj
        ORDER BY id_sj DESC
        LIMIT {int(limit)};
    """


def insert_sj_polygon_link_sql():
    """
    Idempotent insert (M:N).
    """
    return """
        INSERT INTO tabaid_sj_polygon (ref_sj, ref_polygon)
        VALUES (%s, %s)
        ON CONFLICT (ref_sj, ref_polygon) DO NOTHING;
    """


def delete_su_sql():
    return "DELETE FROM tab_sj WHERE id_sj=%s;"



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
# Sections: SQL helpers (manual create + bindings + SU links)
# ----------------------------------------------------

def get_sections_list_sql():
    """
    Listing for /sections:
      - srid_txt: SRID inferred from geopts used by section (— / <srid> / mixed)
      - ranges_txt: e.g. "1-4, 7-9, 12-13"
      - sj_nr: count of linked SUs
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
    """Simple list of SUs IDs for multi-select."""
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
    """Delete M:N links SECTION→SU. Params: (id_section,)"""
    return "DELETE FROM tabaid_sj_section WHERE ref_section = %s;"


def insert_section_sj_link_sql():
    """
    Insert one SECTION↔SU link.
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


#############################
## Geodesy queries
#############################

def list_geopts_sql():
    """
    List points (for modal table).
    Params: (q_like, q_like, id_from, id_to, limit)
    """
    return """
      SELECT id_pts, x, y, h, code::text AS code, notes
      FROM tab_geopts
      WHERE
        (
          %s IS NULL
          OR code::text ILIKE %s
          OR notes ILIKE %s
        )
        AND (%s IS NULL OR id_pts >= %s)
        AND (%s IS NULL OR id_pts <= %s)
      ORDER BY id_pts
      LIMIT %s;
    """


def delete_geopt_sql():
    return "DELETE FROM tab_geopts WHERE id_pts = %s;"


def update_geopt_sql():
    """
    Update x,y,h,code,notes. Trigger will maintain pts_geom.
    Params: (x, y, h, code, code, code, notes, id_pts)
    """
    return """
      UPDATE tab_geopts
      SET
        x = %s,
        y = %s,
        h = %s,
        code = CASE
                 WHEN NULLIF(BTRIM(%s), '') IS NULL THEN NULL
                 WHEN UPPER(BTRIM(%s)) IN ('SU','FX','EP','FP','NI','PF','SP')
                   THEN UPPER(BTRIM(%s))::geopt_code
                 ELSE NULL
               END,
        notes = NULLIF(%s, '')
      WHERE id_pts = %s;
    """


def geojson_geopts_bbox_sql():
    """
    Returns FeatureCollection of points inside bbox (bbox in EPSG:4326).
    Params: (minx, miny, maxx, maxy, target_srid, code_filter, q_like, q_like, id_from, id_to, limit)
    """
    return """
      WITH
      bbox AS (
        SELECT ST_Transform(
                 ST_MakeEnvelope(%s, %s, %s, %s, 4326),
                 %s
               ) AS g
      ),
      pts AS (
        SELECT
          g.id_pts,
          g.code::text AS code,
          g.notes,
          ST_Transform(g.pts_geom, 4326) AS geom_4326
        FROM tab_geopts g, bbox b
        WHERE g.pts_geom IS NOT NULL
          AND ST_Intersects(g.pts_geom, b.g)
          AND (%s IS NULL OR g.code::text = %s)
          AND (
            %s IS NULL
            OR g.notes ILIKE %s
            OR g.code::text ILIKE %s
          )
          AND (%s IS NULL OR g.id_pts >= %s)
          AND (%s IS NULL OR g.id_pts <= %s)
        ORDER BY g.id_pts
        LIMIT %s
      )
      SELECT json_build_object(
        'type', 'FeatureCollection',
        'features', COALESCE(json_agg(
          json_build_object(
            'type', 'Feature',
            'geometry', ST_AsGeoJSON(geom_4326)::json,
            'properties', json_build_object(
              'id_pts', id_pts,
              'code', code,
              'notes', notes
            )
          )
        ), '[]'::json)
      )
      FROM pts;
    """


def geojson_polygons_bbox_sql():
    """
    Overlay polygons (geom_top) inside bbox (bbox in EPSG:4326).
    Params: (minx, miny, maxx, maxy, target_srid, limit)
    """
    return """
      WITH
      bbox AS (
        SELECT ST_Transform(
                 ST_MakeEnvelope(%s, %s, %s, %s, 4326),
                 %s
               ) AS g
      ),
      polys AS (
        SELECT
          p.polygon_name,
          ST_Transform(p.geom_top, 4326) AS geom_4326
        FROM tab_polygons p, bbox b
        WHERE p.geom_top IS NOT NULL
          AND ST_Intersects(p.geom_top, b.g)
        ORDER BY p.polygon_name
        LIMIT %s
      )
      SELECT json_build_object(
        'type', 'FeatureCollection',
        'features', COALESCE(json_agg(
          json_build_object(
            'type', 'Feature',
            'geometry', ST_AsGeoJSON(geom_4326)::json,
            'properties', json_build_object('polygon_name', polygon_name)
          )
        ), '[]'::json)
      )
      FROM polys;
    """


def geojson_photos_bbox_sql():
    """
    Photo centroids from tab_photos (gps_lon, gps_lat, gps_alt). Assumed WGS84.
    Params: (minx, miny, maxx, maxy, limit)
    """
    return """
      WITH
      bbox AS (
        SELECT ST_MakeEnvelope(%s, %s, %s, %s, 4326) AS g
      ),
      ph AS (
        SELECT
          id_foto,
          file_name,
          gps_lat,
          gps_lon,
          gps_alt,
          ST_SetSRID(ST_MakePoint(gps_lon, gps_lat, COALESCE(gps_alt, 0)), 4326) AS geom_4326
        FROM tab_photos
        WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL
        LIMIT %s
      ),
      inside AS (
        SELECT *
        FROM ph, bbox
        WHERE ST_Intersects(ph.geom_4326, bbox.g)
      )
      SELECT json_build_object(
        'type', 'FeatureCollection',
        'features', COALESCE(json_agg(
          json_build_object(
            'type', 'Feature',
            'geometry', ST_AsGeoJSON(geom_4326)::json,
            'properties', json_build_object(
              'id_foto', id_foto,
              'file_name', file_name,
              'gps_alt', gps_alt
            )
          )
        ), '[]'::json)
      )
      FROM inside;
    """

# this query serves for getting extent of geodesy points - then used for scaling map automatically
def geopts_extent_4326_sql():
    """
    Returns bbox of tab_geopts points in EPSG:4326.
    Output: (minx, miny, maxx, maxy) or all NULL if no points.
    """
    return """
      WITH e AS (
        SELECT ST_Extent(ST_Transform(pts_geom, 4326)) AS ext
        FROM tab_geopts
        WHERE pts_geom IS NOT NULL
      )
      SELECT
        ST_XMin(ext), ST_YMin(ext), ST_XMax(ext), ST_YMax(ext)
      FROM e;
    """

# -------------------------
# Finds & Samples (glossaries + CRUD + linking)
# -------------------------

def list_find_types_sql():
    """Return active find types for dropdown. No params."""
    return """
        SELECT type_code
        FROM gloss_find_type
        WHERE is_active IS TRUE
        ORDER BY sort_order, type_code;
    """


def insert_find_type_sql():
    """Params: (type_code,)"""
    return """
        INSERT INTO gloss_find_type (type_code)
        VALUES (LOWER(BTRIM(%s)))
        ON CONFLICT (type_code) DO NOTHING;
    """


def list_sample_types_sql():
    """Return active sample types for dropdown. No params."""
    return """
        SELECT type_code
        FROM gloss_sample_type
        WHERE is_active IS TRUE
        ORDER BY sort_order, type_code;
    """


def insert_sample_type_sql():
    """Params: (type_code,)"""
    return """
        INSERT INTO gloss_sample_type (type_code)
        VALUES (LOWER(BTRIM(%s)))
        ON CONFLICT (type_code) DO NOTHING;
    """


def list_polygons_names_sql():
    """Return polygon names for dropdown. No params."""
    return """
        SELECT polygon_name
        FROM tab_polygons
        ORDER BY polygon_name;
    """


def find_exists_sql():
    """Params: (id_find,)"""
    return "SELECT 1 FROM tab_finds WHERE id_find = %s;"


def sample_exists_sql():
    """Params: (id_sample,)"""
    return "SELECT 1 FROM tab_samples WHERE id_sample = %s;"


def insert_find_sql():
    """
    Params:
      (id_find, ref_find_type, description, count, ref_sj, ref_geopt, ref_polygon, box)
    """
    return """
        INSERT INTO tab_finds (
            id_find, ref_find_type, description, count, ref_sj, ref_geopt, ref_polygon, box
        )
        VALUES (%s, %s, NULLIF(%s,''), %s, %s, %s, NULLIF(%s,''), %s);
    """


def update_find_sql():
    """
    Params:
      (ref_find_type, description, count, ref_sj, ref_geopt, ref_polygon, box, id_find)
    """
    return """
        UPDATE tab_finds SET
          ref_find_type = %s,
          description   = NULLIF(%s,''),
          count         = %s,
          ref_sj        = %s,
          ref_geopt     = %s,
          ref_polygon   = NULLIF(%s,''),
          box           = %s
        WHERE id_find = %s;
    """


def delete_find_sql():
    """Params: (id_find,)"""
    return "DELETE FROM tab_finds WHERE id_find = %s;"


def list_finds_sql():
    """Params: (limit,)"""
    return """
        SELECT
          id_find, ref_find_type, ref_sj, count, box,
          ref_polygon, ref_geopt,
          COALESCE(description,'') AS description
        FROM tab_finds
        ORDER BY id_find DESC
        LIMIT %s;
    """


def get_find_sql():
    """Params: (id_find,)"""
    return """
        SELECT
          id_find, ref_find_type, ref_sj, count, box,
          ref_polygon, ref_geopt,
          COALESCE(description,'') AS description
        FROM tab_finds
        WHERE id_find = %s;
    """


def insert_sample_sql():
    """
    Params:
      (id_sample, ref_sample_type, description, ref_sj, ref_geopt, ref_polygon)
    """
    return """
        INSERT INTO tab_samples (
            id_sample, ref_sample_type, description, ref_sj, ref_geopt, ref_polygon
        )
        VALUES (%s, %s, NULLIF(%s,''), %s, %s, NULLIF(%s,''));
    """


def update_sample_sql():
    """
    Params:
      (ref_sample_type, description, ref_sj, ref_geopt, ref_polygon, id_sample)
    """
    return """
        UPDATE tab_samples SET
          ref_sample_type = %s,
          description     = NULLIF(%s,''),
          ref_sj          = %s,
          ref_geopt       = %s,
          ref_polygon     = NULLIF(%s,'')
        WHERE id_sample = %s;
    """


def delete_sample_sql():
    """Params: (id_sample,)"""
    return "DELETE FROM tab_samples WHERE id_sample = %s;"


def list_samples_sql():
    """Params: (limit,)"""
    return """
        SELECT
          id_sample, ref_sample_type, ref_sj,
          ref_polygon, ref_geopt,
          COALESCE(description,'') AS description
        FROM tab_samples
        ORDER BY id_sample DESC
        LIMIT %s;
    """


def get_sample_sql():
    """Params: (id_sample,)"""
    return """
        SELECT
          id_sample, ref_sample_type, ref_sj,
          ref_polygon, ref_geopt,
          COALESCE(description,'') AS description
        FROM tab_samples
        WHERE id_sample = %s;
    """



# -------------------------
# Finds & Samples: link media
# -------------------------

def link_find_photo_sql():
    """Idempotent link. Params: (id_find, id_photo, id_find, id_photo)"""
    return """
        INSERT INTO tabaid_finds_photos (ref_find, ref_photo)
        SELECT %s, %s
        WHERE NOT EXISTS (
          SELECT 1 FROM tabaid_finds_photos
          WHERE ref_find = %s AND ref_photo = %s
        );
    """


def link_find_sketch_sql():
    """Idempotent link. Params: (id_find, id_sketch, id_find, id_sketch)"""
    return """
        INSERT INTO tabaid_finds_sketches (ref_find, ref_sketch)
        SELECT %s, %s
        WHERE NOT EXISTS (
          SELECT 1 FROM tabaid_finds_sketches
          WHERE ref_find = %s AND ref_sketch = %s
        );
    """


def link_sample_photo_sql():
    """Idempotent link. Params: (id_sample, id_photo, id_sample, id_photo)"""
    return """
        INSERT INTO tabaid_samples_photos (ref_sample, ref_photo)
        SELECT %s, %s
        WHERE NOT EXISTS (
          SELECT 1 FROM tabaid_samples_photos
          WHERE ref_sample = %s AND ref_photo = %s
        );
    """


def link_sample_sketch_sql():
    """Idempotent link. Params: (id_sample, id_sketch, id_sample, id_sketch)"""
    return """
        INSERT INTO tabaid_samples_sketches (ref_sample, ref_sketch)
        SELECT %s, %s
        WHERE NOT EXISTS (
          SELECT 1 FROM tabaid_samples_sketches
          WHERE ref_sample = %s AND ref_sketch = %s
        );
    """



# -------------------------
# SQLs for MEDIA/PHOTO handling (helpers for photos route)
# -------------------------

def photo_exists_sql():
    return "SELECT 1 FROM tab_photos WHERE id_photo = %s LIMIT 1;"


def checksum_exists_sql():
    return "SELECT 1 FROM tab_photos WHERE checksum_sha256 = %s LIMIT 1;"


def update_photo_sql():
    """
    Params: (photo_typ, datum, author, notes, id_photo)
    """
    return """
        UPDATE tab_photos
           SET photo_typ = %s,
               datum = %s,
               author = %s,
               notes = %s
         WHERE id_photo = %s;
    """


def delete_photo_sql():
    return "DELETE FROM tab_photos WHERE id_photo = %s;"


def get_photo_sql():
    return """
        SELECT
            id_photo, photo_typ, datum, author, notes,
            mime_type, file_size, checksum_sha256,
            shoot_datetime, gps_lat, gps_lon, gps_alt
        FROM tab_photos
        WHERE id_photo = %s;
    """


def list_photos_sql(where_sql: str = "", order_sql: str = "", limit_sql: str = ""):
    base = """
        SELECT
            p.id_photo, p.photo_typ, p.datum, p.author, p.notes,
            p.mime_type, p.file_size, p.checksum_sha256,
            p.shoot_datetime, p.gps_lat, p.gps_lon, p.gps_alt
        FROM tab_photos p
    """
    return base + "\n" + (where_sql or "") + "\n" + (order_sql or "") + "\n" + (limit_sql or "") + ";"


def count_photos_sql(where_sql: str = ""):
    return "SELECT COUNT(*) FROM tab_photos p " + (where_sql or "") + ";"


def stats_basic_sql():
    return "SELECT COUNT(*)::bigint, COALESCE(SUM(file_size),0)::bigint FROM tab_photos;"


def stats_by_type_sql():
    return """
        SELECT photo_typ, COUNT(*)::bigint
        FROM tab_photos
        GROUP BY photo_typ
        ORDER BY COUNT(*) DESC, photo_typ;
    """


# -------------------------
# Search endpoints (AJAX for select2 in media handling)
# -------------------------

#def search_authors_sql():
#    return """
#        SELECT mail
#        FROM gloss_personalia
#        WHERE mail ILIKE %s
#        ORDER BY mail
#        LIMIT %s OFFSET %s;
#    """


def search_sj_sql():
    return """
        SELECT id_sj
        FROM tab_sj
        WHERE CAST(id_sj AS text) ILIKE %s
        ORDER BY id_sj
        LIMIT %s OFFSET %s;
    """


def search_polygons_sql():
    return """
        SELECT polygon_name
        FROM tab_polygons
        WHERE polygon_name ILIKE %s
        ORDER BY polygon_name
        LIMIT %s OFFSET %s;
    """


def search_sections_sql():
    return """
        SELECT id_section
        FROM tab_section
        WHERE CAST(id_section AS text) ILIKE %s
        ORDER BY id_section
        LIMIT %s OFFSET %s;
    """


def search_finds_sql():
    return """
        SELECT id_find
        FROM tab_finds
        WHERE CAST(id_find AS text) ILIKE %s
        ORDER BY id_find
        LIMIT %s OFFSET %s;
    """


def search_samples_sql():
    return """
        SELECT id_sample
        FROM tab_samples
        WHERE CAST(id_sample AS text) ILIKE %s
        ORDER BY id_sample
        LIMIT %s OFFSET %s;
    """


# -------------------------
# SQLs for photograms handling
# -------------------------

def insert_photogram_sql():
    return """
        INSERT INTO tab_photograms (
            id_photogram, photogram_typ, ref_sketch, notes,
            mime_type, file_size, checksum_sha256,
            ref_photo_from, ref_photo_to
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s);
    """

def update_photogram_sql():
    return """
        UPDATE tab_photograms
        SET photogram_typ=%s,
            ref_sketch=%s,
            notes=%s,
            mime_type=%s,
            file_size=%s,
            checksum_sha256=%s,
            ref_photo_from=%s,
            ref_photo_to=%s
        WHERE id_photogram=%s;
    """

def delete_photogram_sql():
    return "DELETE FROM tab_photograms WHERE id_photogram=%s;"

def photogram_checksum_exists_sql():
    return "SELECT 1 FROM tab_photograms WHERE checksum_sha256=%s LIMIT 1;"

def photogram_exists_sql():
    return "SELECT 1 FROM tab_photograms WHERE id_photogram=%s LIMIT 1;"


# --- link tables (SU / polygon / section) ---
def link_photogram_sj_sql():
    return """
        INSERT INTO tabaid_photogram_sj (ref_photogram, ref_sj)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING;
    """

def unlink_photogram_sj_sql():
    return "DELETE FROM tabaid_photogram_sj WHERE ref_photogram=%s AND ref_sj=%s;"

def link_photogram_polygon_sql():
    return """
        INSERT INTO tabaid_polygon_photograms (ref_polygon, ref_photogram)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING;
    """

def unlink_photogram_polygon_sql():
    return "DELETE FROM tabaid_polygon_photograms WHERE ref_polygon=%s AND ref_photogram=%s;"

def link_photogram_section_sql():
    return """
        INSERT INTO tabaid_section_photograms (ref_section, ref_photogram)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING;
    """

def unlink_photogram_section_sql():
    return "DELETE FROM tabaid_section_photograms WHERE ref_section=%s AND ref_photogram=%s;"


# --- geopts ranges ---
def insert_photogram_geopts_range_sql():
    return """
        INSERT INTO tabaid_photogram_geopts (ref_photogram, ref_geopt_from, ref_geopt_to)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING;
    """

def delete_photogram_geopts_ranges_sql():
    return "DELETE FROM tabaid_photogram_geopts WHERE ref_photogram=%s;"

def select_photogram_geopts_ranges_sql():
    return """
        SELECT ref_geopt_from, ref_geopt_to
        FROM tabaid_photogram_geopts
        WHERE ref_photogram=%s
        ORDER BY ref_geopt_from, ref_geopt_to;
    """


# --- list / detail / links / stats ---
def select_photograms_page_sql(
    *,
    orphan_only: bool,
    has_typ: bool,
    has_sketch: bool,
    has_pf: bool,
    has_pt: bool,
    has_sj: bool,
    has_polygon: bool,
    has_section: bool,
):
    """
    Page select for photograms with optional filters.
    Params dict:
      typ_list, ref_sketch, ref_photo_from, ref_photo_to,
      sj_ids, polygon_names, section_ids,
      limit, offset
    """
    where = ["1=1"]

    if orphan_only:
        where.append("""
          NOT EXISTS (SELECT 1 FROM tabaid_photogram_sj s WHERE s.ref_photogram=p.id_photogram)
          AND NOT EXISTS (SELECT 1 FROM tabaid_polygon_photograms pp WHERE pp.ref_photogram=p.id_photogram)
          AND NOT EXISTS (SELECT 1 FROM tabaid_section_photograms sp WHERE sp.ref_photogram=p.id_photogram)
          AND NOT EXISTS (SELECT 1 FROM tabaid_photogram_geopts g WHERE g.ref_photogram=p.id_photogram)
        """)

    if has_typ:
        where.append("p.photogram_typ = ANY(%(typ_list)s)")
    if has_sketch:
        where.append("p.ref_sketch = %(ref_sketch)s")
    if has_pf:
        where.append("p.ref_photo_from = %(ref_photo_from)s")
    if has_pt:
        where.append("p.ref_photo_to = %(ref_photo_to)s")

    # --- entity filters ---
    if has_sj:
        where.append("""
          EXISTS (
            SELECT 1
            FROM tabaid_photogram_sj x
            WHERE x.ref_photogram = p.id_photogram
              AND x.ref_sj = ANY(%(sj_ids)s)
          )
        """)

    if has_polygon:
        where.append("""
          EXISTS (
            SELECT 1
            FROM tabaid_polygon_photograms x
            WHERE x.ref_photogram = p.id_photogram
              AND x.ref_polygon = ANY(%(polygon_names)s)
          )
        """)

    if has_section:
        where.append("""
          EXISTS (
            SELECT 1
            FROM tabaid_section_photograms x
            WHERE x.ref_photogram = p.id_photogram
              AND x.ref_section = ANY(%(section_ids)s)
          )
        """)

    where_sql = " AND ".join(f"({w})" for w in where)

    return f"""
      SELECT
        p.id_photogram,
        p.photogram_typ,
        p.ref_sketch,
        p.notes,
        p.ref_photo_from,
        p.ref_photo_to,
        json_build_object(
          'sj',      (SELECT COUNT(*) FROM tabaid_photogram_sj s WHERE s.ref_photogram=p.id_photogram),
          'polygon', (SELECT COUNT(*) FROM tabaid_polygon_photograms pp WHERE pp.ref_photogram=p.id_photogram),
          'section', (SELECT COUNT(*) FROM tabaid_section_photograms sp WHERE sp.ref_photogram=p.id_photogram),
          'ranges',  (SELECT COUNT(*) FROM tabaid_photogram_geopts g WHERE g.ref_photogram=p.id_photogram)
        ) AS link_counts
      FROM tab_photograms p
      WHERE {where_sql}
      ORDER BY p.id_photogram DESC
      LIMIT %(limit)s OFFSET %(offset)s;
    """


def select_photogram_detail_sql():
    return """
      SELECT id_photogram, photogram_typ, ref_sketch, notes, ref_photo_from, ref_photo_to
      FROM tab_photograms
      WHERE id_photogram=%s;
    """

def select_photogram_links_sql():
    return """
      SELECT
        ARRAY(SELECT ref_sj      FROM tabaid_photogram_sj       WHERE ref_photogram=%s ORDER BY ref_sj),
        ARRAY(SELECT ref_polygon FROM tabaid_polygon_photograms WHERE ref_photogram=%s ORDER BY ref_polygon),
        ARRAY(SELECT ref_section FROM tabaid_section_photograms WHERE ref_photogram=%s ORDER BY ref_section);
    """

def photograms_stats_sql():
    return """
      SELECT
        (SELECT COUNT(*) FROM tab_photograms) AS total_cnt,
        (SELECT COALESCE(SUM(file_size),0) FROM tab_photograms) AS total_bytes,
        (SELECT COUNT(*) FROM tab_photograms p
          WHERE
            NOT EXISTS (SELECT 1 FROM tabaid_photogram_sj s WHERE s.ref_photogram=p.id_photogram)
            AND NOT EXISTS (SELECT 1 FROM tabaid_polygon_photograms pp WHERE pp.ref_photogram=p.id_photogram)
            AND NOT EXISTS (SELECT 1 FROM tabaid_section_photograms sp WHERE sp.ref_photogram=p.id_photogram)
            AND NOT EXISTS (SELECT 1 FROM tabaid_photogram_geopts g WHERE g.ref_photogram=p.id_photogram)
        ) AS orphan_cnt;
    """

def photograms_stats_by_type_sql():
    return """
      SELECT photogram_typ, COUNT(*)
      FROM tab_photograms
      GROUP BY photogram_typ
      ORDER BY COUNT(*) DESC, photogram_typ;
    """


# --- search SQLs (SearchSelect) ---
def search_sj_sql():
    return """
      SELECT id_sj::text AS id, ('SU ' || id_sj::text) AS text
      FROM tab_sj
      WHERE id_sj::text ILIKE %s
      ORDER BY id_sj
      LIMIT %s OFFSET %s;
    """

def search_polygons_sql():
    return """
      SELECT polygon_name AS id, polygon_name AS text
      FROM tab_polygons
      WHERE polygon_name ILIKE %s
      ORDER BY polygon_name
      LIMIT %s OFFSET %s;
    """

def search_sections_sql():
    return """
      SELECT id_section::text AS id, ('Section ' || id_section::text) AS text
      FROM tab_section
      WHERE id_section::text ILIKE %s
      ORDER BY id_section
      LIMIT %s OFFSET %s;
    """

def search_sketches_sql():
    return """
      SELECT id_sketch AS id, id_sketch AS text
      FROM tab_sketches
      WHERE id_sketch ILIKE %s
      ORDER BY id_sketch
      LIMIT %s OFFSET %s;
    """

def search_photos_sql():
    return """
      SELECT id_photo AS id, id_photo AS text
      FROM tab_photos
      WHERE id_photo ILIKE %s
      ORDER BY id_photo DESC
      LIMIT %s OFFSET %s;
    """


# -------------------------
# SQLs for sketches handling
# -------------------------

def insert_sketch_sql():
    return """
        INSERT INTO tab_sketches (
            id_sketch, sketch_typ, author, datum, notes,
            mime_type, file_size, checksum_sha256
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s);
    """

def update_sketch_sql():
    return """
        UPDATE tab_sketches
        SET sketch_typ=%s,
            author=%s,
            datum=%s,
            notes=%s,
            mime_type=%s,
            file_size=%s,
            checksum_sha256=%s
        WHERE id_sketch=%s;
    """

def delete_sketch_sql():
    return "DELETE FROM tab_sketches WHERE id_sketch=%s;"

def sketch_exists_sql():
    return "SELECT 1 FROM tab_sketches WHERE id_sketch=%s LIMIT 1;"

def sketch_checksum_exists_sql():
    return "SELECT 1 FROM tab_sketches WHERE checksum_sha256=%s LIMIT 1;"


# --- link tables ---
def link_sketch_sj_sql():
    return """
      INSERT INTO tabaid_sj_sketch (ref_sj, ref_sketch)
      VALUES (%s, %s)
      ON CONFLICT DO NOTHING;
    """

def unlink_sketch_sj_sql():
    return "DELETE FROM tabaid_sj_sketch WHERE ref_sj=%s AND ref_sketch=%s;"

def link_sketch_polygon_sql():
    return """
      INSERT INTO tabaid_polygon_sketches (ref_polygon, ref_sketch)
      VALUES (%s, %s)
      ON CONFLICT DO NOTHING;
    """

def unlink_sketch_polygon_sql():
    return "DELETE FROM tabaid_polygon_sketches WHERE ref_polygon=%s AND ref_sketch=%s;"

def link_sketch_section_sql():
    return """
      INSERT INTO tabaid_section_sketches (ref_section, ref_sketch)
      VALUES (%s, %s)
      ON CONFLICT DO NOTHING;
    """

def unlink_sketch_section_sql():
    return "DELETE FROM tabaid_section_sketches WHERE ref_section=%s AND ref_sketch=%s;"

def link_sketch_find_sql():
    return """
      INSERT INTO tabaid_finds_sketches (ref_find, ref_sketch)
      VALUES (%s, %s)
      ON CONFLICT DO NOTHING;
    """

def unlink_sketch_find_sql():
    return "DELETE FROM tabaid_finds_sketches WHERE ref_find=%s AND ref_sketch=%s;"

def link_sketch_sample_sql():
    return """
      INSERT INTO tabaid_samples_sketches (ref_sample, ref_sketch)
      VALUES (%s, %s)
      ON CONFLICT DO NOTHING;
    """

def unlink_sketch_sample_sql():
    return "DELETE FROM tabaid_samples_sketches WHERE ref_sample=%s AND ref_sketch=%s;"


# --- SKETCHES: page query with optional filters incl. entity links ---
def select_sketches_page_sql(
    *,
    orphan_only: bool,
    has_typ: bool,
    has_author: bool,
    has_df: bool,
    has_dt: bool,
    has_sj: bool,
    has_polygon: bool,
    has_section: bool,
    has_find: bool,
    has_sample: bool,
) -> str:
    """
    Returns:
      (id_sketch, sketch_typ, author, datum, notes, link_counts_json)
    Params dict:
      typ_list, author, date_from, date_to,
      sj_list, polygon_list, section_list, find_list, sample_list,
      limit, offset
    """
    where = ["1=1"]

    if has_typ:
        where.append("s.sketch_typ = ANY(%(typ_list)s)")
    if has_author:
        where.append("s.author = %(author)s")
    if has_df:
        where.append("s.datum >= %(date_from)s")
    if has_dt:
        where.append("s.datum <= %(date_to)s")

    if has_sj:
        where.append("""
          EXISTS (
            SELECT 1
            FROM tabaid_sj_sketch x
            WHERE x.ref_sketch = s.id_sketch
              AND x.ref_sj = ANY(%(sj_list)s)
          )
        """)

    if has_polygon:
        where.append("""
          EXISTS (
            SELECT 1
            FROM tabaid_polygon_sketches x
            WHERE x.ref_sketch = s.id_sketch
              AND x.ref_polygon = ANY(%(polygon_list)s)
          )
        """)

    if has_section:
        where.append("""
          EXISTS (
            SELECT 1
            FROM tabaid_section_sketches x
            WHERE x.ref_sketch = s.id_sketch
              AND x.ref_section = ANY(%(section_list)s)
          )
        """)

    if has_find:
        where.append("""
          EXISTS (
            SELECT 1
            FROM tabaid_finds_sketches x
            WHERE x.ref_sketch = s.id_sketch
              AND x.ref_find = ANY(%(find_list)s)
          )
        """)

    if has_sample:
        where.append("""
          EXISTS (
            SELECT 1
            FROM tabaid_samples_sketches x
            WHERE x.ref_sketch = s.id_sketch
              AND x.ref_sample = ANY(%(sample_list)s)
          )
        """)

    if orphan_only:
        where.append("""
          COALESCE(sj.cnt, 0) = 0
          AND COALESCE(poly.cnt, 0) = 0
          AND COALESCE(sec.cnt, 0) = 0
          AND COALESCE(fd.cnt, 0) = 0
          AND COALESCE(sp.cnt, 0) = 0
        """)

    return f"""
      SELECT
        s.id_sketch,
        s.sketch_typ,
        s.author,
        s.datum,
        s.notes,
        jsonb_build_object(
          'sj',     COALESCE(sj.cnt, 0),
          'polygon',COALESCE(poly.cnt, 0),
          'section',COALESCE(sec.cnt, 0),
          'find',   COALESCE(fd.cnt, 0),
          'sample', COALESCE(sp.cnt, 0)
        ) AS link_counts
      FROM tab_sketches s

      LEFT JOIN (
        SELECT ref_sketch, COUNT(*)::int AS cnt
        FROM tabaid_sj_sketch
        GROUP BY ref_sketch
      ) sj ON sj.ref_sketch = s.id_sketch

      LEFT JOIN (
        SELECT ref_sketch, COUNT(*)::int AS cnt
        FROM tabaid_polygon_sketches
        GROUP BY ref_sketch
      ) poly ON poly.ref_sketch = s.id_sketch

      LEFT JOIN (
        SELECT ref_sketch, COUNT(*)::int AS cnt
        FROM tabaid_section_sketches
        GROUP BY ref_sketch
      ) sec ON sec.ref_sketch = s.id_sketch

      LEFT JOIN (
        SELECT ref_sketch, COUNT(*)::int AS cnt
        FROM tabaid_finds_sketches
        GROUP BY ref_sketch
      ) fd ON fd.ref_sketch = s.id_sketch

      LEFT JOIN (
        SELECT ref_sketch, COUNT(*)::int AS cnt
        FROM tabaid_samples_sketches
        GROUP BY ref_sketch
      ) sp ON sp.ref_sketch = s.id_sketch

      WHERE {" AND ".join(where)}
      ORDER BY s.datum DESC NULLS LAST, s.id_sketch DESC
      LIMIT %(limit)s OFFSET %(offset)s;
    """


def select_sketch_detail_sql():
    return """
      SELECT id_sketch, sketch_typ, author, datum, notes
      FROM tab_sketches
      WHERE id_sketch=%s;
    """

def select_sketch_links_sql():
    return """
      SELECT
        ARRAY(SELECT ref_sj      FROM tabaid_sj_sketch         WHERE ref_sketch=%s ORDER BY ref_sj),
        ARRAY(SELECT ref_polygon FROM tabaid_polygon_sketches  WHERE ref_sketch=%s ORDER BY ref_polygon),
        ARRAY(SELECT ref_section FROM tabaid_section_sketches  WHERE ref_sketch=%s ORDER BY ref_section),
        ARRAY(SELECT ref_find    FROM tabaid_finds_sketches    WHERE ref_sketch=%s ORDER BY ref_find),
        ARRAY(SELECT ref_sample  FROM tabaid_samples_sketches  WHERE ref_sketch=%s ORDER BY ref_sample);
    """

def sketches_stats_sql():
    return """
      SELECT
        (SELECT COUNT(*) FROM tab_sketches) AS total_cnt,
        (SELECT COALESCE(SUM(file_size),0) FROM tab_sketches) AS total_bytes,
        (SELECT COUNT(*) FROM tab_sketches k
          WHERE
            NOT EXISTS (SELECT 1 FROM tabaid_sj_sketch s WHERE s.ref_sketch=k.id_sketch)
            AND NOT EXISTS (SELECT 1 FROM tabaid_polygon_sketches p WHERE p.ref_sketch=k.id_sketch)
            AND NOT EXISTS (SELECT 1 FROM tabaid_section_sketches sc WHERE sc.ref_sketch=k.id_sketch)
            AND NOT EXISTS (SELECT 1 FROM tabaid_finds_sketches f WHERE f.ref_sketch=k.id_sketch)
            AND NOT EXISTS (SELECT 1 FROM tabaid_samples_sketches sa WHERE sa.ref_sketch=k.id_sketch)
        ) AS orphan_cnt;
    """

def sketches_stats_by_type_sql():
    return """
      SELECT sketch_typ, COUNT(*)
      FROM tab_sketches
      GROUP BY sketch_typ
      ORDER BY COUNT(*) DESC, sketch_typ;
    """


# --- search SQLs for sketches module ---
def search_finds_sql():
    return """
      SELECT id_find::text AS id, ('Find ' || id_find::text) AS text
      FROM tab_finds
      WHERE id_find::text ILIKE %s
      ORDER BY id_find DESC
      LIMIT %s OFFSET %s;
    """

def search_samples_sql():
    return """
      SELECT id_sample::text AS id, ('Sample ' || id_sample::text) AS text
      FROM tab_samples
      WHERE id_sample::text ILIKE %s
      ORDER BY id_sample DESC
      LIMIT %s OFFSET %s;
    """

def search_authors_sql():
    return """
      SELECT mail AS id, mail AS text
      FROM gloss_personalia
      WHERE mail ILIKE %s
      ORDER BY mail
      LIMIT %s OFFSET %s;
    """


# -------------------------
# DRAWINGS (tab_drawings)
# -------------------------

def insert_drawing_sql():
    """
    Params:
      (id_drawing, author, datum, notes, mime_type, file_size, checksum_sha256)
    """
    return """
        INSERT INTO tab_drawings (
            id_drawing, author, datum, notes,
            mime_type, file_size, checksum_sha256
        )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s
        );
    """

def drawing_exists_sql():
    return "SELECT 1 FROM tab_drawings WHERE id_drawing=%s LIMIT 1;"

def drawing_checksum_exists_sql():
    return "SELECT 1 FROM tab_drawings WHERE checksum_sha256=%s LIMIT 1;"


# --- SEARCHSELECT (id/text) ---

def search_authors_id_text_sql():
    return """
      SELECT mail AS id, mail AS text
      FROM gloss_personalia
      WHERE mail ILIKE %s
      ORDER BY mail
      LIMIT %s OFFSET %s;
    """

def search_sj_id_text_sql():
    return """
      SELECT id_sj::text AS id, ('SJ ' || id_sj::text) AS text
      FROM tab_sj
      WHERE id_sj::text ILIKE %s
      ORDER BY id_sj
      LIMIT %s OFFSET %s;
    """

def search_sections_id_text_sql():
    return """
      SELECT id_section::text AS id, ('Section ' || id_section::text) AS text
      FROM tab_section
      WHERE id_section::text ILIKE %s
      ORDER BY id_section
      LIMIT %s OFFSET %s;
    """


# --- DRAWINGS: page query with optional filters + aggregated link VALUES ---

def select_drawings_page_sql(
    orphan_only: bool,
    has_author: bool,
    has_df: bool,
    has_dt: bool,
    has_sj: bool,
    has_section: bool,
) -> str:
    """
    Page select for drawings incl. aggregated linked entity values.
    Returns columns:
      (id_drawing, author, datum, notes, mime_type, file_size, sj_ids_jsonb, section_ids_jsonb)

    Params dict expected:
      author, date_from, date_to, sj_list, section_list, limit, offset
    """
    where = ["1=1"]

    if has_author:
        where.append("d.author = %(author)s")
    if has_df:
        where.append("d.datum >= %(date_from)s")
    if has_dt:
        where.append("d.datum <= %(date_to)s")

    if has_sj:
        where.append("""
          EXISTS (
            SELECT 1
            FROM tabaid_sj_drawings x
            WHERE x.ref_drawing = d.id_drawing
              AND x.ref_sj = ANY(%(sj_list)s)
          )
        """)

    if has_section:
        where.append("""
          EXISTS (
            SELECT 1
            FROM tabaid_section_drawings x
            WHERE x.ref_drawing = d.id_drawing
              AND x.ref_section = ANY(%(section_list)s)
          )
        """)

    if orphan_only:
        # no links at all
        where.append("(COALESCE(jsonb_array_length(sj.sj_ids), 0) = 0 AND COALESCE(jsonb_array_length(sec.section_ids), 0) = 0)")

    return f"""
      SELECT
        d.id_drawing,
        d.author,
        d.datum,
        d.notes,
        d.mime_type,
        d.file_size,
        COALESCE(sj.sj_ids, '[]'::jsonb)          AS sj_ids,
        COALESCE(sec.section_ids, '[]'::jsonb)    AS section_ids
      FROM tab_drawings d

      LEFT JOIN LATERAL (
        SELECT COALESCE(jsonb_agg(ref_sj ORDER BY ref_sj), '[]'::jsonb) AS sj_ids
        FROM tabaid_sj_drawings
        WHERE ref_drawing = d.id_drawing
      ) sj ON true

      LEFT JOIN LATERAL (
        SELECT COALESCE(jsonb_agg(ref_section ORDER BY ref_section), '[]'::jsonb) AS section_ids
        FROM tabaid_section_drawings
        WHERE ref_drawing = d.id_drawing
      ) sec ON true

      WHERE {" AND ".join(where)}
      ORDER BY d.datum DESC NULLS LAST, d.id_drawing DESC
      LIMIT %(limit)s OFFSET %(offset)s;
    """



def drawings_stats_sql():
    """
    total count, sum bytes, orphan count
    """
    return """
        WITH lc AS (
          SELECT
            d.id_drawing,
            (SELECT COUNT(*) FROM tabaid_sj_drawings x WHERE x.ref_drawing = d.id_drawing) AS sj,
            (SELECT COUNT(*) FROM tabaid_section_drawings y WHERE y.ref_drawing = d.id_drawing) AS section
          FROM tab_drawings d
        )
        SELECT
          (SELECT COUNT(*) FROM tab_drawings) AS total_cnt,
          COALESCE((SELECT SUM(file_size) FROM tab_drawings), 0) AS total_bytes,
          COALESCE((SELECT COUNT(*) FROM lc WHERE (COALESCE(sj,0)+COALESCE(section,0))=0), 0) AS orphan_cnt;
    """

def select_drawing_detail_sql():
    """
    Returns: id_drawing, author, datum(YYYY-MM-DD), notes, mime_type, file_size
    """
    return """
        SELECT
          id_drawing,
          author,
          to_char(datum, 'YYYY-MM-DD') AS datum,
          notes,
          mime_type,
          file_size
        FROM tab_drawings
        WHERE id_drawing=%s
        LIMIT 1;
    """

def select_drawing_links_sql():
    """
    Returns arrays: sj_ids, section_ids
    """
    return """
      SELECT
        COALESCE((SELECT array_agg(ref_sj ORDER BY ref_sj) FROM tabaid_sj_drawings WHERE ref_drawing=%s), '{}'::int[]) AS sj_ids,
        COALESCE((SELECT array_agg(ref_section ORDER BY ref_section) FROM tabaid_section_drawings WHERE ref_drawing=%s), '{}'::int[]) AS section_ids;
    """

def delete_drawing_sql():
    return "DELETE FROM tab_drawings WHERE id_drawing=%s;"

def link_drawing_sj_sql():
    # unique index prevents dupes; ON CONFLICT for safety
    return """
      INSERT INTO tabaid_sj_drawings (ref_drawing, ref_sj)
      VALUES (%s, %s)
      ON CONFLICT DO NOTHING;
    """

def link_drawing_section_sql():
    return """
      INSERT INTO tabaid_section_drawings (ref_section, ref_drawing)
      VALUES (%s, %s)
      ON CONFLICT DO NOTHING;
    """

def unlink_all_drawing_sj_sql():
    return "DELETE FROM tabaid_sj_drawings WHERE ref_drawing=%s;"

def unlink_all_drawing_section_sql():
    return "DELETE FROM tabaid_section_drawings WHERE ref_drawing=%s;"

def update_drawing_meta_sql():
    """
    author, datum, notes
    """
    return """
      UPDATE tab_drawings
      SET author=%s, datum=%s, notes=%s
      WHERE id_drawing=%s;
    """

def update_drawing_file_sql():
    """
    mime_type, file_size, checksum_sha256
    """
    return """
      UPDATE tab_drawings
      SET mime_type=%s, file_size=%s, checksum_sha256=%s
      WHERE id_drawing=%s;
    """

def bulk_delete_drawings_sql():
    return "DELETE FROM tab_drawings WHERE id_drawing = ANY(%s);"

def bulk_update_drawings_meta_sql(set_author: bool, set_date: bool, set_notes: bool):
    sets = []
    if set_author: sets.append("author=%(author)s")
    if set_date: sets.append("datum=%(datum)s")
    if set_notes: sets.append("notes=%(notes)s")
    if not sets:
        # no-op safe
        return "SELECT 1;"
    return f"""
      UPDATE tab_drawings
      SET {", ".join(sets)}
      WHERE id_drawing = ANY(%(ids)s);
    """
