from functools import wraps

import jwt
from flask import g, request

from config import Config
from app.responses import _json_error


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


def require_mobile_token(view):
    """Reject the request with 401 unless a valid mobile access token is
    presented; expose its claims as g.mobile_claims."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        claims, error_response = _validate_access_token()
        if error_response:
            return error_response
        g.mobile_claims = claims
        return view(*args, **kwargs)

    return wrapper
