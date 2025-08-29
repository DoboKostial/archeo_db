# web_app/app/routes/admin.py
import os
import re
import shutil
import subprocess
import jwt
import psycopg2
from zipfile import ZipFile

from flask import Blueprint, request, render_template, redirect, url_for, flash, send_file
from werkzeug.security import generate_password_hash

from config import Config
from app.logger import logger
from app.database import get_auth_connection, create_database_backup
from app.queries import (
    get_user_role,
    get_terrain_db_list,
    get_terrain_db_sizes,
)
from psycopg2 import sql
from app.utils import (
    generate_random_password,
    send_new_account_email,
    sync_single_user_to_all_terrain_dbs,
    sync_single_db,
    update_geometry_srid,
    archeolog_required,   
)

admin_bp = Blueprint('admin', __name__)


# administrative endpoint enabled only if group_role 'archeolog' is logged in
@admin_bp.route('/admin')
@archeolog_required
def admin():
    token = request.cookies.get('token')
    if not token:
        logger.warning("Access to /admin with no token ---> redirecting to /login")
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired ---> redirecting to /login")
        return redirect('/login')

    conn = get_auth_connection()
    cur = conn.cursor()

    # check role
    cur.execute(get_user_role(), (user_email,))
    user_role = cur.fetchone()[0] if cur.rowcount else 'neznámá'
    if user_role != 'archeolog':
        logger.warning(f"User {user_email} with role '{user_role}' is not allowed to /admin ---> redirected to /index")
        conn.close()
        return redirect('/index')

    # pagination
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    per_page = 5
    offset = (page - 1) * per_page

    # the number of all users
    cur.execute("SELECT COUNT(*) FROM app_users")
    total_users = cur.fetchone()[0]
    total_pages = (total_users + per_page - 1) // per_page

    # fetch users with limit (offset)
    cur.execute("""
        SELECT name, mail, group_role, enabled, last_login
        FROM app_users
        ORDER BY name
        LIMIT %s OFFSET %s
    """, (per_page, offset))
    users = cur.fetchall()

    # fetching all terrain DBs
    terrain_db_names = get_terrain_db_list(conn)

    # list the size of all terrain DBs
    cur.execute(get_terrain_db_sizes())
    all_sizes = cur.fetchall()
    terrain_dbs = [(name, int(size)) for name, size in all_sizes if name in terrain_db_names]

    conn.close()

    return render_template('admin.html', users=users, page=page, total_pages=total_pages, terrain_dbs=terrain_dbs)


# creating new app user in administration panel
@admin_bp.route('/add_user', methods=['POST'])
@archeolog_required
def add_user():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        current_user_email = payload['email']
    except jwt.ExpiredSignatureError:
        return redirect('/login')

    # verify the role rights
    conn = get_auth_connection()
    cur = conn.cursor()
    cur.execute(get_user_role(), (current_user_email,))
    user_role = cur.fetchone()[0] if cur.rowcount else 'neznámá'
    if user_role != 'archeolog':
        conn.close()
        return redirect('/index')

    # reading data from form
    name = request.form.get('name')
    mail = request.form.get('mail')
    group_role = request.form.get('group_role')

    if not name or not mail or not group_role:
        conn.close()
        flash("Missing data in the form.", "danger")
        return redirect('/admin')

    # duplicity check
    cur.execute("SELECT 1 FROM app_users WHERE mail = %s", (mail,))
    if cur.fetchone():
        conn.close()
        flash(f"User with mail {mail} already exists.", "warning")
        return redirect('/admin')

    # password generator
    raw_password = generate_random_password()
    password_hash = generate_password_hash(raw_password)

    # inserting to DB
    cur.execute("""
        INSERT INTO app_users (name, mail, group_role, password_hash, enabled)
        VALUES (%s, %s, %s, %s, TRUE)
    """, (name, mail, group_role, password_hash))
    conn.commit()

    # sending email
    try:
        send_new_account_email(mail, name, raw_password)
    except Exception as e:
        logger.error(f"There is an error while sending email to new user {mail}: {str(e)}")

    logger.info(f"New user {mail} was created by archeolog {current_user_email}.")
    conn.close()

    # >>> SYNCING ONLY NEW USER <<<
    success = sync_single_user_to_all_terrain_dbs(mail, name, group_role)
    flash(f"User {mail} was created and synchronized into terrain databases.", "success")
    if not success:
        flash("User was created but sync to terrain DBs failed.", "warning")

    return redirect('/admin')


