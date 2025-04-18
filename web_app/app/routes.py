from config import Config
from flask import Blueprint, render_template, jsonify, request, redirect, make_response, session, url_for, flash, get_flashed_messages
import re
from functools import wraps
import jwt
import datetime
from werkzeug.security import check_password_hash, generate_password_hash
import psycopg2
from psycopg2 import sql
from app.database import get_db_connection, create_database_backup
from app.utils import send_password_change_email, send_password_reset_email
from app.logger import setup_logger
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
    get_all_users,
    get_enabled_user_name_by_email,
    update_user_password_and_commit

)


main = Blueprint('main', __name__)
logger = setup_logger('app_archeodb')


# check if archeolog (admin) is logged - decorator
def archeolog_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_role' not in session or session['user_role'] != 'archeolog':
            logger.warning(f"Neautorizovaný pokus o přístup na /admin od uživatele {session.get('user_email')}")
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


##############
#here routes
##############


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

    logger.info(f"Pokus o přihlášení: {email}")

    try:
        conn = get_db_connection()

        # Kontrola, zda je účet aktivní
        enabled = is_user_enabled(conn, email)
        if enabled is False:
            logger.warning(f"Přihlášení zamítnuto – účet zakázán: {email}")
            return jsonify({"error": "Váš účet byl deaktivován. Kontaktujte administrátora."}), 403

        # Kontrola hesla
        password_hash = get_user_password_hash(conn, email)
        if password_hash and check_password_hash(password_hash, password):
            token = jwt.encode(
                {
                    'email': email,
                    'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
                },
                Config.SECRET_KEY,
                algorithm="HS256"
            )

            logger.info(f"Úspěšné přihlášení: {email}")

            response = make_response(jsonify({"success": True}))
            response.set_cookie('token', token, httponly=True, samesite='Lax')
            return response
        else:
            logger.warning(f"Neplatné přihlašovací údaje: {email}")
            return jsonify({"error": "Neplatné přihlašovací údaje"}), 403

    except Exception as e:
        logger.error(f"Chyba při ověřování přihlášení: {e}")
        return jsonify({"error": "Chyba serveru"}), 500
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
        conn = get_db_connection()
        user_name = get_enabled_user_name_by_email(conn, email)

        if not user_name:
            logger.warning(f"Neplatný požadavek na reset hesla pro e-mail: {email}")
            return jsonify({"error": "Účet neexistuje nebo je deaktivován."}), 400

        token = jwt.encode({
            'email': email,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
        }, Config.SECRET_KEY, algorithm='HS256')

        reset_url = url_for('main.reset_password', token=token, _external=True)
        send_password_reset_email(email, user_name, reset_url)

        logger.info(f"Odeslán e-mail pro reset hesla: {email}")
        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Chyba při generování reset linku: {e}")
        return jsonify({"error": "Chyba serveru."}), 500
    finally:
        conn.close()


