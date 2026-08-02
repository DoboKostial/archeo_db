# web_app/app/routes/admin.py
import os, re, shutil, subprocess, psycopg2
from zipfile import ZipFile

from flask import Blueprint, request, render_template, redirect, url_for, flash, send_file, jsonify, g
from werkzeug.wsgi import ClosingIterator
from werkzeug.security import generate_password_hash
from psycopg2 import sql

from config import Config
from app.logger import logger
from app.database import get_auth_connection, create_database_backup, get_terrain_connection
from app.queries import (
    get_terrain_db_list,
    get_terrain_db_sizes,
    count_app_users_sql,
    list_app_users_sql,
    srid_search_exact_sql,
    srid_search_text_sql,
)
from app.utils.auth import generate_random_password, send_new_account_email
from app.utils.admin import sync_single_user_to_all_terrain_dbs, sync_single_db
from app.utils.geom_utils import update_geometry_srid, detect_db_srid, epsg_exists_in_template_spatial_ref_sys
from app.utils.decorators import archeolog_required
from app.utils.storage import safe_join, validate_db_name

admin_bp = Blueprint('admin', __name__)


def _terrain_database_available(dbname: str) -> bool:
    validate_db_name(dbname)
    conn = get_auth_connection()
    try:
        return dbname in get_terrain_db_list(conn)
    finally:
        conn.close()


@admin_bp.get("/admin/srid/search")
@archeolog_required
def srid_search():
    """
    Search SRIDs in terrain_db_template.spatial_ref_sys.
    Query param: q (code or text)
    Returns JSON: [{"srid": 5514, "label": "EPSG:5514 — ..."}]
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])

    conn = get_terrain_connection("terrain_db_template")
    try:
        with conn.cursor() as cur:
            if re.fullmatch(r"\d{3,6}", q):
                cur.execute(srid_search_exact_sql(), (int(q),))
            else:
                like = f"%{q}%"
                cur.execute(srid_search_text_sql(), (like, like))
            rows = cur.fetchall()

        return jsonify([{"srid": int(r[0]), "label": r[1]} for r in rows])

    except Exception as e:
        logger.error(f"SRID search error: {e}")
        return jsonify([]), 500

    finally:
        try:
            conn.close()
        except Exception:
            pass


# administrative endpoint enabled only if group_role 'archeolog' is logged in
@admin_bp.route('/admin')
@archeolog_required
def admin():
    user_email = g.user_email

    conn = get_auth_connection()
    cur = conn.cursor()

    # pagination
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    per_page = 5
    offset = (page - 1) * per_page

    # the number of all users
    cur.execute(count_app_users_sql())
    total_users = cur.fetchone()[0]
    total_pages = (total_users + per_page - 1) // per_page

    # fetch users with limit (offset)
    cur.execute(list_app_users_sql(), (per_page, offset))
    users = cur.fetchall()

    # fetching all terrain DBs (names)
    terrain_db_names = get_terrain_db_list(conn)

    # list sizes
    cur.execute(get_terrain_db_sizes())
    all_sizes = cur.fetchall()

    # enrich with SRID detected from typmods
    terrain_dbs = []
    for name, size in all_sizes:
        if name not in terrain_db_names:
            continue
        srid = None
        try:
            srid = detect_db_srid(name)
        except Exception as e:
            logger.warning(f"SRID detect failed for DB '{name}': {e}")
            srid = None
        terrain_dbs.append((name, int(size), srid))

    conn.close()

    return render_template('admin.html', users=users, page=page, total_pages=total_pages, terrain_dbs=terrain_dbs)


# creating new app user in administration panel
@admin_bp.route('/add_user', methods=['POST'])
@archeolog_required
def add_user():
    current_user_email = g.user_email
    conn = get_auth_connection()
    cur = conn.cursor()

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
    current_user = g.user_email

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
    user_email = g.user_email

    conn = get_auth_connection()
    cur = conn.cursor()

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
    dbname = (request.form.get('dbname') or '').strip()
    try:
        available = _terrain_database_available(dbname)
    except Exception as e:
        logger.warning(f"Rejected backup database selection '{dbname}': {e}")
        available = False
    if not available:
        flash("The selected terrain DB is not available.", "danger")
        return redirect('/admin')

    artifacts = []
    cleanup_scheduled = False
    try:
        gz_dump_path, gz_files_path = create_database_backup(dbname)
        artifacts.extend((gz_dump_path, gz_files_path))
        logger.info(f"Backup of DB '{dbname}' created: dump at '{gz_dump_path}', files at '{gz_files_path}'")

        # pack all in one .zip and provide for download
        zip_name = os.path.basename(gz_dump_path).replace('.backup.gz', '_full_backup.zip')
        zip_path = safe_join(Config.BACKUP_DIR, zip_name)
        artifacts.append(zip_path)
        with ZipFile(zip_path, 'w') as zipf:
            zipf.write(gz_dump_path, arcname=os.path.basename(gz_dump_path))
            zipf.write(gz_files_path, arcname=os.path.basename(gz_files_path))

        logger.info(f"Full backup zip created at '{zip_path}' and sent to user")

        def remove_backup_artifacts():
            for path in artifacts:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError as e:
                    logger.warning(f"Could not remove temporary backup artifact '{path}': {e}")

        response = send_file(
            zip_path,
            as_attachment=True,
            download_name=os.path.basename(zip_path)
        )
        response.response = ClosingIterator(response.response, [remove_backup_artifacts])
        cleanup_scheduled = True
        return response

    except subprocess.CalledProcessError as e:
        logger.error(f"Error while backing up DB '{dbname}': {e.stderr.strip() if e.stderr else e}")
        flash(f"Error while backing up DB '{dbname}'. Check logs for details.", "danger")
    except Exception as e:
        logger.error(f"Unexpected error while backing up DB '{dbname}': {e}")
        flash(f"Unexpected error during backup of DB '{dbname}'.", "danger")
    finally:
        if not cleanup_scheduled:
            for path in artifacts:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass

    return redirect('/admin')


@admin_bp.route('/delete-database', methods=['POST'])
@archeolog_required
def delete_database():
    dbname = (request.form.get('dbname') or '').strip()
    try:
        available = _terrain_database_available(dbname)
    except Exception as e:
        logger.warning(f"Rejected database deletion selection '{dbname}': {e}")
        available = False
    if not available:
        flash("The selected terrain DB is not available.", "danger")
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
        db_folder_path = safe_join(Config.DATA_DIR, dbname)
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
        if epsg_int <= 0:
            flash("Invalid EPSG code.", "danger")
            return redirect('/admin')
    except ValueError:
        flash("EPSG must be a number (select from list or use Other... search).", "danger")
        return redirect('/admin')

    # Validate EPSG exists in template DB spatial_ref_sys
    if not epsg_exists_in_template_spatial_ref_sys(epsg_int):
        flash("Chosen EPSG was not found in spatial_ref_sys (template DB).", "danger")
        return redirect('/admin')

    try:
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
        subfolders = ['photos', 'drawings', 'sketches', 'photograms', 'harrismatrix']
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
