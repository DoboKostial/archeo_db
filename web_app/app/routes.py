from config import Config
from flask import Blueprint, render_template, jsonify, request, redirect, make_response, session, url_for, flash, get_flashed_messages
import re
import os
from functools import wraps
import jwt
import time
import matplotlib.pyplot as plt
import networkx as nx
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import psycopg2
from psycopg2 import sql
from app.database import get_auth_connection, get_terrain_connection, create_database_backup
from app import utils
from app.utils import (
    send_password_change_email, 
    send_password_reset_email, 
    send_new_account_email, 
    sync_users_to_terrain_dbs,
    float_or_none,
    require_selected_db, process_polygon_upload, 
    prepare_polygons
)
from collections import defaultdict
from weasyprint import HTML
import io
import networkx as nx
import matplotlib.pyplot as plt
from app.logger import setup_logger
# from app import queries (na konci, az to dopises, tak zmaz jednotlie importy a prefixni metody, napr. cur.execute(queries.count_sj_total()))
from app.queries import (
    get_user_password_hash,
    get_user_name_and_last_login,
    update_user_password_hash,
    get_user_name_by_email,
    get_full_user_data,
    get_random_citation,
    update_last_login,
    get_pg_version,
    get_terrain_db_sizes,
    is_user_enabled,
    get_user_role, 
    get_user_name_and_last_login,
    get_enabled_user_name_by_email,
    get_terrain_db_list,
    count_sj_by_type,
    count_sj_total,
    count_sj_by_type_all,
    count_total_sj,
    count_objects,
    count_sj_without_relation,
    get_stratigraphy_relations, 
    get_sj_types_and_objects,
    fetch_stratigraphy_relations,
    count_sj_by_type_all,
    count_total_sj,
    insert_polygons

 )


main = Blueprint('main', __name__)
logger = setup_logger('app_archeodb')


# check if archeolog (admin) is logged - decorator
def archeolog_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_role' not in session or session['user_role'] != 'archeolog':
            logger.warning(f"Non authorized attempt for /admin from user {session.get('user_email')}")
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


####################
# here basic routes
####################


#getting to webroot - check, if logged in, if not, redirect
@main.route('/')
def root():
    return redirect('/index')


#login endpoint for application 
@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    logger.info(f"Login attempt: {email}")

    try:
        conn = get_auth_connection()

        # Is account valid and enbled?
        enabled = is_user_enabled(conn, email)
        if enabled is False:
            logger.warning(f"Login denied, account locked for: {email}")
            return jsonify({"error": "Your account is inactive. Please contact administrator."}), 403

        # Kontrola hesla
        password_hash = get_user_password_hash(conn, email)
        if password_hash and check_password_hash(password_hash, password):
            token = jwt.encode(
                {
                    'email': email,
                    'exp': datetime.utcnow() + timedelta(hours=1)
                },
                Config.SECRET_KEY,
                algorithm="HS256"
            )

            logger.info(f"Succesfull login for: {email}")

            response = make_response(jsonify({"success": True}))
            response.set_cookie('token', token, httponly=True, samesite='Lax')
            return response
        else:
            logger.warning(f"Non valid credentials for: {email}")
            return jsonify({"error": "Non valid credentials."}), 403

    except Exception as e:
        logger.error(f"An error occured while login verification: {e}")
        return jsonify({"error": "Server fault"}), 500
    finally:
        conn.close()


# logic for reseting forgotten password
@main.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot_password.html')

    data = request.get_json()
    email = data.get('email')

    try:
        conn = get_auth_connection()
        user_name = get_enabled_user_name_by_email(conn, email)

        if not user_name:
            logger.warning(f"Non valid request for password reset for e-mail: {email}")
            return jsonify({"error": "This account does not exist or was disabled."}), 400

        token = jwt.encode({
            'email': email,
            'exp': datetime.utcnow() + timedelta(minutes=30)
        }, Config.SECRET_KEY, algorithm='HS256')

        reset_url = url_for('main.profile', _external=True)
        send_password_reset_email(email, user_name, reset_url)

        logger.info(f"A request for password reset was sent to: {email}")
        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"An error occured during password reset link generation: {e}")
        return jsonify({"error": "Server fatal surprise."}), 500
    finally:
        conn.close()


@main.route('/emergency-login/<token>')
def emergency_login(token):
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("Expiration of emergency JWT token -> redirecting to /login")
        return redirect('/login')
    except jwt.InvalidTokenError:
        logger.warning("Non valid emergency JWT token: redirecting to /login")
        return redirect('/login')

    conn = get_auth_connection()
    is_enabled = is_user_enabled(conn, user_email)
    if not is_enabled:
        logger.warning(f"Emergency login of disabled or non-existing user: {user_email}")
        conn.close()
        return redirect('/login')

    logger.info(f"Emergency login successfull for user: {user_email}")
    conn.close()

    response = redirect('/profile')
    response.set_cookie(
        'token',
        token,
        httponly=True,
        samesite='Lax',
        max_age=60 * 60 * 24  # 24 hours – customizable
    )
    return response


