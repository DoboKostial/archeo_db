import os
import logging
import jwt
from flask import Flask, request
from app.database import get_auth_connection
from config import Config


def setup_logging():
    os.makedirs(Config.LOG_DIR, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(Config.MAIN_LOG_PATH),
            logging.StreamHandler()
        ]
    )


def create_app():
    setup_logging()

    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.secret_key = Config.SECRET_KEY  # nutné pro Flask sessions
    from app.routes import main
    app.register_blueprint(main)
    

    @app.context_processor
    def inject_user_info():
        user_name = ""
        user_email = ""
        last_login = ""

        token = request.cookies.get("token")
        if token:
            try:
                payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
                user_email = payload.get("email", "")
                conn = get_auth_connection()
                cur = conn.cursor()
                cur.execute("SELECT name, last_login FROM app_users WHERE mail = %s", (user_email,))
                result = cur.fetchone()
                if result:
                    user_name, last_login_dt = result
                    last_login = last_login_dt.strftime("%Y-%m-%d %H:%M:%S")
                cur.close()
                conn.close()
            except Exception as e:
                logging.warning(f"An error occured while retrieving info about user: {e}")

        return dict(user_name=user_name, user_email=user_email, last_login=last_login)

    return app

