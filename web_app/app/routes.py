from config import Config
from flask import Blueprint, render_template, jsonify, request, redirect, make_response
import jwt
import datetime
import logging
import psycopg2
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash

secret_key = Config.SECRET_KEY

main = Blueprint("main", __name__)

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    logging.info(f"Pokus o přihlášení: {email}")


    try:
        # Připojení k auth_db
        conn = psycopg2.connect(
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            host=Config.DB_HOST,
            port=Config.DB_PORT
    )
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

                logging.info(f"Úspěšné přihlášení: {email}")

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
                logging.warning(f"Neplatné heslo pro uživatele: {email}")
        else:
            logging.warning(f"Přihlášení selhalo – uživatel neexistuje: {email}")

        return jsonify({"error": "Neplatné přihlašovací údaje"}), 403

    except Exception as e:
        logging.error(f"Chyba při ověřování přihlášení: {e}")
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
        conn = psycopg2.connect(
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            host=Config.DB_HOST,
            port=Config.DB_PORT
        )
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
        logging.error(f"Chyba při načítání údajů uživatele: {e}")
        return redirect('/login')

    return render_template(
        'index.html',
        user_name=user_name,
        last_login=last_login.strftime("%Y-%m-%d")
    )



@main.route('/profile')
def profile():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        return redirect('/login')

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
        print("Chyba při načítání údajů uživatele:", e)
        return redirect('/login')

    return render_template(
        'profile.html',
        user_email=user_email,
        user_name=user_name,
        last_login=last_login.strftime("%Y-%m-%d %H:%M:%S")
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

    except Exception as e:
        logging.error(f"Chyba při odhlašování: {e}")

    # Odstranit token z cookies a přesměrovat
    response = make_response(redirect('/login'))
    response.set_cookie('token', '', expires=0)
    return response



@main.route('/change-password', methods=['POST'])
def change_password():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        return jsonify({'error': 'Chybí token'}), 401

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        email = payload['email']
        data = request.get_json()
        new_password = data.get('newPassword')

        if not new_password:
            return jsonify({'error': 'Chybí nové heslo'}), 400

        hashed = generate_password_hash(new_password, method='pbkdf2:sha256', salt_length=16)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE app_users SET password_hash = %s WHERE mail = %s", (hashed, email))
        conn.commit()
        cur.close()
        conn.close()

        app_logger.info(f"Heslo úspěšně změněno pro uživatele: {email}")
        return jsonify({'message': 'Heslo úspěšně změněno.'})

    except Exception as e:
        app_logger.error(f"Chyba při změně hesla: {e}")
        return jsonify({'error': 'Chyba při změně hesla.'}), 500

