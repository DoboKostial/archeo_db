from flask import Blueprint, render_template, jsonify, request
from werkzeug.security import check_password_hash
import jwt
import datetime

from app.database import get_db_connection  # <== Tady to přibylo

main = Blueprint("main", __name__)

SECRET_KEY = '84f84e2f68868faa06bd67721a861047aeb71c073d98c2309029451dc457cb8d'

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Zadejte email a heslo."}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM app_users WHERE mail = %s", (email,))
        result = cur.fetchone()
        cur.close()
        conn.close()

        if result is None:
            return jsonify({"error": "Uživatel nenalezen"}), 403

        password_hash = result[0]
        if check_password_hash(password_hash, password):
            token = jwt.encode(
                {'email': email, 'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)},
                SECRET_KEY,
                algorithm="HS256"
            )
            return jsonify({"token": token})

        return jsonify({"error": "Neplatné heslo"}), 403

    except Exception as e:
        print(f"Chyba při ověřování přihlášení: {e}")
        return jsonify({"error": "Chyba serveru"}), 500


@main.route('/index', methods=['GET'])
def index():
    return render_template('index.html')
