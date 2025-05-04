#############################
# app/queries.py
# all SQL queries in app in one file (= called in app by needs)
# dobo@dobo.sk
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
            WHERE datname ~'^[0-9]'
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


def update_user_password_and_commit(conn, email, password_hash):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE app_users
            SET password_hash = %s
            WHERE mail = %s
        """, (password_hash, email))
    conn.commit()



# here queries for data manipulation in terrain DBs

def count_sj_total():
    return "SELECT COUNT(*) FROM tab_sj;"

def count_sj_by_type(sj_typ):
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
    
def count_sj_by_type_all():
    return """
        SELECT sj_typ, COUNT(*)
        FROM tab_sj
        GROUP BY sj_typ;
    """

def count_total_sj():
    return "SELECT COUNT(*) FROM tab_sj;"

def get_polygons_list():
    return """
        SELECT polygon_name, ST_NPoints(geom), ST_SRID(geom)
        FROM tab_polygons
        ORDER BY polygon_name;
    """


def insert_polygons():
    return """
    INSERT INTO tab_polygons (polygon_name, geom)
    VALUES (%s, ST_Transform(
                   ST_SetSRID(
                       ST_MakePolygon(
                           ST_GeomFromText('LINESTRING(%s)')
                       ), %s
                   ), 4326)
           )
    """


def insert_polygon_sql(polygon_name, points, source_epsg):
    sql = f"""
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
                {source_epsg}
            ),
            4326
        )
    );
    """
    return sql