#if logged in, redirected here - basic info about app
@main.route('/index')
def index():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        return redirect('/login')

    try:
        conn = get_auth_connection()
        cur = conn.cursor()

        # User info
        user_data = get_user_name_and_last_login(conn, user_email)
        if not user_data:
            return redirect('/login')
        user_name, last_login = user_data

        # Logged in user role
        cur.execute(get_user_role(), (user_email,))
        user_role = cur.fetchone()[0] if cur.rowcount else 'neznámá'

        # PostgreSQL version
        cur.execute(get_pg_version())
        pg_version = cur.fetchone()[0]

        # Existing datbases
        cur.execute(get_terrain_db_sizes())
        terrain_dbs = cur.fetchall()
        db_sizes = [
            {'name': row[0], 'size_mb': round(row[1] / (1024 * 1024), 2)}
            for row in terrain_dbs
        ]

    except Exception as e:
        logger.error(f"Error fetching data for /index: {e}")
        return redirect('/login')
    finally:
        conn.close()

    db_selected_message = None
    flashed = get_flashed_messages(category_filter=['success'])
    if flashed:
        db_selected_message = flashed[0]

    return render_template(
        'index.html',
        user_name=user_name,
        last_login=last_login.strftime("%Y-%m-%d") if last_login else "You are logged first time.",
        pg_version=pg_version,
        db_sizes=db_sizes,
        user_role=user_role,
        db_selected_message=db_selected_message
    )


# endpoint about currently logged in user with password change possibility
# beware of mail function - postfix should be configured on machine
@main.route('/profile', methods=['GET', 'POST'])
def profile():
    token = request.cookies.get('token')
    if not token:
        logger.warning("Access on /profile without token -> redirecting to /login")
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expiration -> redirecting to /login")
        return redirect('/login')

    conn = get_auth_connection()
    cur = conn.cursor()

    # Retrieving user role
    cur.execute(get_user_role(), (user_email,))
    user_role = cur.fetchone()[0] if cur.rowcount else 'neznámá'

    if request.method == 'POST':
        logger.info(f"Request for password change for user: {user_email}")
        data = request.get_json()
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if new_password != confirm_password or not new_password:
            logger.warning(f"The change of password for {user_email} failed - passwords are not same or empty.")
            conn.close()
            return jsonify({'error': 'Given passwords are not the same or are empty.'}), 400

        password_hash = generate_password_hash(new_password)
        update_user_password_hash(conn, user_email, password_hash)

        user_name_for_email = get_user_name_by_email(conn, user_email) or "uživatel"

        logger.info(f"Password changed successfully for {user_email}")
        send_password_change_email(user_email, user_name_for_email)
        logger.info(f"Confirming email about password change was sent to {user_email}")

        conn.close()
        return jsonify({'message': 'Password was changed and confirming email was sent.'})

    # GET request – profile data
    user_data = get_full_user_data(conn, user_email)
    if not user_data:
        logger.error(f"User {user_email} was not found in database -> redirecting to /login")
        conn.close()
        return redirect('/login')

    user_name, mail, last_login = user_data
    citation = get_random_citation(conn)

    conn.close()

    logger.info(f"Fetching the profile of user {user_email}")

    return render_template(
        'profile.html',
        user_name=user_name,
        user_email=mail,
        last_login=last_login.strftime('%Y-%m-%d'),
        citation=citation,
        user_role=user_role
    )


#user logout and get to main login endpoint
@main.route('/logout')
def logout():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload.get('email')

        if user_email:
            conn = get_auth_connection()
            update_last_login(conn, user_email)
            conn.close()

        logger.info(f"User {user_email} loged out successfully")
    except Exception as e:
        logger.error(f"Error during logout: {e}")

    response = make_response(redirect('/login'))
    response.set_cookie('token', '', expires=0)
    return response

# user would have to choose terrain DB to work with - here logic
@main.route('/select-db', methods=['POST'])
def select_db():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        return redirect('/login')

    selected_db = request.form.get('selected_db')
    if selected_db:
        session['selected_db'] = selected_db
        flash(f'Terrain DB "{selected_db}" was chosen ---> this will be Your working DB while logged in.', 'success')
    else:
        flash('No terrain DB was chosen!', 'warning')

    return redirect('/index')


#administrative endpoint enabled only if group_role
# 'archeolog' is logged in
@main.route('/admin')
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

    # fetching all users
    cur.execute("SELECT name, mail, group_role, enabled, last_login FROM app_users ORDER BY name")
    users = cur.fetchall()

    # fetching all terrain DBs
    terrain_db_names = get_terrain_db_list(conn)

    # list the size of all terrain DBs
    cur.execute(get_terrain_db_sizes())
    all_sizes = cur.fetchall()
    terrain_dbs = [(name, int(size)) for name, size in all_sizes if name in terrain_db_names]

    conn.close()

    return render_template('admin.html', users=users, terrain_dbs=terrain_dbs)


