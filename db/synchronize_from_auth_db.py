##
# This python script synchronizes auth_db (table 'app_users')
# with all DBs in cluster and corresponding table 'gloss_personalia'
# except of password hash (no needed)
#
# Do not forget to instal dotenv and psycopg2!!!
# do not forget to stuck this script into cron!!!
# author: dobo@dobo.sk
##

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
import os
import sys

# adding 'web_app' to Python path for import logger
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../web_app')))
from app.logger import setup_logger

# logger load
logger = setup_logger("synchronization")

load_dotenv()

# connect to auth_db
AUTH_DB_CONFIG = {
    "dbname": "auth_db",
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
}

# function for retrieve data from auth_db
def get_users_from_auth_db():
    try:
        logger.info("Getting users from auth_db...")
        with psycopg2.connect(**AUTH_DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT mail, name, group_role FROM app_users")
                users = cursor.fetchall()
        logger.info(f"Successfully fetched {len(users)} users from auth_db")
        return users
    except Exception as e:
        logger.error(f"Error while getting users from auth_db: {e}")
        return []

# function for synchro of one database
def sync_database(db_name, users):
    DB_CONFIG = AUTH_DB_CONFIG.copy()
    DB_CONFIG["dbname"] = db_name

    try:
        logger.info(f"Starting sync for database: {db_name}")
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                for mail, name, group_role in users:
                    # Update existing user
                    cursor.execute(
                        sql.SQL("""
                            UPDATE public.gloss_personalia
                            SET name = %s, group_role = %s
                            WHERE mail = %s
                        """),
                        (name, group_role, mail)
                    )
                    # Inserting new user
                    cursor.execute(
                        sql.SQL("""
                            INSERT INTO public.gloss_personalia (mail, name, group_role)
                            SELECT %s, %s, %s
                            WHERE NOT EXISTS (
                                SELECT 1 FROM public.gloss_personalia WHERE mail = %s
                            )
                        """),
                        (mail, name, group_role, mail)
                    )
                # Deleting users not being present in auth_db
                cursor.execute(
                    sql.SQL("""
                        DELETE FROM public.gloss_personalia
                        WHERE mail NOT IN %s
                    """),
                    (tuple(user[0] for user in users),)
                )
            conn.commit()
        logger.info(f"Successfully synced DB {db_name}")
    except Exception as e:
        logger.error(f"Error while syncing DB {db_name}: {e}")

# Retrieving list of databases
def get_databases():
    try:
        logger.info("Getting list of databases...")
        with psycopg2.connect(**AUTH_DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT datname FROM pg_database WHERE datistemplate = false AND datname NOT IN ('postgres', 'auth_db')"
                )
                databases = [row[0] for row in cursor.fetchall()]
        logger.info(f"Found {len(databases)} databases to sync")
        return databases
    except Exception as e:
        logger.error(f"Error while getting databases: {e}")
        return []

# main logic
if __name__ == "__main__":
    logger.info("Starting synchronization...")
    users = get_users_from_auth_db()
    if not users:
        logger.info("No users to sync. Exiting.")
    else:
        databases = get_databases()
        for db_name in databases:
            sync_database(db_name, users)

    logger.info("Synchronization completed")

