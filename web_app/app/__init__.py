# web_app/app/__init__.py
import jwt
from flask import Flask, request
from config import Config
from app.database import get_auth_connection
from app.logger import logger  # unified logger


def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.secret_key = Config.SECRET_KEY  # for Flask sessions

    # Bluprints registration
    # so far only routes
    from app.routes import main_bp, auth_bp, admin_bp, su_bp, archeo_objects_bp, polygons_bp, sections_bp, terr_photo_bp, geodesy_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(su_bp)
    app.register_blueprint(archeo_objects_bp)
    app.register_blueprint(polygons_bp)
    app.register_blueprint(sections_bp)
    app.register_blueprint(terr_photo_bp)
    app.register_blueprint(geodesy_bp)

    @app.context_processor
    def inject_user_info():
        user_name = ""
        user_email = ""
        last_login = ""
        user_role = ""

        token = request.cookies.get("token")
        if token:
            try:
                payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
                user_email = payload.get("email", "")

                with get_auth_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT name, last_login, group_role FROM app_users WHERE mail = %s",
                             (user_email,)
                        )
                        result = cur.fetchone()
                        if result:
                            user_name, last_login_dt, user_role = result
                            last_login = last_login_dt.strftime("%Y-%m-%d %H:%M:%S") if last_login_dt else ""
            except Exception as e:
                logger.warning(f"An error occurred while retrieving user info: {e}")

        return dict(
            user_name=user_name,
            user_email=user_email,
            last_login=last_login,
            user_role=user_role,
        )

    return app
