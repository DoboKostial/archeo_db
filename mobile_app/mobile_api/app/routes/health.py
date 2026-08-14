from flask import Blueprint, jsonify

from config import Config

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    return jsonify(
        {
            "service": Config.APP_NAME,
            "version": Config.APP_VERSION,
            "status": "ok",
        }
    )

