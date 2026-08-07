import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from config import Config


TOKEN_ISSUER = "archeodb-web"
SESSION_AUDIENCE = "archeodb-web-session"
RESET_AUDIENCE = "archeodb-password-reset"


def _derived_key(label: str) -> bytes:
    secret = str(Config.SECRET_KEY).encode("utf-8")
    return hmac.new(secret, label.encode("ascii"), hashlib.sha256).digest()


def create_session_token(email: str, name: str, role: str, lifetime_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "type": "session",
            "iss": TOKEN_ISSUER,
            "aud": SESSION_AUDIENCE,
            "sub": email,
            "email": email,
            "name": name,
            "role": role,
            "iat": now,
            "exp": now + timedelta(minutes=lifetime_minutes),
        },
        _derived_key("session-token"),
        algorithm="HS256",
    )


def decode_session_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        _derived_key("session-token"),
        algorithms=["HS256"],
        audience=SESSION_AUDIENCE,
        issuer=TOKEN_ISSUER,
        options={"require": ["type", "sub", "email", "iat", "exp"]},
    )
    if payload.get("type") != "session" or payload.get("sub") != payload.get("email"):
        raise jwt.InvalidTokenError("invalid session token type")
    return payload


def _password_fingerprint(password_hash: str) -> str:
    return hmac.new(
        _derived_key("password-reset-binding"),
        password_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_password_reset_token(email: str, password_hash: str, lifetime_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "type": "password_reset",
            "iss": TOKEN_ISSUER,
            "aud": RESET_AUDIENCE,
            "sub": email,
            "email": email,
            "password_fingerprint": _password_fingerprint(password_hash),
            "jti": secrets.token_urlsafe(24),
            "iat": now,
            "exp": now + timedelta(minutes=lifetime_minutes),
        },
        _derived_key("password-reset-token"),
        algorithm="HS256",
    )


def decode_password_reset_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        _derived_key("password-reset-token"),
        algorithms=["HS256"],
        audience=RESET_AUDIENCE,
        issuer=TOKEN_ISSUER,
        options={
            "require": [
                "type",
                "sub",
                "email",
                "password_fingerprint",
                "jti",
                "iat",
                "exp",
            ]
        },
    )
    if payload.get("type") != "password_reset" or payload.get("sub") != payload.get("email"):
        raise jwt.InvalidTokenError("invalid password reset token type")
    return payload


def password_reset_token_matches(payload: dict, password_hash: str) -> bool:
    expected = _password_fingerprint(password_hash)
    supplied = str(payload.get("password_fingerprint") or "")
    return hmac.compare_digest(supplied, expected)