# creating new app user in administration panel
@main.route('/add_user', methods=['POST'])
def add_user():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        current_user_email = payload['email']
    except jwt.ExpiredSignatureError:
        return redirect('/login')

    # ověření oprávnění
    conn = get_auth_connection()
    cur = conn.cursor()
    cur.execute(get_user_role(), (current_user_email,))
    user_role = cur.fetchone()[0] if cur.rowcount else 'neznámá'
    if user_role != 'archeolog':
        conn.close()
        return redirect('/index')

    # načtení dat z formuláře
    name = request.form.get('name')
    mail = request.form.get('mail')
    group_role = request.form.get('group_role')

    if not name or not mail or not group_role:
        conn.close()
        flash("Neúplná data ve formuláři.", "danger")
        return redirect('/admin')

    # kontrola duplicity
    cur.execute("SELECT 1 FROM app_users WHERE mail = %s", (mail,))
    if cur.fetchone():
        conn.close()
        flash(f"Uživatel s e-mailem {mail} již existuje.", "warning")
        return redirect('/admin')

    # generování hesla
    raw_password = utils.generate_random_password()
    password_hash = generate_password_hash(raw_password)

    # vložení do DB
    cur.execute("""
        INSERT INTO app_users (name, mail, group_role, password_hash, enabled)
        VALUES (%s, %s, %s, %s, TRUE)
    """, (name, mail, group_role, password_hash))
    conn.commit()

    # odeslání e-mailu
    try:
        utils.send_new_account_email(mail, name, raw_password)
    except Exception as e:
        logger.error(f"Chyba při odesílání e-mailu novému uživateli {mail}: {str(e)}")

    logger.info(f"Nový uživatel {mail} přidán archeologem {current_user_email}.")
    conn.close()

    # >>> SYNC JEN NOVÉHO UŽIVATELE <<<
    success = utils.sync_single_user_to_all_terrain_dbs(mail, name, group_role)
    flash(f"Uživatel {mail} was caeted and synchronized into terrain databases.", "success")
    if not success:
        flash("Uživatel byl vytvořen, ale synchronizace do terénních DB selhala.", "warning")

    return redirect('/admin')


@main.route('/disable-user', methods=['POST'])
def disable_user():
    token = request.cookies.get('token')
    if not token:
        logger.warning("Přístup na /disable-user bez tokenu – přesměrování na /login")
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        current_user = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("Expirace JWT tokenu při pokusu o deaktivaci uživatele")
        return redirect('/login')

    user_to_disable = request.form.get('mail')
    if not user_to_disable:
        flash("Chybí email uživatele pro deaktivaci", "danger")
        return redirect('/admin')

    conn = get_auth_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE app_users SET enabled = false WHERE mail = %s", (user_to_disable,))
        conn.commit()
        logger.info(f"Uživatel {current_user} deaktivoval uživatele {user_to_disable}")
        flash(f"Uživatel {user_to_disable} byl deaktivován.", "success")
    except Exception as e:
        logger.error(f"Chyba při deaktivaci uživatele {user_to_disable}: {e}")
        flash("Chyba při deaktivaci uživatele", "danger")
    finally:
        conn.close()

    return redirect('/admin')


@main.route('/enable-user', methods=['POST'])
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

    # Zkontroluj, zda je aktuální uživatel archeolog
    cur.execute(get_user_role(), (user_email,))
    role = cur.fetchone()[0]
    if role != 'archeolog':
        conn.close()
        flash("Nemáte oprávnění aktivovat uživatele.", "danger")
        return redirect('/admin')

    mail_to_enable = request.form.get('mail')
    if not mail_to_enable:
        conn.close()
        flash("Chyba: nebyl vybrán žádný uživatel.", "warning")
        return redirect('/admin')

    cur.execute("""
        UPDATE app_users
        SET enabled = true
        WHERE mail = %s
    """, (mail_to_enable,))
    conn.commit()

    logger.info(f"Uživatel {user_email} aktivoval uživatele {mail_to_enable}")
    conn.close()
    flash(f"Uživatel {mail_to_enable} byl aktivován.", "success")
    return redirect('/admin')


@main.route('/backup-database', methods=['POST'])
def backup_database():
    dbname = request.form.get('dbname')
    if not dbname:
        flash("Název databáze nebyl zadán", "danger")
        return redirect('/admin')

    try:
        backup_path = create_database_backup(dbname)
        logger.info(f"Záloha databáze '{dbname}' vytvořena: {backup_path}")
        flash(f"Záloha databáze '{dbname}' byla úspěšně vytvořena.", "success")
    except subprocess.CalledProcessError as e:
        logger.error(f"Chyba při záloze databáze '{dbname}': {e}")
        flash(f"Chyba při záloze databáze '{dbname}'.", "danger")

    return redirect('/admin')


