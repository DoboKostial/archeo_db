import smtplib
import psycopg2
from email.message import EmailMessage
from config import Config
from app.database import get_auth_connection, get_terrain_connection
from app.queries import get_user_password_hash, get_terrain_db_list
import secrets
import string
from functools import wraps
from flask import session, redirect, flash
from app.logger import setup_logger

logger = setup_logger('app_archeodb')

###
# functions reused elsewhere
###

def send_password_change_email(user_email, user_name):
    msg = EmailMessage()
    msg['Subject'] = 'Password Changed Notification'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
    msg.set_content(
        f"Dear {user_name},\n\nYour password in ArcheoDB has been changed.\n"
        f"If you are not aware of this action, please contact the application administrator: {Config.ADMIN_NAME} ({Config.ADMIN_EMAIL})."
    )

    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
    except Exception as e:
        print("Chyba při odesílání e-mailu:", e)


# utility for sending mail when forgot password
def send_password_reset_email(user_email, user_name, reset_url):
    msg = EmailMessage()
    msg['Subject'] = 'Password reset for ArcheoDB'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
    msg.set_content(
    f"Hi {user_name},\n\n"
    f"You requested for password reset ArcheoDB system."
    f"For new password please use the following link:\n\n"
    f"{reset_url}\n\n"
    f"After this You will be requested to change Your password. This link is valid for 30 minutes.\n\n"
    f"If You DID NOT request for new password, please be so kind and contact app admin immediately: {Config.ADMIN_NAME} ({Config.ADMIN_EMAIL})\n\n"
    f"Have a nice day,\nArcheoDB team"
    )

    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
    except Exception as e:
        print("There is an error while sending email:", e)


# if archeolog creates new app user account, mail would be sent
def send_new_account_email(user_email, user_name, password):
    msg = EmailMessage()
    msg['Subject'] = 'Your account in ArcheoDB test environment was created'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
    msg.set_content(
        f"Hi {user_name},\n\n"
        f"an access to ArcheoDB test (https://sulis183.zcu.cz) was granted.\n\n"
        f"Your credentials:\n"
        f"E-mail: {user_email}\n"
        f"Password: {password}\n\n"
        f"You are encouraged to change Yor password immediately after first succesfull login (in Profile section).\n\n"
        f"Have a nice day,\n{Config.ADMIN_NAME}"
    )
    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
    except Exception as e:
        logger.error(f"While sending an email to new user an error occured: {e}")


# this is for syncying new terrain Dbs with auth_db (app users)
def sync_single_db(db_name, users):
    try:
        with get_terrain_connection(db_name) as conn:
            with conn.cursor() as cur:
                for mail, name, group_role in users:
                    cur.execute("""
                        INSERT INTO public.gloss_personalia (mail, name, group_role)
                        VALUES (%s, %s, %s)
                    """, (mail, name, group_role))
            conn.commit()
        logger.info(f"Users were succcessfully synchronised to DB '{db_name}'.")
    except Exception as e:
        logger.error(f"There is an error while synchro to DB '{db_name}': {e}")


# this is for syncying terrain Dbs with auth_db (app users)
def sync_users_to_terrain_dbs():
    try:
        # Připojení k auth_db a načtení uživatelů
        conn = get_auth_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT mail, name, group_role
                FROM app_users
                WHERE enabled = TRUE
            """)
            users = cur.fetchall()

        # Stejné připojení použijeme i pro seznam terénních DB
        terrain_dbs = get_terrain_db_list(conn)
        conn.close()

        for db_name in terrain_dbs:
            logger.info(f"Synchro DB: {db_name}")
            sync_single_db(db_name, users)

        logger.info("All DBs were synchonized successfully.")
        return True

    except Exception as e:
        logger.error(f"An error while synchronisation of users: {e}")
        return False

# after creating a new app user (in auth_db) write him to terrain Dbs as well (to gloss_personalia)
def sync_single_user_to_all_terrain_dbs(mail, name, group_role):
    try:
        # seznam databází
        conn = get_terrain_connection(Config.AUTH_DB_NAME)
        terrain_dbs = get_terrain_db_list(conn)
        conn.close()

        for db_name in terrain_dbs:
            logger.info(f"Synchro of user {mail} to DB: {db_name}")
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
                logger.error(f"Error while synchro of user {mail} to DB '{db_name}': {str(e)}")
                return False

        logger.info(f"User {mail} was synchronized successfully into all DBs.")
        return True
    except Exception as e:
        logger.error(f"Ooops, an error while synchro of user {mail}: {str(e)}")
        return False


def generate_random_password(length=12):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


# this function is a decorator and enables requirement of 'selected db' in routes
def require_selected_db(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'selected_db' not in session:
            flash("Please select the DB You would like to work upon.", "warning")
            return redirect('/index')
        return f(*args, **kwargs)
    return decorated_function

def float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None




from psycopg2 import sql
from app.database import get_terrain_connection
import logging
logger = logging.getLogger(__name__)

def update_geometry_srid(dbname, target_srid):
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
                    logger.info(f"Změna SRID na {target_srid} v {schema}.{table}.{column} ({geom_type})")

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
                        logger.error(f"❌ Chyba při změně SRID v {schema}.{table}.{column}: {inner_e}")
                        raise inner_e

        conn.commit()
    except Exception as e:
        logger.error(f"Chyba při aktualizaci SRID v databázi '{dbname}': {e}")
        raise
    finally:
        conn.close()

        



#utility for upload and control of .csv file with polygon vertices
import csv
import tempfile
def process_polygon_upload(file, epsg_code):
    """
    Reads CSV file and prepares the list of polygons.
    Returns: (dict polygon_name -> [(x, y), ...]), int epsg_code
    """
    polygons = {}

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

    # Close the polygon if not closed yet
    for poly_points in polygons.values():
        if poly_points[0] != poly_points[-1]:
            poly_points.append(poly_points[0])

    return polygons, int(epsg_code)


def prepare_polygons(points):
    """
    This prepared the list (glossary) of polygons from points records: {polygon_name: [(x, y), (x, y), ...]}
    """
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
        if pts[0] != pts[-1]:
            pts.append(pts[0])

    return polygons
