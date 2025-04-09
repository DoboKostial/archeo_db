# app/queries.py

def get_user_password_hash(conn, email):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT password_hash 
            FROM app_users 
            WHERE mail = %s
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

