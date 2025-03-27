##
# This python script synchronizes auth_db (table 'app_users')
# with all DBs in cluster and corresponding table 'gloss_personalia'
# except of password hash (no needed)
#
# Do not forget to instal dotenv and psycopg2!!!
# do not forget to stuck this script into cron!!!
# author: dobo@dobo.sk
##

import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# read config z .env file
load_dotenv()

# vars from .env
AUTH_DB = os.getenv('AUTH_DB')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')

# connection to auth_db
def get_connection(db_name):
    return psycopg2.connect(
        dbname=db_name,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )

# get the list of databases from cluster except of 'auth_db'
def get_databases():
    try:
        conn = get_connection('postgres')
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT datname FROM pg_database 
                WHERE datistemplate = false AND datname != %s;
            """, (AUTH_DB,))
            databases = [row[0] for row in cursor.fetchall()]
        conn.close()
        return databases
    except Exception as e:
        print(f"Error getting the list of databases: {e}")
        return []

# get users from table app_users in auth_db
def fetch_users_from_auth_db():
    try:
        conn = get_connection(AUTH_DB)
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT mail, name, group_role, last_login 
                FROM app_users;
            """)
            users = cursor.fetchall()
        conn.close()
        return users
    except Exception as e:
        print(f"Error while getting users from auth_db: {e}")
        return []

# synchro table 'gloss_personalia' in target DB
def sync_to_database(db_name, users):
    try:
        conn = get_connection(db_name)
        with conn.cursor() as cursor:
            # truncate present data
            cursor.execute("TRUNCATE TABLE gloss_personalia;")
            
            # insert data from auth_db
            insert_query = sql.SQL("""
                INSERT INTO gloss_personalia (mail, name, group_role, last_login)
                VALUES (%s, %s, %s, %s);
            """)
            cursor.executemany(insert_query, users)
            conn.commit()
        conn.close()
        print(f"Synchro finished for DB {db_name}.")
    except Exception as e:
        print(f"Error while syncing DB {db_name}: {e}")

# Main logic of synchronization
def main():
    print("Starting synchonization...")
    users = fetch_users_from_auth_db()
    if not users:
        print("No data for synchronization found.")
        return

    databases = get_databases()
    if not databases:
        print("No databases for synchronisation found.")
        return

    for db in databases:
        sync_to_database(db, users)

    print("Synchronisation finished.")

if __name__ == "__main__":
    main()