@main.route('/delete-database', methods=['POST'])
def delete_database():
    dbname = request.form.get('dbname')
    if not dbname:
        flash("Název databáze nebyl zadán.", "danger")
        return redirect('/admin')

    try:
        conn = get_auth_connection()
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(dbname)))

        logger.warning(f"Databáze '{dbname}' byla smazána.")
        flash(f"Databáze '{dbname}' byla úspěšně smazána.", "warning")

        cur.close()
        conn.close()
    except psycopg2.errors.ObjectInUse:
        logger.error(f"Nelze smazat databázi '{dbname}' – je právě používána.")
        flash(f"Databázi '{dbname}' nelze smazat, protože je právě používána.", "danger")
    except Exception as e:
        logger.error(f"Chyba při mazání databáze '{dbname}': {e}")
        flash(f"Nastala chyba při mazání databáze '{dbname}'. Zkontrolujte logy.", "danger")

    return redirect('/admin')


@main.route('/create-database', methods=['POST'])
def create_database():
    dbname = request.form.get('dbname')

    if not dbname:
        flash("No name of terrain DB was provided.", "danger")
        return redirect('/admin')

    if not re.match(r'^[0-9][a-zA-Z0-9_]*$', dbname):
        flash("The name of new terrain DB has to begin with number and contain letters, numbers and underscores only.", "danger")
        return redirect('/admin')

    try:
        conn = get_auth_connection()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            sql.SQL("CREATE DATABASE {} WITH TEMPLATE terrain_db_template")
            .format(sql.Identifier(dbname))
        )
        cur.close()
        conn.close()
        logger.info(f"Terrain DB '{dbname}' was created.")

        # To get users from auth_db.app_users
        auth_conn = get_auth_connection()
        with auth_conn.cursor() as auth_cur:
            auth_cur.execute("SELECT mail, name, group_role FROM app_users WHERE enabled = TRUE")
            users = auth_cur.fetchall()

        # Synchronization with new terrain DB
        from app.utils import sync_single_db
        sync_single_db(dbname, users)

        flash(f"Terrain DB '{dbname}' was successfully created and synchronized with users.", "success")
    except psycopg2.errors.DuplicateDatabase:
        flash(f"Terrain DB '{dbname}' already exists!", "warning")
    except Exception as e:
        logger.error(f"Error while creating terrain DB '{dbname}': {e}")
        flash("Error while creating terrain DB.", "danger")

    return redirect('/admin')


#######
# here fun begins - endpoints for data manipulation from terrain DBs...
#######