@admin_bp.route('/disable-user', methods=['POST'])
@archeolog_required
def disable_user():
    token = request.cookies.get('token')
    if not token:
        logger.warning("An access to/disable-user with no token ---> redirecting to /login")
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        current_user = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expiration during the action of user deactivation.")
        return redirect('/login')

    user_to_disable = request.form.get('mail')
    if not user_to_disable:
        flash("Missing email of user to be deactivated", "danger")
        return redirect('/admin')

    conn = get_auth_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE app_users SET enabled = false WHERE mail = %s", (user_to_disable,))
        conn.commit()
        logger.info(f"User {current_user} deactivated user {user_to_disable}")
        flash(f"User {user_to_disable} was disabled.", "success")
    except Exception as e:
        logger.error(f"An error while deactivation of user {user_to_disable}: {e}")
        flash("Error while disabling user", "danger")
    finally:
        conn.close()

    return redirect('/admin')


@admin_bp.route('/enable-user', methods=['POST'])
@archeolog_required
def enable_user():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        return redirect('/login')

    conn = get_auth_connection()
    cur = conn.cursor()

    # Check if currrent user is archeolog
    cur.execute(get_user_role(), (user_email,))
    role = cur.fetchone()[0]
    if role != 'archeolog':
        conn.close()
        flash("You have no rights to enable user. Must be an archeolog.", "danger")
        return redirect('/admin')

    mail_to_enable = request.form.get('mail')
    if not mail_to_enable:
        conn.close()
        flash("Error: no user was selected.", "warning")
        return redirect('/admin')

    cur.execute("""
        UPDATE app_users
        SET enabled = true
        WHERE mail = %s
    """, (mail_to_enable,))
    conn.commit()

    logger.info(f"User {user_email} activated user {mail_to_enable}")
    conn.close()
    flash(f"User {mail_to_enable} was enabled.", "success")
    return redirect('/admin')


@admin_bp.route('/backup-database', methods=['POST'])
@archeolog_required
def backup_database():
    dbname = request.form.get('dbname')
    if not dbname:
        flash("The name of DB was not provided", "danger")
        return redirect('/admin')

    try:
        gz_dump_path, gz_files_path = create_database_backup(dbname)
        logger.info(f"Backup of DB '{dbname}' created: dump at '{gz_dump_path}', files at '{gz_files_path}'")

        # pack all in one .zip and provide for download
        zip_path = gz_dump_path.replace('.backup.gz', '_full_backup.zip')
        with ZipFile(zip_path, 'w') as zipf:
            zipf.write(gz_dump_path, arcname=os.path.basename(gz_dump_path))
            zipf.write(gz_files_path, arcname=os.path.basename(gz_files_path))

        logger.info(f"Full backup zip created at '{zip_path}' and sent to user")

        return send_file(
            zip_path,
            as_attachment=True,
            download_name=os.path.basename(zip_path)
        )

    except subprocess.CalledProcessError as e:
        logger.error(f"Error while backing up DB '{dbname}': {e.stderr.strip() if e.stderr else e}")
        flash(f"Error while backing up DB '{dbname}'. Check logs for details.", "danger")
    except Exception as e:
        logger.error(f"Unexpected error while backing up DB '{dbname}': {e}")
        flash(f"Unexpected error during backup of DB '{dbname}'.", "danger")

    return redirect('/admin')


