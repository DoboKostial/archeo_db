import hashlib
import hmac
import logging
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import jwt
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash

from config import Config
from app.database import auth_connection
from app.responses import _json_error
from app import limiter

auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger("mobile_api.auth")

ACCESS_TOKEN_MINUTES = 8 * 60
RESET_TOKEN_MINUTES = 30
QR_LOGIN_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,128}$")
WEB_TOKEN_ISSUER = "archeodb-web"
WEB_RESET_AUDIENCE = "archeodb-password-reset"


def _build_access_token(
    email: str,
    name: str,
    role: str,
) -> str:
    return jwt.encode(
        {
            "email": email,
            "name": name,
            "role": role,
            "client": "mobile",
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        },
        Config.JWT_SECRET_KEY,
        algorithm="HS256",
    )


def _login_response(user_email: str, user_name: str, user_role: str):
    access_token = _build_access_token(
        email=user_email,
        name=user_name or "",
        role=user_role or "",
    )
    return jsonify(
        {
            "access_token": access_token,
            "refresh_token": None,
            "user": {
                "email": user_email,
                "name": user_name or "",
                "role": user_role or "",
            },
        }
    )


def _derived_web_key(label: str) -> bytes:
    reset_secret = str(getattr(Config, "WEB_PASSWORD_RESET_SECRET_KEY", ""))
    if not reset_secret:
        raise RuntimeError("Password reset is not configured.")
    return hmac.new(
        reset_secret.encode("utf-8"),
        label.encode("ascii"),
        hashlib.sha256,
    ).digest()


def _password_fingerprint(password_hash: str) -> str:
    return hmac.new(
        _derived_web_key("password-reset-binding"),
        password_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_web_password_reset_url(email: str, password_hash: str) -> str:
    web_base_url = getattr(Config, "WEB_BASE_URL", "").rstrip("/")

    if not web_base_url or not password_hash:
        raise RuntimeError("Password reset is not configured.")

    now = datetime.now(timezone.utc)
    reset_token = jwt.encode(
        {
            "type": "password_reset",
            "iss": WEB_TOKEN_ISSUER,
            "aud": WEB_RESET_AUDIENCE,
            "sub": email,
            "email": email,
            "password_fingerprint": _password_fingerprint(password_hash),
            "jti": secrets.token_urlsafe(24),
            "iat": now,
            "exp": now + timedelta(minutes=RESET_TOKEN_MINUTES),
        },
        _derived_web_key("password-reset-token"),
        algorithm="HS256",
    )

    return f"{web_base_url}/forgot-password?token={reset_token}"


def _send_password_reset_email(user_email: str, user_name: str, reset_url: str) -> None:
    admin_email = getattr(Config, "ADMIN_EMAIL", "")
    admin_name = getattr(Config, "ADMIN_NAME", "ArcheoDB")
    sender = (getattr(Config, "MAIL_DEFAULT_SENDER", "") or admin_email).strip()
    reply_to = (getattr(Config, "MAIL_REPLY_TO", "") or admin_email).strip()
    server = (getattr(Config, "MAIL_SERVER", "localhost") or "").strip()
    port = int(getattr(Config, "MAIL_PORT", 25) or 25)
    timeout = int(getattr(Config, "MAIL_TIMEOUT", 10) or 10)
    username = (getattr(Config, "MAIL_USERNAME", "") or "").strip()
    password = getattr(Config, "MAIL_PASSWORD", "") or ""
    use_tls = bool(getattr(Config, "MAIL_USE_TLS", False))
    use_ssl = bool(getattr(Config, "MAIL_USE_SSL", False))

    if not sender or not server:
        raise RuntimeError("Outgoing password reset email is not configured.")
    if use_tls and use_ssl:
        raise RuntimeError("MAIL_USE_TLS and MAIL_USE_SSL cannot both be enabled.")

    msg = EmailMessage()
    msg["Subject"] = "Password reset for ArcheoDB"
    msg["From"] = sender
    msg["To"] = user_email
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(
        f"Hi {user_name},\n\n"
        f"You requested password reset for ArcheoDB Mobile.\n"
        f"To set a new password, open the following link in the web application:\n\n"
        f"{reset_url}\n\n"
        f"This link is valid for {RESET_TOKEN_MINUTES} minutes.\n\n"
        f"If you did not request this reset, please contact {admin_name} ({admin_email}).\n\n"
        f"Have a nice day,\nArcheoDB team"
    )

    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(server, port, timeout=timeout, context=context) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)
        return

    with smtplib.SMTP(server, port, timeout=timeout) as smtp:
        if use_tls:
            smtp.starttls(context=context)
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)