@main.route('/add-sj', methods=['GET', 'POST'])
@require_selected_db
def add_sj():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    cur.execute("SELECT COALESCE(MAX(id_sj), 0) + 1 FROM tab_sj;")
    suggested_id = cur.fetchone()[0]

    cur.execute("SELECT mail FROM gloss_personalia ORDER BY mail;")
    authors = [row[0] for row in cur.fetchall()]

    form_data = {}

    # Přehled o tom, co již bylo zapsáno – vždy, i při GET
    cur.execute(count_sj_total())
    sj_count_total = cur.fetchone()[0]

    # Počet podle typu
    cur.execute(*count_sj_by_type('deposit'))
    sj_count_deposit = cur.fetchone()[0]

    cur.execute(*count_sj_by_type('negativ'))
    sj_count_negative = cur.fetchone()[0]

    cur.execute(*count_sj_by_type('structure'))
    sj_count_structure = cur.fetchone()[0]

    if request.method == 'POST':
        try:
            id_sj = int(request.form.get('id_sj'))
            cur.execute("SELECT 1 FROM tab_sj WHERE id_sj = %s;", (id_sj,))
            if cur.fetchone():
                flash(f"ID stratigrafické jednotky #{id_sj} už existuje. Zadejte jiné ID.", "warning")
                form_data = request.form.to_dict(flat=True)
                return render_template('add_sj.html', suggested_id=suggested_id, authors=authors, selected_db=selected_db, form_data=form_data,
                                       sj_count_total=sj_count_total,
                                       sj_count_deposit=sj_count_deposit,
                                       sj_count_negativ=sj_count_negative,
                                       sj_count_structure=sj_count_structure)

            sj_typ = request.form.get('sj_typ')
            description = request.form.get('description')
            interpretation = request.form.get('interpretation')
            author = request.form.get('author')
            recorded = datetime.now()
            docu_plan = 'docu_plan' in request.form
            docu_vertical = 'docu_vertical' in request.form

            # Zápis do tab_sj
            cur.execute("""
                INSERT INTO tab_sj (id_sj, sj_typ, description, interpretation, author, recorded, docu_plan, docu_vertical)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (id_sj, sj_typ, description, interpretation, author, recorded, docu_plan, docu_vertical))

            # Zápis do konkrétní typové tabulky
            if sj_typ == 'deposit':
                cur.execute("""
                    INSERT INTO tab_sj_deposit (id_deposit, deposit_typ, color, boundary_visibility, "structure", compactness, deposit_removed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    id_sj,
                    request.form.get('deposit_typ'),
                    request.form.get('color'),
                    request.form.get('boundary_visibility'),
                    request.form.get('structure'),
                    request.form.get('compactness'),
                    request.form.get('deposit_removed')
                ))
            elif sj_typ == 'negativ':
                cur.execute("""
                    INSERT INTO tab_sj_negativ (id_negativ, negativ_typ, excav_extent, ident_niveau_cut, shape_plan, shape_sides, shape_bottom)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    id_sj,
                    request.form.get('negativ_typ'),
                    request.form.get('excav_extent'),
                    'ident_niveau_cut' in request.form,
                    request.form.get('shape_plan'),
                    request.form.get('shape_sides'),
                    request.form.get('shape_bottom')
                ))
            elif sj_typ == 'structure':
                cur.execute("""
                    INSERT INTO tab_sj_structure (id_structure, structure_typ, construction_typ, binder, basic_material, length_m, width_m, height_m)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    id_sj,
                    request.form.get('structure_typ'),
                    request.form.get('construction_typ'),
                    request.form.get('binder'),
                    request.form.get('basic_material'),
                    float_or_none(request.form.get('length_m')),
                    float_or_none(request.form.get('width_m')),
                    float_or_none(request.form.get('height_m'))
                ))
            else:
                flash("Neplatný typ stratigrafické jednotky.", "danger")
                form_data = request.form.to_dict(flat=True)
                return render_template('add_sj.html', suggested_id=suggested_id, authors=authors, selected_db=selected_db, form_data=form_data,
                                       sj_count_total=sj_count_total,
                                       sj_count_deposit=sj_count_deposit,
                                       sj_count_negativ=sj_count_negative,
                                       sj_count_structure=sj_count_structure)

            # Stratigrafické vztahy – nová verze s více vstupy
            relation_inputs = {
                '>': [request.form.get('above_1'), request.form.get('above_2')],
                '<': [request.form.get('below_1'), request.form.get('below_2')],
                '=': [request.form.get('equal')],
            }

            for relation, sj_list in relation_inputs.items():
                for sj_str in sj_list:
                    if sj_str:
                        try:
                            related_sj = int(sj_str)
                            if relation == '>':
                                cur.execute("""
                                    INSERT INTO tab_sj_stratigraphy (ref_sj1, relation, ref_sj2)
                                    VALUES (%s, %s, %s)
                                """, (related_sj, '<', id_sj))  # related_sj > id_sj
                            elif relation == '<':
                                cur.execute("""
                                    INSERT INTO tab_sj_stratigraphy (ref_sj1, relation, ref_sj2)
                                    VALUES (%s, %s, %s)
                                """, (id_sj, '<', related_sj))  # id_sj < related_sj
                            elif relation == '=':
                                cur.execute("""
                                    INSERT INTO tab_sj_stratigraphy (ref_sj1, relation, ref_sj2)
                                    VALUES (%s, %s, %s)
                                """, (id_sj, '=', related_sj))  # id_sj = related_sj
                        except ValueError:
                            flash(f"Neplatné číslo SJ '{sj_str}' pro vztah '{relation}' – záznam nebyl uložen.", "warning")


        except Exception as e:
            flash(f"Chyba při ukládání SJ: {e}", "danger")
            conn.rollback()
            form_data = request.form.to_dict(flat=True)
        else:
            flash(f"SU '{sj_str}' was saved to DB")
            conn.commit()
    cur.close()
    conn.close()
    return render_template('add_sj.html', 
                           suggested_id=suggested_id, 
                           authors=authors, 
                           selected_db=selected_db, 
                           form_data=form_data,
                           sj_count_total=sj_count_total,
                           sj_count_deposit=sj_count_deposit,
                           sj_count_negativ=sj_count_negative,
                           sj_count_structure=sj_count_structure)


@main.route('/objects', methods=['GET', 'POST'])
@require_selected_db
def objects():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    # Návrh ID objektu
    cur.execute("SELECT COALESCE(MAX(id_object), 0) + 1 FROM tab_object;")
    suggested_id = cur.fetchone()[0]

    # Typy objektu pro roletku
    cur.execute("SELECT object_typ FROM gloss_object_type ORDER BY object_typ;")
    object_types = [row[0] for row in cur.fetchall()]

    form_data = {}

    if request.method == 'POST':
        try:
            # Získání a kontrola hodnot z formuláře
            id_object = int(request.form.get('id_object'))
            object_typ = request.form.get('object_typ')
            superior_object = request.form.get('superior_object') or None
            notes = request.form.get('notes')
            sj_ids_raw = request.form.getlist('sj_ids[]')  # seznam SJ (z HTML name="sj_ids[]")

            # Validace: ID nesmí existovat
            cur.execute("SELECT 1 FROM tab_object WHERE id_object = %s;", (id_object,))
            if cur.fetchone():
                flash(f"Object #{id_object} already exists.", "warning")
                raise ValueError("Duplicity of ID object.")

            # Validace: nejméně 2 SJ
            if len(sj_ids_raw) < 2:
                flash("Objekt musí obsahovat alespoň dvě stratigrafické jednotky.", "warning")
                raise ValueError("Nedostatečný počet SJ.")

            # Validace: všechny SJ musí existovat
            sj_ids = []
            for sj_id_str in sj_ids_raw:
                try:
                    sj_id = int(sj_id_str)
                    cur.execute("SELECT 1 FROM tab_sj WHERE id_sj = %s;", (sj_id,))
                    if not cur.fetchone():
                        flash(f"SJ #{sj_id} neexistuje.", "danger")
                        raise ValueError(f"SJ {sj_id} neexistuje.")
                    sj_ids.append(sj_id)
                except ValueError:
                    flash(f"Neplatné číslo SJ: {sj_id_str}", "danger")
                    raise

            # Zápis do tab_object
            cur.execute("""
                INSERT INTO tab_object (id_object, object_typ, superior_object, notes)
                VALUES (%s, %s, %s, %s)
            """, (id_object, object_typ, superior_object, notes))

            # Aktualizace ref_object v tab_sj
            for sj_id in sj_ids:
                cur.execute("""
                    UPDATE tab_sj SET ref_object = %s WHERE id_sj = %s
                """, (id_object, sj_id))

            conn.commit()
            flash(f"Objekt #{id_object} byl úspěšně vytvořen.", "success")
            return redirect(url_for('main.objects'))

        except Exception as e:
            conn.rollback()
            print(f"Chyba při ukládání objektu: {e}")
            form_data = request.form.to_dict(flat=True)

    cur.close()
    conn.close()
    return render_template("objects.html",
                           suggested_id=suggested_id,
                           object_types=object_types,
                           selected_db=selected_db,
                           form_data=form_data)