@admin_bp.route('/delete-database', methods=['POST'])
@archeolog_required
def delete_database():
    dbname = request.form.get('dbname')
    if not dbname:
        flash("The name of DB was not provided.", "danger")
        return redirect('/admin')

    try:
        conn = get_auth_connection()
        conn.autocommit = True
        cur = conn.cursor()

        # 1. DROP DATABASE
        cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(dbname)))
        cur.close()
        conn.close()

        logger.warning(f"Database '{dbname}' was deleted.")
        flash(f"Database '{dbname}' was successfully deleted.", "warning")

        # 2. deleting respective folders from FS
        db_folder_path = os.path.join(Config.DATA_DIR, dbname)
        if os.path.exists(db_folder_path) and os.path.isdir(db_folder_path):
            shutil.rmtree(db_folder_path)
            logger.info(f"Folder structure for DB '{dbname}' was removed from {db_folder_path}")
        else:
            logger.warning(f"Folder structure for DB '{dbname}' was not found at {db_folder_path}")

    except psycopg2.errors.ObjectInUse:
        logger.error(f"Can not delete DB '{dbname}' - currently in use.")
        flash(f"Database '{dbname}' can not be deleted - is currently in use.", "danger")
    except Exception as e:
        logger.error(f"An error during deletion of DB '{dbname}': {e}")
        flash(f"An error occurred during deletion of DB '{dbname}'. Check logs.", "danger")

    return redirect('/admin')


@admin_bp.route('/create-database', methods=['POST'])
@archeolog_required
def create_database():
    dbname = request.form.get('dbname')
    epsg = request.form.get('epsg')

    if not dbname or not epsg:
        flash("The name of database or epsg code is missing.", "danger")
        return redirect('/admin')

    if not re.match(r'^[0-9][a-zA-Z0-9_]*$', dbname):
        flash("The name of DB has to start with number and could contain only letters, numbers and underscores.", "danger")
        return redirect('/admin')

    try:
        epsg_int = int(epsg)
        allowed_epsg = [5514, 5515, 4326, 32633, 3035, 32643]
        if epsg_int not in allowed_epsg:
            flash("Chosen EPSG is not allowed.", "danger")
            return redirect('/admin')

        # Creating DB from template
        conn = get_auth_connection()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            sql.SQL("CREATE DATABASE {} WITH TEMPLATE terrain_db_template")
            .format(sql.Identifier(dbname))
        )
        cur.close()
        conn.close()
        logger.info(f"Database '{dbname}' was created.")

        # Users synchronisation to terrain databases
        auth_conn = get_auth_connection()
        with auth_conn.cursor() as auth_cur:
            auth_cur.execute("SELECT mail, name, group_role FROM app_users WHERE enabled = TRUE")
            users = auth_cur.fetchall()

        sync_single_db(dbname, users)

        # The change of SRID in newly created database
        update_geometry_srid(dbname, epsg_int)
        logger.info(f"SRID in DB '{dbname}' changed to {epsg_int}.")

        # Folder structure for content data + thumbs
        db_dir = os.path.join(Config.DATA_DIR, dbname)
        subfolders = ['photos', 'drawings', 'sketches', 'harrismatrix']
        os.makedirs(db_dir, exist_ok=True)

        for folder in subfolders:
            folder_path = os.path.join(db_dir, folder)
            thumbs_path = os.path.join(folder_path, 'thumbs')
            os.makedirs(folder_path, exist_ok=True)
            os.makedirs(thumbs_path, exist_ok=True)

        logger.info(f"File and thumbs structure created for DB '{dbname}' at {db_dir}")

        flash(f"Database '{dbname}' was created with EPSG:{epsg_int} and synchronized with users.", "success")
    except psycopg2.errors.DuplicateDatabase:
        flash(f"Database '{dbname}' already exists!", "warning")
    except Exception as e:
        logger.error(f"Error during creating DB '{dbname}': {e}")
        flash("Error during creating DB.", "danger")

    return redirect('/admin')