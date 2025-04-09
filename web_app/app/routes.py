from config import Config
from flask import Blueprint, render_template, jsonify, request, redirect, make_response
import jwt
import datetime
import psycopg2
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash
from app.database import get_db_connection
from app.utils import send_password_change_email
from app.logger import setup_logger
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
        # Připojení k auth_db
        conn = get_db_connection()

        cur = conn.cursor()

        cur.execute("SELECT password_hash FROM app_users WHERE mail = %s", (email,))
        result = cur.fetchone()

        if result:
            password_hash = result[0]
            if check_password_hash(password_hash, password):
                # Vygeneruj JWT token
                token = jwt.encode(
                    {
                        'email': email,
                        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
                    },
                    Config.SECRET_KEY,
                    algorithm="HS256"
                )

                logger.info(f"Úspěšné přihlášení: {email}")

                # Odpověď s cookie
                response = make_response(jsonify({"success": True}))
                response.set_cookie(
                    'token',
                    token,
                    httponly=True,
                    samesite='Lax'
                )
                return response

            else:
                logger.warning(f"Neplatné heslo pro uživatele: {email}")
        else:
            logger.warning(f"Přihlášení selhalo – uživatel neexistuje: {email}")

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
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        return redirect('/login')

    # Získání jména a last_login z auth_db
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT name, last_login FROM app_users WHERE mail = %s
        """, (user_email,))
        result = cur.fetchone()
        cur.close()
        conn.close()

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
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("Expirace JWT tokenu – přesměrování na /login")
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        logger.info(f"Požadavek na změnu hesla pro uživatele: {user_email}")
        data = request.get_json()
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if new_password != confirm_password or not new_password:
            logger.warning(f"Neúspěšná změna hesla pro {user_email} – hesla se neshodují nebo jsou prázdná.")
            return jsonify({'error': 'Hesla se neshodují nebo jsou prázdná.'}), 400

        password_hash = generate_password_hash(new_password)

        cur.execute("""
            UPDATE app_users
            SET password_hash = %s
            WHERE mail = %s
        """, (password_hash, user_email))
        conn.commit()

        # Získání jména pro email
        cur.execute("SELECT name FROM app_users WHERE mail = %s", (user_email,))
        name_result = cur.fetchone()
        user_name_for_email = name_result[0] if name_result else "uživatel"

        logger.info(f"Heslo úspěšně změněno pro {user_email}")
        send_password_change_email(user_email, user_name_for_email)
        logger.info(f"Potvrzovací e-mail o změně hesla odeslán uživateli {user_email}")

        return jsonify({'message': 'Heslo bylo úspěšně změněno a potvrzovací e-mail odeslán.'})

    # GET request – načti údaje uživatele
    cur.execute("SELECT name, mail, last_login FROM app_users WHERE mail = %s", (user_email,))
    user_data = cur.fetchone()

    if not user_data:
        logger.error(f"Uživatel {user_email} nebyl nalezen v databázi – přesměrování na /login")
        cur.close()
        conn.close()
        return redirect('/login')

    user_name, mail, last_login = user_data

    # Citát
    cur.execute("SELECT citation FROM random_citation ORDER BY RANDOM() LIMIT 1")
    citation = cur.fetchone()[0]

    cur.close()
    conn.close()

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
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload.get('email')

        if user_email:
            conn = get_db_connection()
            cur = conn.cursor()

            # Update last_login na dnešní datum (bez času)
            today = datetime.date.today()
            cur.execute(
                "UPDATE app_users SET last_login = %s WHERE mail = %s",
                (today, user_email)
            )

            conn.commit()
            cur.close()
            conn.close()
        logger.info(f"User {user_email} uspesne odhlasen")
    except Exception as e:
        logger.error(f"Chyba při odhlašování: {e}")

    # Odstranit token z cookies a přesměrovat
    response = make_response(redirect('/login'))
    response.set_cookie('token', '', expires=0)
    return response

