from functools import wraps
import logging

import jwt
from flask import g, request

from config import Config
from app.database import auth_connection
from app.responses import _json_error

logger = logging.getLogger("mobile_api.auth_tokens")
TERRAIN_WRITERS = {"archeolog", "documentator"}


def _get_bearer_token():
    auth_header = request.headers.get("Authorization", "").strip()
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:].strip()
    return token or None


def _validate_access_token():
    token = _get_bearer_token()
    if not token:
        return None, _json_error("Missing bearer token.", 401)

    try:
        claims = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None, _json_error("Access token expired.", 401)
    except jwt.InvalidTokenError:
        return None, _json_error("Invalid access token.", 401)

    if claims.get("client") != "mobile" or claims.get("type") != "access":
        return None, _json_error("Invalid access token.", 401)

    return claims, None


def _current_write_role(email):
    if not isinstance(email, str) or not email:
        return None, _json_error("Invalid access token.", 401)
    try:
        with auth_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT group_role, enabled FROM public.v_app_login_users WHERE mail = %s",
                    (email,),
                )
                row = cur.fetchone()
    except Exception:
        logger.exception("Could not check current mobile write access")
        return None, _json_error("Authorization is temporarily unavailable.", 503)

    if not row or row[1] is not True:
        return None, _json_error("Account is unavailable.", 401)
    if row[0] not in TERRAIN_WRITERS:
        return None, _json_error("Forbidden", 403)
    return row[0], None


def require_mobile_token(view):
    """Reject the request with 401 unless a valid mobile access token is
    presented; expose its claims as g.mobile_claims."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        claims, error_response = _validate_access_token()
        if error_response:
            return error_response
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            role, error_response = _current_write_role(claims.get("email"))
            if error_response:
                return error_response
            claims = {**claims, "role": role}
        g.mobile_claims = claims
        return view(*args, **kwargs)

    return wrapper
