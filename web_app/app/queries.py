# app/queries.py

# USER-related queries
def get_user_by_email():
    return """
        SELECT id, name, password_hash, last_login
        FROM app_users
        WHERE mail = %s
    """

def update_last_login():
    return """
        UPDATE app_users
        SET last_login = %s
        WHERE mail = %s
    """

def update_user_password():
    return """
        UPDATE app_users
        SET password_hash = %s
        WHERE mail = %s
    """

def get_user_profile_info():
    return """
        SELECT name, mail, last_login
        FROM app_users
        WHERE mail = %s
    """

# CITATION-related
def get_random_citation():
    return """
        SELECT citation
        FROM random_citation
        ORDER BY RANDOM()
        LIMIT 1
    """

# For index/dashboard
def get_pg_version():
    return "SELECT version()"

def get_terrain_db_sizes():
    return """
        SELECT datname, pg_database_size(datname)
        FROM pg_database
        WHERE datname LIKE 'terrain_%'
    """

