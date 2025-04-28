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
        f"Dear {user_name},\n\nYour password has been changed.\n"
        f"If you are not aware of this action, please contact the application administrator: {Config.ADMIN_NAME} ({Config.ADMIN_EMAIL})."
    )

    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
    except Exception as e:
        print("Chyba při odesílání e-mailu:", e)


# utility for sending mail when forget password
def send_password_reset_email(user_email, user_name, reset_url):
    msg = EmailMessage()
    msg['Subject'] = 'Obnova hesla – ArcheoDB'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
    msg.set_content(
    f"Dobrý den {user_name},\n\n"
    f"požádali jste o resetování hesla do systému ArcheoDB. "
    f"Pro nastavení nového hesla klikněte na následující odkaz:\n\n"
    f"{reset_url}\n\n"
    f"Po kliknutí budete vyzváni ke změně hesla. Tento odkaz je platný 30 minut.\n\n"
    f"Pokud jste o změnu nežádali, kontaktujte prosím správce: {Config.ADMIN_NAME} ({Config.ADMIN_EMAIL})\n\n"
    f"S pozdravem,\nTým ArcheoDB"
    )

    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
    except Exception as e:
        print("Chyba při odesílání e-mailu:", e)


# if archeolog creates new app user account, mail would be sent
def send_new_account_email(user_email, user_name, password):
    msg = EmailMessage()
    msg['Subject'] = 'Váš účet do ArcheoDB byl vytvořen'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
    msg.set_content(
        f"Dobrý den {user_name},\n\n"
        f"byl Vám zřízen účet do systému ArcheoDB.\n\n"
        f"Vaše přihlašovací údaje:\n"
        f"E-mail: {user_email}\n"
        f"Heslo: {password}\n\n"
        f"Doporučujeme si heslo změnit po prvním přihlášení (v sekci Můj profil).\n\n"
        f"S pozdravem,\n{Config.ADMIN_NAME}"
    )
    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
    except Exception as e:
        logger.error(f"Chyba při odesílání e-mailu novému uživateli: {e}")


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
        logger.info(f"Uživatelé byli úspěšně synchronizováni do DB '{db_name}'.")
    except Exception as e:
        logger.error(f"Chyba při synchronizaci DB '{db_name}': {e}")


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
            logger.info(f"Synchronizace DB: {db_name}")
            sync_single_db(db_name, users)

        logger.info("Synchronizace všech databází proběhla úspěšně.")
        return True

    except Exception as e:
        logger.error(f"Chyba při synchronizaci uživatelů: {e}")
        return False

# after creating a new app user (in auth_db) write him to terrain Dbs as well (to gloss_personalia)
def sync_single_user_to_all_terrain_dbs(mail, name, group_role):
    try:
        # seznam databází
        conn = get_terrain_connection(Config.AUTH_DB_NAME)
        terrain_dbs = get_terrain_db_list(conn)
        conn.close()

        for db_name in terrain_dbs:
            logger.info(f"Synchronizace uživatele {mail} do DB: {db_name}")
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
                logger.error(f"Chyba při synchronizaci uživatele {mail} do DB '{db_name}': {str(e)}")
                return False

        logger.info(f"Uživatel {mail} úspěšně synchronizován do všech databází.")
        return True
    except Exception as e:
        logger.error(f"Chyba při synchronizaci uživatele {mail}: {str(e)}")
        return False


def generate_random_password(length=12):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


# this function is a decorator and enables requirement of 'selected db' in routes
def require_selected_db(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'selected_db' not in session:
            flash("Nejdřív vyberte databázi, se kterou chcete pracovat.", "warning")
            return redirect('/index')
        return f(*args, **kwargs)
    return decorated_function

def float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

import csv
from flask import flash

#utility for upload and control of .csv file with polygon vertices
def process_polygon_upload(uploaded_file_path):
    points = []
    errors = []
    try:
        with open(uploaded_file_path, mode='r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile, delimiter=',')
            line_number = 0
            for row in reader:
                line_number += 1
                if not row or all(not field.strip() for field in row):
                    continue
                if len(row) != 5:
                    errors.append(f"Řádek {line_number}: očekáváno 5 polí, nalezeno {len(row)} polí.")
                    continue
                try:
                    id_str, x_str, y_str, z_str, description = row
                    id_int = int(id_str)
                    x = float(x_str)
                    y = float(y_str)
                    z = float(z_str)
                    description = description.strip()
                    if not description:
                        errors.append(f"Řádek {line_number}: popis (description) je prázdný.")
                        continue
                    points.append({
                        'id': id_int,
                        'x': x,
                        'y': y,
                        'z': z,
                        'description': description
                    })
                except ValueError as ve:
                    errors.append(f"Řádek {line_number}: chyba při konverzi hodnot ({ve}).")
                    continue

    except Exception as e:
        flash(f"Chyba při zpracování souboru: {str(e)}", 'danger')
        return None, None

    if errors:
        for err in errors:
            flash(err, 'warning')

    return points, errors

def prepare_polygons(points):
    """
    Ze seznamu bodů připraví slovník polygonů: {jmeno_polygonu: [(x, y), (x, y), ...]}
    """
    polygons = {}

    for point in points:
        description = point['description']
        x = point['x']
        y = point['y']

        if description not in polygons:
            polygons[description] = []
        polygons[description].append((x, y))

    # Uzavřeme každý polygon automaticky
    for description, pts in polygons.items():
        if pts[0] != pts[-1]:
            pts.append(pts[0])

    return polygons
