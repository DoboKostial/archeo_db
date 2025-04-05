from flask import Blueprint, render_template, jsonify, request
import jwt
import datetime
import logging
import psycopg2
from werkzeug.security import check_password_hash

main = Blueprint("main", __name__)

SECRET_KEY = '84f84e2f68868faa06bd67721a861047aeb71c073d98c2309029451dc457cb8d'

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    logging.info(f"Pokus o přihlášení: {email}")

    try:
        conn = psycopg2.connect(
            dbname="auth_db",
            user="app_terrain_db",
            password="Som_321kokot",
            host="localhost",
            port=5432
        )
        cur = conn.cursor()

        cur.execute("SELECT password_hash FROM app_users WHERE mail = %s", (email,))
        result = cur.fetchone()

        if result:
            password_hash = result[0]
            if check_password_hash(password_hash, password):
                token = jwt.encode(
                    {'email': email, 'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)},
                    SECRET_KEY,
                    algorithm="HS256"
                )
                logging.info(f"Úspěšné přihlášení: {email}")
                return jsonify({"token": token})
            else:
                logging.warning(f"Neplatné heslo pro uživatele: {email}")
        else:
            logging.warning(f"Přihlášení selhalo – uživatel neexistuje: {email}")

        return jsonify({"error": "Invalid credentials"}), 403

    except Exception as e:
        logging.error(f"Chyba při ověřování přihlášení: {e}")
        return jsonify({"error": "Server error"}), 500

@main.route('/index', methods=['GET'])
def index():
    token = request.headers.get('Authorization')

    if not token:
        return jsonify({"error": "Token missing"}), 401

    try:
        jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return render_template('index.html')
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

