# web_app/app/__init__.py
import jwt
from flask import Flask, request, redirect, url_for, jsonify, g
from config import Config
from app.logger import logger
from app.extensions import csrf
from app.reports.service import init_report_generators

def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.secret_key = Config.SECRET_KEY

    # init CSRF protection
    csrf.init_app(app)
    # generator for reports
    init_report_generators()

    from app.routes import (
        main_bp, auth_bp, admin_bp, su_bp, archeo_objects_bp, polygons_bp,
        sections_bp, geodesy_bp, finds_samples_bp, photos_bp, photograms_bp,
        sketches_bp, drawings_bp, analyze_bp, reports_bp
    )
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(su_bp)
    app.register_blueprint(archeo_objects_bp)
    app.register_blueprint(polygons_bp)
    app.register_blueprint(sections_bp)
    app.register_blueprint(geodesy_bp)
    app.register_blueprint(finds_samples_bp)
    app.register_blueprint(photos_bp)
    app.register_blueprint(photograms_bp)
    app.register_blueprint(sketches_bp)
    app.register_blueprint(drawings_bp)
    app.register_blueprint(analyze_bp)
    app.register_blueprint(reports_bp)


    PUBLIC_ENDPOINTS = {"auth.login", "auth.forgot_password"}

    def _wants_json_response() -> bool:
        if request.is_json:
            return True
        if request.accept_mimetypes.best == "application/json":
            return True
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return True
        return False

    def _unauthorized():
        if _wants_json_response():
            return jsonify({"error": "Unauthorized"}), 401
        nxt = request.full_path if request.query_string else request.path
        return redirect(url_for("auth.login", next=nxt))

    def _forbidden():
        if _wants_json_response():
            return jsonify({"error": "Forbidden"}), 403
        return redirect(url_for("main.index"))

    @app.before_request
    def enforce_auth_and_role():
        if request.endpoint is None:
            return

        if request.endpoint.startswith("static"):
            return

        if request.endpoint in PUBLIC_ENDPOINTS:
            return

        token = request.cookies.get("token")
        if not token:
            logger.warning(f"Unauthorized (no token): {request.method} {request.path}")
            return _unauthorized()

        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            logger.info(f"Expired token: {request.method} {request.path}")
            return _unauthorized()
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e} ({request.method} {request.path})")
            return _unauthorized()

        g.user_email = payload.get("email", "") or ""
        g.user_role = payload.get("role", "") or ""
        g.user_name = payload.get("name", "") or ""
        g.user_last_login = payload.get("last_login", "") or ""  # NEW

        # admin policy
        if request.endpoint.startswith("admin.") and g.user_role != "archeolog":
            logger.warning(f"Forbidden admin access for {g.user_email} role={g.user_role} -> {request.path}")
            return _forbidden()

    @app.context_processor
    def inject_user_info():
        # IMPORTANT: navbar/header available everywhere without DB hit
        return dict(
            user_name=getattr(g, "user_name", "") or "",
            user_email=getattr(g, "user_email", "") or "",
            user_role=getattr(g, "user_role", "") or "",
            last_login=getattr(g, "user_last_login", "") or "",
        )

    return app
