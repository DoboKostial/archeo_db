# # app/utils/main.py
# helpers for general purpose

# imports from standard library
import os
from flask import request, current_app, session

#imports from app
from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.queries import get_terrain_db_list

####
# functions
####

def _get_base_url() -> str:
    """
    Vrátí base URL aplikace podle aktuálního requestu, nebo fallback:
    - Config.BASE_URL (pokud existuje),
    - APP_BASE_URL z env,
    - SERVER_NAME z Flask configu,
    - jinak http://localhost:5000
    """
    try:
        from flask import request, current_app
        if getattr(request, "url_root", None):
            return request.url_root.rstrip("/")
        # fallback via SERVER_NAME (if set)
        if current_app:
            srv = current_app.config.get("SERVER_NAME")
            if srv:
                scheme = "https" if current_app.config.get("PREFERRED_URL_SCHEME", "http") == "https" else "http"
                return f"{scheme}://{srv}".rstrip("/")
    except Exception:
        pass

    base = getattr(Config, "BASE_URL", None)
    if base:
        return str(base).rstrip("/")

    env_base = os.environ.get("APP_BASE_URL")
    if env_base:
        return env_base.rstrip("/")

    return "http://localhost:5000"

# after creating a new app user (in auth_db) write him to terrain DBs as well (to gloss_personalia)
def sync_single_user_to_all_terrain_dbs(mail: str, name: str, group_role: str) -> bool:
    logger.info(f"Starting synchronization of single user {mail} to all terrain DBs")
    try:
        # list of databases
        # NOTE.: if get_terrain_db_list reads list from auth DB, it would be more appropriate use get_auth_connection().
        conn = get_terrain_connection(Config.AUTH_DB_NAME)
        terrain_dbs = get_terrain_db_list(conn)
        conn.close()

        for db_name in terrain_dbs:
            logger.info(f"Sync user {mail} to DB: {db_name}")
            try:
                conn_terrain = get_terrain_connection(db_name)
                with conn_terrain.cursor() as cur:
                    cur.execute("""
                        INSERT INTO gloss_personalia (mail, name, group_role)
                        VALUES (%s, %s, %s)
                    """, (mail, name, group_role))
                conn_terrain.commit()
                conn_terrain.close()
            except Exception as e:
                logger.error(f"Error while synchronization of user {mail} to DB '{db_name}': {e}")
                return False

        logger.info(f"User {mail} was synchronized successfully into all DBs.")
        return True
    except Exception as e:
        logger.error(f"Error while synchronization of user {mail}: {e}")
        return False



# this is for syncing new terrain DBs with auth_db (app users)
def sync_single_db(db_name: str, users) -> None:
    logger.info(f"Synchronizing users into DB '{db_name}'")
    try:
        with get_terrain_connection(db_name) as conn:
            with conn.cursor() as cur:
                for mail, name, group_role in users:
                    cur.execute("""
                        INSERT INTO public.gloss_personalia (mail, name, group_role)
                        VALUES (%s, %s, %s)
                    """, (mail, name, group_role))
            conn.commit()
        logger.info(f"Users were successfully synchronized to DB '{db_name}'.")
    except Exception as e:
        logger.error(f"There is an error while synchronization to DB '{db_name}': {e}")



# --- media directories helpers (per selected DB) ---
def get_media_dirs(selected_db=None, kind: str = 'photos'):
    """
    Generic: DATA_DIR/<db>/<kind> + thumbs.
    kind ∈ {'photos','drawings','sketches','harrismatrix'}
    """
    if selected_db is None:
        selected_db = session.get('selected_db')
    if not selected_db:
        base_dir = os.path.join(Config.DATA_DIR, "_no_db_selected_", kind)
        thumbs_dir = os.path.join(base_dir, "thumbs")
        return base_dir, thumbs_dir

    base_dir = os.path.join(Config.DATA_DIR, selected_db, kind)
    thumbs_dir = os.path.join(base_dir, 'thumbs')
    return base_dir, thumbs_dir

def get_photo_dirs(selected_db=None):
    return get_media_dirs(selected_db, 'photos')

def get_drawing_dirs(selected_db=None):
    return get_media_dirs(selected_db, 'drawings')

def get_sketch_dirs(selected_db=None):
    return get_media_dirs(selected_db, 'sketches')

def get_hmatrix_dirs(selected_db=None):
    return get_media_dirs(selected_db, 'harrismatrix')