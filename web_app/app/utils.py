# web_app/app/utils.py
# general utilities to be reused everywhere
import os
import smtplib
import secrets
import string
import csv
import tempfile
from email.message import EmailMessage
from functools import wraps

from flask import session, redirect, flash, url_for, request
import jwt
from psycopg2 import sql

from config import Config
from app.database import get_auth_connection, get_terrain_connection
from app.queries import get_terrain_db_list, get_user_role
from app.logger import logger


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
        # fallback přes SERVER_NAME (pokud je nastaven)
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


#
# Utilities for auth stack
#

def send_password_change_email(user_email: str, user_name: str) -> None:
    logger.info(f"Preparing password-change email for {user_email}")
    msg = EmailMessage()
    msg['Subject'] = 'Password Changed Notification'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
    msg.set_content(
        f"Dear {user_name},\n\nYour password in ArcheoDB has been changed.\n"
        f"If you are not aware of this action, please contact the application administrator: "
        f"{Config.ADMIN_NAME} ({Config.ADMIN_EMAIL})."
    )

    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
        logger.info(f"Password-change email was sent to {user_email}")
    except Exception as e:
        logger.error(f"Error while sending password-change email to {user_email}: {e}")


def send_password_reset_email(user_email: str, user_name: str, reset_url: str) -> None:
    logger.info(f"Preparing password-reset email for {user_email}")
    msg = EmailMessage()
    msg['Subject'] = 'Password reset for ArcheoDB'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
    msg.set_content(
        f"Hi {user_name},\n\n"
        f"You requested for password reset ArcheoDB system.\n"
        f"For new password please use the following link:\n\n"
        f"{reset_url}\n\n"
        f"After this You will be requested to change Your password. This link is valid for 30 minutes.\n\n"
        f"If You DID NOT request for new password, please contact app admin immediately: "
        f"{Config.ADMIN_NAME} ({Config.ADMIN_EMAIL})\n\n"
        f"Have a nice day,\nArcheoDB team"
    )

    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
        logger.info(f"Password-reset email was sent to {user_email}")
    except Exception as e:
        logger.error(f"Error while sending password-reset email to {user_email}: {e}")


def send_new_account_email(user_email: str, user_name: str, password: str) -> None:
    logger.info(f"Preparing new-account email for {user_email}")
    base_url = _get_base_url()
    msg = EmailMessage()
    msg['Subject'] = 'Your account in ArcheoDB test environment was created'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
    msg.set_content(
        f"Hi {user_name},\n\n"
        f"an access to ArcheoDB ({base_url}) was granted.\n\n"
        f"Your credentials:\n"
        f"E-mail: {user_email}\n"
        f"Password: {password}\n\n"
        f"You are encouraged to change Your password immediately after first succesfull login (in Profile section).\n\n"
        f"Have a nice day,\n{Config.ADMIN_NAME}"
    )
    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
        logger.info(f"New-account email was sent to {user_email}")
    except Exception as e:
        logger.error(f"While sending an email to new user {user_email} an error occured: {e}")


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


