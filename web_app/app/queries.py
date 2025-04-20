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