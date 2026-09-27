import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from config import Config


TOKEN_ISSUER = "archeodb-web"
SESSION_AUDIENCE = "archeodb-web-session"
RESET_AUDIENCE = "archeodb-password-reset"
DEFAULT_SESSION_IDLE_MINUTES = 120
DEFAULT_SESSION_ABSOLUTE_MINUTES = 12 * 60


def _derived_key(label: str) -> bytes:
    secret = str(Config.SECRET_KEY).encode("utf-8")
    return hmac.new(secret, label.encode("ascii"), hashlib.sha256).digest()


def _positive_int_config(name: str, default: int, *, allow_disabled: bool = False) -> int | None:
    raw = getattr(Config, name, default)
    if raw in (None, "") and allow_disabled:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    if value <= 0:
        return None if allow_disabled else default
    return value


def session_idle_minutes() -> int:
    return int(_positive_int_config("WEB_SESSION_IDLE_MINUTES", DEFAULT_SESSION_IDLE_MINUTES))


def session_absolute_minutes() -> int | None:
    return _positive_int_config(
        "WEB_SESSION_ABSOLUTE_MINUTES",
        DEFAULT_SESSION_ABSOLUTE_MINUTES,
        allow_disabled=True,
    )


def _claim_to_datetime(value, default: datetime | None = None) -> datetime | None:
    if value is None:
        return default
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromtimestamp(float(value), timezone.utc)
        except (TypeError, ValueError, OSError):
            return default
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def session_started_at(payload: dict) -> datetime:
    return (
        _claim_to_datetime(payload.get("auth_time"))
        or _claim_to_datetime(payload.get("iat"))
        or datetime.now(timezone.utc)
    )


def session_absolute_timeout_reached(payload: dict) -> bool:
    absolute_minutes = session_absolute_minutes()
    if not absolute_minutes:
        return False
    absolute_exp = session_started_at(payload) + timedelta(minutes=absolute_minutes)
    return datetime.now(timezone.utc) >= absolute_exp


def session_cookie_max_age(payload: dict) -> int:
    exp = _claim_to_datetime(payload.get("exp"))
    if exp is None:
        return session_idle_minutes() * 60
    seconds = int((exp - datetime.now(timezone.utc)).total_seconds())
    return max(0, seconds)


def create_session_token_with_payload(
    email: str,
    name: str,
    role: str,
    lifetime_minutes: int | None = None,
    session_started: datetime | int | float | str | None = None,
) -> tuple[str, dict]:
    now = datetime.now(timezone.utc)
    idle_minutes = int(lifetime_minutes or session_idle_minutes())
    started = _claim_to_datetime(session_started, now) or now
    idle_exp = now + timedelta(minutes=idle_minutes)

    absolute_minutes = session_absolute_minutes()
    absolute_exp = started + timedelta(minutes=absolute_minutes) if absolute_minutes else None
    exp = min(idle_exp, absolute_exp) if absolute_exp else idle_exp

    payload = {
        "type": "session",
        "iss": TOKEN_ISSUER,
        "aud": SESSION_AUDIENCE,
        "sub": email,
        "email": email,
        "name": name,
        "role": role,
        "iat": now,
        "auth_time": int(started.timestamp()),
        "exp": exp,
    }
    if absolute_exp:
        payload["absolute_exp"] = int(absolute_exp.timestamp())

    token = jwt.encode(
        payload,
        _derived_key("session-token"),
        algorithm="HS256",
    )
    return token, payload


def create_session_token(email: str, name: str, role: str, lifetime_minutes: int | None = None) -> str:
    token, _payload = create_session_token_with_payload(email, name, role, lifetime_minutes)
    return token


def refresh_session_token(payload: dict) -> tuple[str, dict]:
    return create_session_token_with_payload(
        payload.get("email", "") or "",
        payload.get("name", "") or "",
        payload.get("role", "") or "",
        session_started=session_started_at(payload),
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
