from config import Config
from flask import Blueprint, render_template, jsonify, request, redirect, make_response
import jwt
import datetime
from werkzeug.security import check_password_hash, generate_password_hash
from app.database import get_db_connection
from app.utils import send_password_change_email
from app.logger import setup_logger
from app.queries import (
    get_user_password_hash,
    get_user_name_and_last_login,
    update_user_password_hash,
    get_user_name_by_email,
    get_random_citation,
    get_full_user_data,
    update_last_login
)

logger = setup_logger("app_archeodb")
secret_key = Config.SECRET_KEY
main = Blueprint("main", __name__)


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
        password_hash = get_user_password_hash(conn, email)

        if password_hash and check_password_hash(password_hash, password):
            token = jwt.encode(
                {
                    'email': email,
                    'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
                },
                secret_key,
                algorithm="HS256"
            )

            logger.info(f"Úspěšné přihlášení: {email}")
            response = make_response(jsonify({"success": True}))
            response.set_cookie('token', token, httponly=True, samesite='Lax')
            return response

        logger.warning(f"Neplatné přihlášení pro: {email}")
        return jsonify({"error": "Neplatné přihlašovací údaje"}), 403

    except Exception as e:
        logger.error(f"Chyba při ověřování přihlášení: {e}")
        return jsonify({"error": "Chyba serveru"}), 500


@main.route('/index')
def index():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        return redirect('/login')

    try:
        conn = get_db_connection()
        result = get_user_name_and_last_login(conn, user_email)
        if not result:
            return redirect('/login')

        user_name, last_login = result

    except Exception as e:
        logger.error(f"Chyba při načítání údajů uživatele: {e}")
        return redirect('/login')

    return render_template(
        'index.html',
        user_name=user_name,
        last_login=last_login.strftime("%Y-%m-%d")
    )


@main.route('/profile', methods=['GET', 'POST'])
def profile():
    token = request.cookies.get('token')
    if not token:
        logger.warning("Přístup na /profile bez tokenu – přesměrování na /login")
        return redirect('/login')

    try:
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("Expirace JWT tokenu – přesměrování na /login")
        return redirect('/login')

    conn = get_db_connection()

    if request.method == 'POST':
        logger.info(f"Požadavek na změnu hesla pro uživatele: {user_email}")
        data = request.get_json()
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if new_password != confirm_password or not new_password:
            logger.warning(f"Neúspěšná změna hesla pro {user_email}")
            return jsonify({'error': 'Hesla se neshodují nebo jsou prázdná.'}), 400

        password_hash = generate_password_hash(new_password)
        update_user_password_hash(conn, user_email, password_hash)

        user_name_for_email = get_user_name_by_email(conn, user_email) or "uživatel"

        logger.info(f"Heslo úspěšně změněno pro {user_email}")
        send_password_change_email(user_email, user_name_for_email)
        logger.info(f"E-mail o změně hesla odeslán uživateli {user_email}")

        return jsonify({'message': 'Heslo bylo úspěšně změněno a potvrzovací e-mail odeslán.'})

    user_data = get_full_user_data(conn, user_email)
    if not user_data:
        logger.error(f"Uživatel {user_email} nebyl nalezen – přesměrování na /login")
        return redirect('/login')

    user_name, mail, last_login = user_data
    citation = get_random_citation(conn)

    logger.info(f"Načtení profilu pro uživatele {user_email}")

    return render_template(
        'profile.html',
        user_name=user_name,
        user_email=mail,
        last_login=last_login.strftime('%Y-%m-%d'),
        citation=citation
    )


@main.route('/logout')
def logout():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
        user_email = payload.get('email')

        if user_email:
            conn = get_db_connection()
            update_last_login(conn, user_email)
            logger.info(f"User {user_email} úspěšně odhlášen")

    except Exception as e:
        logger.error(f"Chyba při odhlašování: {e}")

    response = make_response(redirect('/login'))
    response.set_cookie('token', '', expires=0)
    return response