@auth_bp.post("/api/mobile/auth/login")
@limiter.limit("5 per minute")
def login():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""

    if not email or not password:
        return _json_error("Missing email or password.", 400)

    try:
        with auth_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT mail, name, password_hash, group_role, enabled
                    FROM public.v_app_login_users
                    WHERE mail = %s
                    """,
                    (email,),
                )
                row = cur.fetchone()

        if not row:
            logger.warning("Mobile login failed: unknown user %s", email)
            return _json_error("Invalid credentials.", 401)

        user_email, user_name, password_hash, user_role, enabled = row

        if not enabled:
            logger.warning("Mobile login denied: disabled user %s", email)
            return _json_error("Your account is inactive. Please contact administrator.", 403)

        if not password_hash or not check_password_hash(password_hash, password):
            logger.warning("Mobile login failed: invalid password for %s", email)
            return _json_error("Invalid credentials.", 401)

        logger.info("Mobile login succeeded for %s role=%s", user_email, user_role or "")
        return _login_response(user_email, user_name, user_role)

    except Exception as e:
        logger.exception("Mobile login error for %s: %s", email, e)
        return _json_error("Internal server error.", 500)


@auth_bp.post("/api/mobile/auth/qr-login")
@limiter.limit("10 per minute")
def qr_login():
    payload = request.get_json(silent=True) or {}
    login_code = (payload.get("code") or "").strip()

    if not QR_LOGIN_CODE_PATTERN.fullmatch(login_code):
        return _json_error("Invalid or expired QR login code.", 401)

    token_hash = hashlib.sha256(login_code.encode("ascii")).hexdigest()

    try:
        with auth_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_mail, user_name, user_role, user_enabled
                    FROM public.consume_mobile_login_grant(%s)
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
            conn.commit()

        if not row:
            logger.warning("Mobile QR login rejected: invalid, expired, or used grant")
            return _json_error("Invalid or expired QR login code.", 401)

        user_email, user_name, user_role, enabled = row
        if not enabled:
            logger.warning("Mobile QR login denied: disabled user %s", user_email)
            return _json_error("Your account is inactive. Please contact administrator.", 403)

        logger.info("Mobile QR login succeeded for %s role=%s", user_email, user_role or "")
        return _login_response(user_email, user_name, user_role)
    except Exception as e:
        logger.exception("Mobile QR login error: %s", e)
        return _json_error("Internal server error.", 500)


@auth_bp.post("/api/mobile/auth/forgot-password")
@limiter.limit("3 per hour")
def forgot_password():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip()

    if not email:
        return _json_error("Missing email.", 400)

    try:
        with auth_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT mail, name, password_hash, enabled
                    FROM public.v_app_login_users
                    WHERE mail = %s
                    """,
                    (email,),
                )
                row = cur.fetchone()

        if not row or not row[3]:
            logger.warning("Mobile password reset requested for missing or disabled user %s", email)
            return jsonify(
                {
                    "message": "If the account exists, a reset email was sent and password reset continues in the web application.",
                }
            )

        user_email, user_name, password_hash, _enabled = row
        reset_url = _build_web_password_reset_url(user_email, password_hash)
        _send_password_reset_email(user_email, user_name or "", reset_url)

        logger.info("Mobile password reset email sent for %s", user_email)
        return jsonify(
            {
                "message": "A reset email was sent. Continue password reset in the web application.",
            }
        )

    except Exception as e:
        logger.exception("Mobile forgot-password error for %s: %s", email, e)
        return _json_error("Internal server error.", 500)