@main.route('/define-object-type', methods=['POST'])
@require_selected_db
def define_object_type():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    data = request.get_json()
    new_type = data.get('object_typ', '').strip()
    description = data.get('description_typ', '').strip()

    if not new_type:
        logger.warning(f"Uživatel se pokusil zadat prázdný typ objektu v databázi {selected_db}.")
        return jsonify({'error': 'Chybí název typu objektu.'}), 400

    try:
        cur.execute(
            "INSERT INTO gloss_object_type (object_typ, description_typ) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
            (new_type, description)
        )
        conn.commit()
        logger.info(f"Do databáze {selected_db} byl přidán nový typ objektu: '{new_type}' (popis: '{description}').")
    except Exception as e:
        conn.rollback()
        logger.error(f"Chyba při ukládání typu objektu '{new_type}' do DB {selected_db}: {e}")
        return jsonify({'error': f'Chyba při ukládání: {str(e)}'}), 500
    finally:
        cur.close()
        conn.close()

    return jsonify({'message': f"Typ '{new_type}' byl uložen."}), 200


@main.route('/list-objects')
@require_selected_db
def list_objects():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    try:
        # Načtení všech objektů a jejich SJ
        cur.execute("""
            SELECT o.id_object, o.object_typ, o.superior_object, o.notes,
                   ARRAY_AGG(s.id_sj ORDER BY s.id_sj) AS sj_ids
            FROM tab_object o
            LEFT JOIN tab_sj s ON s.ref_object = o.id_object
            GROUP BY o.id_object
            ORDER BY o.id_object;
        """)
        objects = cur.fetchall()
    except Exception as e:
        conn.rollback()
        flash(f"Chyba při načítání objektů: {e}", "danger")
        objects = []

    cur.close()
    conn.close()

    return render_template('list_objects.html', objects=objects)