# this is for syncing terrain DBs with auth_db (app users)
def sync_users_to_terrain_dbs() -> bool:
    logger.info("Starting synchronization of users to terrain DBs")
    try:
        conn = get_auth_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT mail, name, group_role
                FROM app_users
                WHERE enabled = TRUE
            """)
            users = cur.fetchall()

        terrain_dbs = get_terrain_db_list(conn)
        conn.close()

        logger.info(f"Found {len(terrain_dbs)} terrain DB(s) to sync")
        for db_name in terrain_dbs:
            logger.info(f"Sync DB: {db_name}")
            sync_single_db(db_name, users)

        logger.info("All DBs were synchronized successfully.")
        return True

    except Exception as e:
        logger.error(f"An error while synchronization of users: {e}")
        return False


# after creating a new app user (in auth_db) write him to terrain DBs as well (to gloss_personalia)
def sync_single_user_to_all_terrain_dbs(mail: str, name: str, group_role: str) -> bool:
    logger.info(f"Starting synchronization of single user {mail} to all terrain DBs")
    try:
        # list of databases
        # POZN.: pokud get_terrain_db_list čte seznam z auth DB, bylo by logičtější použít get_auth_connection().
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


def generate_random_password(length: int = 12) -> str:
    # we wont log password only its length
    logger.info(f"Generating random password (length={length})")
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


# this function is a decorator and enables requirement of 'selected db' in routes
def require_selected_db(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'selected_db' not in session:
            flash("Please select the DB You would like to work upon.", "warning")
            logger.info("Redirect to /index due to missing 'selected_db' in session")
            return redirect('/index')
        return f(*args, **kwargs)
    return decorated_function


def float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


#def archeolog_required(f):
 #   @wraps(f)
  #  def decorated_function(*args, **kwargs):
   #     if 'user_role' not in session or session['user_role'] != 'archeolog':
    #        logger.warning(f"Non authorized attempt for /admin from user {session.get('user_email')}")
     #       return redirect(url_for('main.index'))
      #  return f(*args, **kwargs)
    #return decorated_function

def archeolog_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.cookies.get('token')
        if not token:
            logger.warning("Admin access without token -> /login")
            return redirect('/login')

        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            email = payload.get('email')
        except jwt.ExpiredSignatureError:
            logger.warning("Expired token on admin access -> /login")
            return redirect('/login')
        except jwt.InvalidTokenError:
            logger.warning("Invalid token on admin access -> /login")
            return redirect('/login')

        # check role directly from DB
        role = None
        try:
            with get_auth_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(get_user_role(), (email,))
                    role = cur.fetchone()[0] if cur.rowcount else None
        except Exception as e:
            logger.error(f"Role check failed for {email}: {e}")
            return redirect(url_for('main.index'))

        if role != 'archeolog':
            logger.warning(f"User {email} (role={role}) blocked from admin")
            return redirect(url_for('main.index'))

        # renewing session for further use (eg. flashy/UI)
        session['user_email'] = email
        session['user_role'] = role
        return f(*args, **kwargs)
    return decorated_function

#
# Here come utils for data handling in terrain databases
#

# After new DB creation we have default nonsense SRID assigned. This function defines and updates correct SRID
def update_geometry_srid(dbname: str, target_srid: int) -> None:
    logger.info(f"Updating SRID in DB '{dbname}' to {target_srid}")
    conn = get_terrain_connection(dbname)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT f_table_schema, f_table_name, f_geometry_column, coord_dimension, srid, type
                FROM geometry_columns
                WHERE f_table_schema = 'public'
            """)
            rows = cur.fetchall()

            for row in rows:
                schema, table, column, _, current_srid, geom_type = row

                if current_srid != int(target_srid):
                    logger.info(f"Changing SRID to {target_srid} in {schema}.{table}.{column} ({geom_type})")

                    try:
                        alter_sql = sql.SQL("""
                            ALTER TABLE {schema}.{table}
                            ALTER COLUMN {column}
                            TYPE geometry({geom_type}, {target_srid})
                            USING ST_Transform({column}, {target_srid})
                        """).format(
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table),
                            column=sql.Identifier(column),
                            geom_type=sql.SQL(geom_type),
                            target_srid=sql.Literal(int(target_srid))
                        )

                        cur.execute(alter_sql)
                    except Exception as inner_e:
                        logger.error(f"Error while changing SRID in {schema}.{table}.{column}: {inner_e}")
                        raise inner_e

        conn.commit()
        logger.info(f"SRID update in DB '{dbname}' finished")
    except Exception as e:
        logger.error(f"Error while updating SRID in DB '{dbname}': {e}")
        raise
    finally:
        conn.close()


# utility for upload and control of .csv file with polygon vertices
def process_polygon_upload(file, epsg_code: int):
    """
    Reads CSV file and prepares the list of polygons.
    Returns: (dict polygon_name -> [(x, y), ...]), int epsg_code
    """
    filename = getattr(file, "filename", "uploaded.csv")
    logger.info(f"Processing polygon CSV upload: {filename} (epsg={epsg_code})")

    polygons = {}

    try:
        # We store FileStorage on disk temporarily, while csv.reader needs path or file-like object
        with tempfile.NamedTemporaryFile(delete=False, mode='w+', encoding='utf-8') as tmp:
            file.stream.seek(0)
            content = file.read().decode('utf-8')
            tmp.write(content)
            tmp.flush()
            tmp.seek(0)

            reader = csv.reader(tmp)
            next(reader, None)  # skip header if present

            for row in reader:
                if len(row) < 5:
                    raise ValueError("The row in file does not have enough values (expected 5).")

                id_point, x, y, z, polygon_name = row
                x, y = float(x), float(y)

                if polygon_name not in polygons:
                    polygons[polygon_name] = []
                polygons[polygon_name].append((x, y))
    except Exception as e:
        logger.error(f"Error while processing polygon CSV '{filename}': {e}")
        raise

    # Close the polygon if not closed yet
    for poly_points in polygons.values():
        if poly_points and poly_points[0] != poly_points[-1]:
            poly_points.append(poly_points[0])

    logger.info(f"Polygon CSV processed: {len(polygons)} polygon(s)")
    return polygons, int(epsg_code)


def prepare_polygons(points):
    """
    This prepares the list (glossary) of polygons from points records:
    {polygon_name: [(x, y), (x, y), ...]}
    """
    logger.info(f"Preparing polygons from {len(points)} points")
    polygons = {}

    for point in points:
        description = point['description']
        x = point['x']
        y = point['y']

        if description not in polygons:
            polygons[description] = []
        polygons[description].append((x, y))

    # Close the polygons automatically
    for description, pts in polygons.items():
        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])

    logger.info(f"Prepared {len(polygons)} polygon(s) from points")
    return polygons



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