@main.route('/emergency-login/<token>')
def emergency_login(token):
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("Expirace nouzového JWT tokenu – přesměrování na /login")
        return redirect('/login')
    except jwt.InvalidTokenError:
        logger.warning("Neplatný nouzový JWT token – přesměrování na /login")
        return redirect('/login')

    conn = get_db_connection()
    is_enabled = is_user_enabled(conn, user_email)
    if not is_enabled:
        logger.warning(f"Nouzové přihlášení zablokovaného nebo neexistujícího uživatele: {user_email}")
        conn.close()
        return redirect('/login')

    logger.info(f"Nouzové přihlášení úspěšné pro uživatele: {user_email}")
    conn.close()

    response = redirect('/profile')
    response.set_cookie(
        'token',
        token,
        httponly=True,
        samesite='Lax',
        max_age=60 * 60 * 24  # 24 hodin – volitelné
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
        conn = get_db_connection()
        cur = conn.cursor()

        # Uživatel
        user_data = get_user_name_and_last_login(conn, user_email)
        if not user_data:
            return redirect('/login')
        user_name, last_login = user_data

        # Role přihlášeného uživatele
        cur.execute(get_user_role(), (user_email,))
        user_role = cur.fetchone()[0] if cur.rowcount else 'neznámá'

        # Verze PostgreSQL
        cur.execute(get_pg_version())
        pg_version = cur.fetchone()[0]

        # Databáze
        cur.execute(get_terrain_db_sizes())
        terrain_dbs = cur.fetchall()
        db_sizes = [
            {'name': row[0], 'size_mb': round(row[1] / (1024 * 1024), 2)}
            for row in terrain_dbs
        ]

    except Exception as e:
        logger.error(f"Chyba při načítání údajů pro /index: {e}")
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
        last_login=last_login.strftime("%Y-%m-%d"),
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
        logger.warning("Přístup na /profile bez tokenu – přesměrování na /login")
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("Expirace JWT tokenu – přesměrování na /login")
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor()

    # Zjištění role uživatele
    cur.execute(get_user_role(), (user_email,))
    user_role = cur.fetchone()[0] if cur.rowcount else 'neznámá'

    if request.method == 'POST':
        logger.info(f"Požadavek na změnu hesla pro uživatele: {user_email}")
        data = request.get_json()
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if new_password != confirm_password or not new_password:
            logger.warning(f"Neúspěšná změna hesla pro {user_email} – hesla se neshodují nebo jsou prázdná.")
            conn.close()
            return jsonify({'error': 'Hesla se neshodují nebo jsou prázdná.'}), 400

        password_hash = generate_password_hash(new_password)
        update_user_password_hash(conn, user_email, password_hash)

        user_name_for_email = get_user_name_by_email(conn, user_email) or "uživatel"

        logger.info(f"Heslo úspěšně změněno pro {user_email}")
        send_password_change_email(user_email, user_name_for_email)
        logger.info(f"Potvrzovací e-mail o změně hesla odeslán uživateli {user_email}")

        conn.close()
        return jsonify({'message': 'Heslo bylo úspěšně změněno a potvrzovací e-mail odeslán.'})

    # GET request – profilová data
    user_data = get_full_user_data(conn, user_email)
    if not user_data:
        logger.error(f"Uživatel {user_email} nebyl nalezen v databázi – přesměrování na /login")
        conn.close()
        return redirect('/login')

    user_name, mail, last_login = user_data
    citation = get_random_citation(conn)

    conn.close()

    logger.info(f"Načtení profilu pro uživatele {user_email}")

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
            conn = get_db_connection()
            update_last_login(conn, user_email)
            conn.close()

        logger.info(f"User {user_email} úspěšně odhlášen")
    except Exception as e:
        logger.error(f"Chyba při odhlašování: {e}")

    response = make_response(redirect('/login'))
    response.set_cookie('token', '', expires=0)
    return response


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
        flash(f'Byla vybrána databáze "{selected_db}", která bude nyní Vaší pracovní.', 'success')
    else:
        flash('Nebyla vybrána žádná databáze.', 'warning')

    return redirect('/index')


#administrative endpoint enabled only if group_role
# 'archeolog' is logged in
@main.route('/admin')
def admin():
    token = request.cookies.get('token')
    if not token:
        logger.warning("Přístup na /admin bez tokenu – přesměrování na /login")
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("Expirace JWT tokenu – přesměrování na /login")
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(get_user_role(), (user_email,))
    user_role = cur.fetchone()[0] if cur.rowcount else 'neznámá'

    if user_role != 'archeolog':
        logger.warning(f"Uživatel {user_email} s rolí '{user_role}' nemá přístup na /admin – přesměrování na /index")
        conn.close()
        return redirect('/index')

    # získej jméno a last login
    user_info = get_user_name_and_last_login(conn, user_email)
    user_name = user_info[0] if user_info else '???'
    last_login = user_info[1].strftime('%Y-%m-%d') if user_info and user_info[1] else '???'

    # získej seznam uživatelů
    cur.execute(get_all_users())
    users = cur.fetchall()

    # získej seznam databází
    cur.execute(get_terrain_db_sizes())
    terrain_dbs = cur.fetchall()

    conn.close()

    return render_template(
        'admin.html',
        user_name=user_name,
        user_email=user_email,
        last_login=last_login,
        user_role=user_role,
        users=users,
        terrain_dbs=terrain_dbs
    )


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

    conn = get_db_connection()
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

    conn = get_db_connection()
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
        conn = get_db_connection()
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
        flash("Název databáze nebyl zadán.", "danger")
        return redirect('/admin')

    # Validace názvu: musí začínat číslem a může obsahovat jen alfanumerické znaky nebo podtržítka
    if not re.match(r'^[0-9][a-zA-Z0-9_]*$', dbname):
        flash("Název databáze musí začínat číslem a obsahovat pouze písmena, čísla nebo podtržítka.", "danger")
        return redirect('/admin')

    try:
        conn = get_db_connection()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            sql.SQL("CREATE DATABASE {} WITH TEMPLATE terrain_db_template")
            .format(sql.Identifier(dbname))
        )
        cur.close()
        conn.close()

        logger.info(f"Databáze '{dbname}' byla vytvořena.")
        flash(f"Databáze '{dbname}' byla úspěšně vytvořena.", "success")
    except psycopg2.errors.DuplicateDatabase:
        flash(f"Databáze '{dbname}' již existuje.", "warning")
    except Exception as e:
        logger.error(f"Chyba při vytváření databáze '{dbname}': {e}")
        flash("Chyba při vytváření databáze.", "danger")

    return redirect('/admin')