@main.route('/generate-objects-pdf', methods=['POST'])
@require_selected_db
def generate_objects_pdf():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT o.id_object, o.object_typ, o.superior_object, o.notes,
                ARRAY(SELECT s.id_sj FROM tab_sj s WHERE s.ref_object = o.id_object ORDER BY s.id_sj)
            FROM tab_object o
            ORDER BY o.id_object;
            """)
        objects = cur.fetchall()
    except Exception as e:
        cur.close()
        conn.close()
        flash(f"Chyba při generování PDF: {e}", "danger")
        return redirect(url_for('main.objects'))

    cur.close()
    conn.close()

    # Vygeneruj HTML pro PDF
    rendered = render_template('pdf_objects.html', objects=objects)
    pdf_io = io.BytesIO()
    HTML(string=rendered).write_pdf(pdf_io)
    pdf_io.seek(0)

    # Vrať PDF jako odpověď
    response = make_response(pdf_io.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=objekty.pdf'
    return response


@main.route('/harrismatrix', methods=['GET', 'POST'])
@require_selected_db
def harrismatrix():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    try:
        cur.execute(count_sj_by_type_all())
        sj_type_counts = cur.fetchall()

        cur.execute(count_total_sj())
        total_sj_count = cur.fetchone()[0]

        cur.execute(count_objects())
        object_count = cur.fetchone()[0]

        cur.execute(count_sj_without_relation())
        sj_without_relation = cur.fetchone()[0]

    finally:
        cur.close()
        conn.close()

    harris_image = request.args.get('harris_image')

    return render_template('harrismatrix.html',
                           selected_db=selected_db,
                           total_sj_count=total_sj_count,
                           object_count=object_count,
                           sj_without_relation=sj_without_relation,
                           sj_type_counts=sj_type_counts,
                           harris_image=harris_image)

@main.route('/generate-harrismatrix', methods=['POST'])
@require_selected_db
def generate_harrismatrix():
    selected_db = session.get('selected_db')
    if not selected_db:
        flash('Není vybraná databáze.', 'danger')
        return redirect(url_for('main.harrismatrix'))

    conn = None  # Inicializace spojení
    try:
        # Připojení k DB
        conn = get_terrain_connection(selected_db)

        # Načíst stratigrafické vztahy
        relations = fetch_stratigraphy_relations(conn)

        # Inicializace grafu
        G = nx.DiGraph()

        # Zpracování rovností (=) do skupin
        equals_groups = []
        processed_equals = set()

        for ref_sj1, relation, ref_sj2 in relations:
            if relation == '=':
                if ref_sj1 not in processed_equals and ref_sj2 not in processed_equals:
                    equals_groups.append({ref_sj1, ref_sj2})
                else:
                    for group in equals_groups:
                        if ref_sj1 in group or ref_sj2 in group:
                            group.update([ref_sj1, ref_sj2])
                            break
                processed_equals.update([ref_sj1, ref_sj2])

        # Mapování na reprezentanty
        node_mapping = {}
        for group in equals_groups:
            representative = min(group)
            for node in group:
                node_mapping[node] = representative

        # Přidávání hran < a >
        for ref_sj1, relation, ref_sj2 in relations:
            if relation in ('<', '>'):
                source = node_mapping.get(ref_sj1, ref_sj1)
                target = node_mapping.get(ref_sj2, ref_sj2)
                if relation == '<':
                    G.add_edge(source, target)
                elif relation == '>':
                    G.add_edge(target, source)

        # Kontrola cyklů
        try:
            cycles = list(nx.find_cycle(G, orientation='original'))
            if cycles:
                flash('Nalezen cyklus ve vztazích! Matice nebyla vygenerována.', 'danger')
                return redirect(url_for('main.harrismatrix'))
        except nx.exception.NetworkXNoCycle:
            pass  # Žádný cyklus - OK

        # Layout s obrácenou osou Y
        pos = nx.drawing.nx_pydot.graphviz_layout(G, prog='dot')
        for node in pos:
            x, y = pos[node]
            pos[node] = (x, -y)  # Otočení podle Y

        # Načíst typy SJ
        types_dict = {}
        with conn.cursor() as cur:
            cur.execute("SELECT id_sj, sj_typ FROM tab_sj")
            for id_sj, sj_typ in cur.fetchall():
                types_dict[id_sj] = sj_typ.lower()

        # Definice barev podle typu
        color_map = {
            'deposit': '#90EE90',   # zelená
            'negative': '#FFA07A',  # oranžová
            'structure': '#87CEFA'  # modrá
        }

        # Přiřazení barev uzlům
        node_colors = []
        for node in G.nodes():
            node_type = types_dict.get(node, 'unknown')
            color = color_map.get(node_type, '#D3D3D3')  # šedá jako default
            node_colors.append(color)

        # Vykreslení grafu
        plt.figure(figsize=(12, 10))
        nx.draw(
            G, pos,
            with_labels=True,
            node_color=node_colors,
            node_size=2000,
            font_size=10,
            font_color='black',
            arrows=False  # bez šipek!
        )

        # Vytvořit cílový adresář
        os.makedirs(Config.HARRISMATRIX_IMGS, exist_ok=True)

        # Generování názvu souboru
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{selected_db}_{timestamp}.png"
        filepath = os.path.join(Config.HARRISMATRIX_IMGS, filename)

        plt.savefig(filepath, format="png", bbox_inches='tight')
        plt.close()

        # Uložit cestu k vygenerovanému obrázku do session
        session['harrismatrix_image'] = filename

        flash('Harrisova matice byla vygenerována.', 'success')
        return redirect(url_for('main.harrismatrix'))

    except Exception as e:
        flash(f'Chyba při generování Harris Matrix: {str(e)}', 'danger')
        return redirect(url_for('main.harrismatrix'))

    finally:
        if conn:
            conn.close()


from app.queries import get_polygons_list, insert_polygon_sql
import os
import io
import csv
import shapefile  # PyShp
from flask import flash


@main.route('/polygons', methods=['GET'])
@require_selected_db
def polygons():
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)
    polygons = []

    try:
        with conn.cursor() as cur:
            cur.execute(get_polygons_list())
            polygons = [
                {'name': row[0], 'points': row[1], 'epsg': row[2]}
                for row in cur.fetchall()
            ]
    finally:
        conn.close()

    return render_template('polygons.html', polygons=polygons, selected_db=selected_db)



@main.route('/upload-polygons', methods=['POST'])
@require_selected_db
def upload_polygons():
    selected_db = session.get('selected_db')
    file = request.files.get('file')
    epsg = request.form.get('epsg')

    if not file or not epsg:
        flash('Musíte vybrat soubor a EPSG.', 'danger')
        return redirect(url_for('main.polygons'))

    conn = get_terrain_connection(selected_db)

    try:
        # Zpracuj CSV soubor a získej data
        uploaded_polygons, epsg_code = process_polygon_upload(file, epsg)

        with conn.cursor() as cur:
            for polygon_name, points in uploaded_polygons.items():
                sql = insert_polygon_sql(polygon_name, points, epsg_code)
                cur.execute(sql, (polygon_name,))
        
        conn.commit()
        flash('Polygon(y) byly úspěšně nahrány.', 'success')

    except Exception as e:
        flash(f'Chyba při nahrávání polygonů: {str(e)}', 'danger')
    finally:
        conn.close()

    return redirect(url_for('main.polygons'))


from io import BytesIO
import shapefile
import zipfile
from flask import send_file

@main.route('/download-polygons')
@require_selected_db
def download_polygons():
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT polygon_name, ST_AsText(geom)
                FROM tab_polygons;
            """)
            results = cur.fetchall()

        # Paměťové streamy pro SHP soubory
        shp_io = BytesIO()
        shx_io = BytesIO()
        dbf_io = BytesIO()

        # Vytvoření SHP do paměti
        with shapefile.Writer(shp=shp_io, shx=shx_io, dbf=dbf_io, shapeType=shapefile.POLYGON) as shp:
            shp.field('name', 'C')

            for name, wkt in results:
                coords = []
                coord_text = wkt.replace('POLYGON((', '').replace('))', '')
                for part in coord_text.split(','):
                    x, y = map(float, part.strip().split())
                    coords.append((x, y))
                shp.poly([coords])
                shp.record(name)

        # ZIP soubor v paměti
        zip_io = BytesIO()
        with zipfile.ZipFile(zip_io, 'w') as zipf:
            zipf.writestr(f"{selected_db}.shp", shp_io.getvalue())
            zipf.writestr(f"{selected_db}.shx", shx_io.getvalue())
            zipf.writestr(f"{selected_db}.dbf", dbf_io.getvalue())

            # Volitelně přidej .prj
            prj = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],' \
                  'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
            zipf.writestr(f"{selected_db}.prj", prj)

        zip_io.seek(0)
        return send_file(
            zip_io,
            mimetype='application/zip',
            download_name=f"{selected_db}_polygons.zip",
            as_attachment=True
        )

    except Exception as e:
        flash(f'Chyba při generování SHP: {str(e)}', 'danger')
        return redirect(url_for('main.polygons'))
    finally:
        conn.close()


