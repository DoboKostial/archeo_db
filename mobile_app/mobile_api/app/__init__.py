from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from app.logger import setup_logger

limiter = Limiter(key_func=get_remote_address, default_limits=[])


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    if not app.config.get("RATELIMIT_STORAGE_URI"):
        app.config["RATELIMIT_STORAGE_URI"] = "memory://"

    # Gunicorn only listens on loopback in production, so these headers are
    # supplied by the single trusted Nginx proxy in front of the service.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    setup_logger()
    limiter.init_app(app)

    from app.routes import (
        auth_bp,
        documentation_bp,
        finds_samples_mobile_bp,
        geodesy_bp,
        health_bp,
        objects_bp,
        polygons_bp,
        projects_bp,
        sections_bp,
        statistics_bp,
        su_bp,
    )

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(polygons_bp)
    app.register_blueprint(su_bp)
    app.register_blueprint(objects_bp)
    app.register_blueprint(sections_bp)
    app.register_blueprint(finds_samples_mobile_bp)
    app.register_blueprint(documentation_bp)
    app.register_blueprint(geodesy_bp)
    app.register_blueprint(statistics_bp)

    return app
