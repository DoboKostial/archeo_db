from flask import jsonify


def _json_error(message: str, status: int):
    return jsonify({"error": message}), status