@main.route('/upload-foto', methods=['GET', 'POST'])
@require_selected_db
def upload_foto():
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)
    thumb_dir = os.path.join(Config.TERR_FOTO_DIR, 'thumbs')
    os.makedirs(Config.TERR_FOTO_DIR, exist_ok=True)
    os.makedirs(thumb_dir, exist_ok=True)

    if request.method == 'POST':
        file = request.files.get('file')
        datum = request.form.get('datum') or None
        author = request.form.get('author') or None
        notes = request.form.get('notes') or None
        selected_sjs = request.form.getlist('ref_sj')
        selected_polygon = request.form.get('ref_polygon')

        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(Config.TERR_FOTO_DIR, filename)
            file.save(filepath)

            # Thumbnail
            from PIL import Image
            with Image.open(filepath) as img:
                img.thumbnail((200, 150))
                thumb_path = os.path.join(thumb_dir, filename.rsplit('.', 1)[0] + '_thumb.jpeg')
                img.save(thumb_path, 'JPEG')

            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO tab_foto (id_foto, datum, author, notes)
                            VALUES (%s, %s, %s, %s)
                        """, (filename, datum, author, notes))

                        for sj in selected_sjs:
                            cur.execute("""
                                INSERT INTO tabaid_foto_sj (ref_foto, ref_sj)
                                VALUES (%s, %s)
                            """, (filename, sj))

                flash('Terrain photo was uploaded successfully.', 'success')
                return redirect(url_for('main.upload_foto'))

            except Exception as e:
                flash(f'Error during the upload: {str(e)}', 'danger')

    # GET request – retrieve data for form
    sj_options = []
    polygon_options = []
    author_options = []
    recent_photos = []

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id_sj FROM tab_sj ORDER BY id_sj")
            sj_options = [row[0] for row in cur.fetchall()]

            cur.execute("SELECT polygon_name FROM tab_polygons ORDER BY polygon_name")
            polygon_options = [row[0] for row in cur.fetchall()]

            cur.execute("SELECT mail FROM gloss_personalia ORDER BY mail")
            author_options = [row[0] for row in cur.fetchall()]

            # To get 10 last uploaded terrain foto 
            cur.execute("""
                SELECT id_foto FROM tab_foto
                WHERE datum IS NOT NULL
                ORDER BY datum DESC
                LIMIT 10
            """)
            recent_photos = cur.fetchall()

    finally:
        conn.close()

    return render_template('upload_foto.html',
                           sj_options=sj_options,
                           polygon_options=polygon_options,
                           author_options=author_options,
                           recent_photos=recent_photos,
                           selected_db=selected_db)


from flask import send_from_directory
from config import Config

@main.route('/terr_foto/<path:filename>')
@require_selected_db
def serve_terr_foto(filename):
    return send_from_directory(Config.TERR_FOTO_DIR, filename)

@main.route('/terr_foto/thumbs/<path:filename>')
@require_selected_db
def serve_terr_thumb(filename):
    return send_from_directory(Config.TERR_FOTO_THUMBS_DIR, filename)

