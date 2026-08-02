# web_app/app/routes/auth.py

from collections import deque
from threading import Lock
from time import monotonic
from urllib.parse import unquote, urlsplit

import jwt
from flask import Blueprint, current_app, request, render_template, jsonify, redirect, url_for, make_response, flash
from werkzeug.security import check_password_hash, generate_password_hash

from app.logger import logger
from app.database import get_auth_connection
from app.queries import (
    is_user_enabled,
    update_user_password_hash,
    get_user_password_hash,
    get_enabled_user_name_by_email,
    update_last_login,
    get_user_role,
    get_user_name_by_email,
    get_full_user_data,
    get_random_citation,
    get_password_reset_state_for_update,
)
from app.utils.auth import send_password_reset_email, send_password_change_email
from app.utils.tokens import (
    create_password_reset_token,
    create_session_token,
    decode_password_reset_token,
    password_reset_token_matches,
)

auth_bp = Blueprint("auth", __name__)

JWT_SESSION_MINUTES = 60
RESET_TOKEN_MINUTES = 30

_RATE_LIMIT_LOCK = Lock()
_RATE_LIMIT_BUCKETS = {}


def _rate_limited(scope: str, identity: str, limit: int, window_seconds: int) -> bool:
    now = monotonic()
    key = (scope, identity)
    with _RATE_LIMIT_LOCK:
        attempts = _RATE_LIMIT_BUCKETS.setdefault(key, deque())
        while attempts and attempts[0] <= now - window_seconds:
            attempts.popleft()
        if len(attempts) >= limit:
            return True
        attempts.append(now)

        if len(_RATE_LIMIT_BUCKETS) > 4096:
            stale_before = now - max(window_seconds, 3600)
            for bucket_key, bucket in list(_RATE_LIMIT_BUCKETS.items()):
                if not bucket or bucket[-1] <= stale_before:
                    _RATE_LIMIT_BUCKETS.pop(bucket_key, None)
        return False


def _clear_rate_limit(scope: str, identity: str) -> None:
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_BUCKETS.pop((scope, identity), None)


def _password_error(password: str) -> str | None:
    if len(password) < 12:
        return "Password must contain at least 12 characters."
    if not any(ch.islower() for ch in password):
        return "Password must contain a lowercase letter."
    if not any(ch.isupper() for ch in password):
        return "Password must contain an uppercase letter."
    if not any(ch.isdigit() for ch in password):
        return "Password must contain a number."
    return None


def _safe_next_url(target: str | None) -> str | None:
    if not target:
        return None

    decoded = target
    for _ in range(2):
        decoded = unquote(decoded)
    parsed = urlsplit(decoded)
    if (
        decoded.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
        or "\\" in decoded
        or any(ord(ch) < 32 for ch in decoded)
    ):
        return None
    return target


def _reset_url(token: str) -> str:
    base_url = str(current_app.config.get("BASE_URL") or "").rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("BASE_URL must be configured for password reset links.")
    return f"{base_url}{url_for('auth.forgot_password', token=token)}"


def _load_reset_account(token: str):
    payload = decode_password_reset_token(token)
    email = payload["email"]
    conn = get_auth_connection()
    try:
        user_name = get_enabled_user_name_by_email(conn, email)
        password_hash = get_user_password_hash(conn, email)
    finally:
        conn.close()

    if not user_name or not password_hash or not password_reset_token_matches(payload, password_hash):
        raise jwt.InvalidTokenError("password reset token has already been used or revoked")
    return email, user_name


def _consume_reset_token(token: str, new_password: str):
    payload = decode_password_reset_token(token)
    email = payload["email"]
    conn = get_auth_connection()
    try:
        reset_state = get_password_reset_state_for_update(conn, email)
        if not reset_state or not password_reset_token_matches(payload, reset_state[1]):
            raise jwt.InvalidTokenError("password reset token has already been used or revoked")
        update_user_password_hash(conn, email, generate_password_hash(new_password))
        return email, reset_state[0]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    # accept both JSON and HTML form
    if request.is_json:
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip()
        password = data.get("password") or ""
    else:
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""

    if not email or not password:
        logger.warning("Login failed: missing email or password")
        if request.is_json:
            return jsonify({"error": "Missing email or password."}), 400
        flash("Missing email or password.", "danger")
        return redirect(url_for("auth.login"))

    rate_identity = f"{request.remote_addr or 'unknown'}:{email.casefold()}"
    if _rate_limited("login", rate_identity, limit=10, window_seconds=15 * 60):
        logger.warning(f"Login rate limit reached for: {email}")
        if request.is_json:
            return jsonify({"error": "Too many login attempts. Please try again later."}), 429
        flash("Too many login attempts. Please try again later.", "danger")
        return redirect(url_for("auth.login"))

    logger.info(f"Login attempt: {email}")

    conn = None
    try:
        conn = get_auth_connection()

        # account enabled?
        enabled = is_user_enabled(conn, email)
        if enabled is False:
            logger.warning(f"Login denied, account disabled for: {email}")
            if request.is_json:
                return jsonify({"error": "Your account is inactive. Please contact administrator."}), 403
            flash("Your account is inactive. Please contact administrator.", "danger")
            return redirect(url_for("auth.login"))

        # password check
        password_hash = get_user_password_hash(conn, email)
        if not (password_hash and check_password_hash(password_hash, password)):
            logger.warning(f"Invalid credentials for: {email}")
            if request.is_json:
                return jsonify({"error": "Invalid credentials."}), 403
            flash("Invalid credentials.", "danger")
            return redirect(url_for("auth.login"))

        # load user name + role once, embed into JWT
        name = get_user_name_by_email(conn, email) or ""
        role = None
        try:
            with conn.cursor() as cur:
                cur.execute(get_user_role(), (email,))
                role = cur.fetchone()[0] if cur.rowcount else None
        except Exception:
            role = None
        role = role or ""

        _clear_rate_limit("login", rate_identity)

        # update last_login on successful login (correct semantics)
        try:
            update_last_login(conn, email)
        except Exception as e:
            logger.warning(f"Could not update last_login for {email}: {e}")

        token = create_session_token(email, name, role, JWT_SESSION_MINUTES)

        logger.info(f"Successful login for: {email} role={role}")

        submitted_next = data.get("next") if request.is_json else request.form.get("next")
        nxt = _safe_next_url(submitted_next or request.args.get("next"))
        destination = nxt or url_for("main.index")

        if request.is_json:
            resp = make_response(jsonify({"ok": True, "redirect": destination}))
        else:
            resp = make_response(redirect(destination))

        resp.set_cookie(
            "token",
            token,
            httponly=True,
            secure=bool(current_app.config.get("SESSION_COOKIE_SECURE", True)),
            samesite="Lax",
            max_age=JWT_SESSION_MINUTES * 60,
        )
        return resp

    except Exception as e:
        logger.error(f"Error during login verification for {email}: {e}")
        if request.is_json:
            return jsonify({"error": "Server fault"}), 500
        flash("Internal server error during login.", "danger")
        return redirect(url_for("auth.login"))

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """
    Public endpoint.

    Flow:
    - GET without token: show 'enter email' page (forgot_password.html)
    - POST without token: accept email, send reset link: /forgot-password?token=<jwt>
    - GET with token: show reset form (reset_password.html)
    - POST with token: set new password, then redirect to /login (or return JSON)
    """
    token = request.args.get("token") or None

    # --- GET ---
    if request.method == "GET":
        if not token:
            logger.info(f"GET /forgot-password from {request.remote_addr}")
            return render_template("forgot_password.html")

        try:
            email, _user_name = _load_reset_account(token)
        except jwt.ExpiredSignatureError:
            flash("Reset link expired. Please request a new one.", "danger")
            return redirect(url_for("auth.forgot_password"))
        except jwt.InvalidTokenError:
            flash("Invalid reset link. Please request a new one.", "danger")
            return redirect(url_for("auth.forgot_password"))
        except Exception as e:
            logger.error(f"Password reset token validation failed: {e}")
            flash("The reset link could not be validated.", "danger")
            return redirect(url_for("auth.forgot_password"))

        return render_template("reset_password.html", token=token, email=email)

    # --- POST ---
    # Accept JSON or form
    data = request.get_json(silent=True) or {}
    form_token = (data.get("token") or request.form.get("token") or "").strip()
    if form_token:
        if _rate_limited("password-reset-submit", request.remote_addr or "unknown", 10, 15 * 60):
            return jsonify({"error": "Too many password reset attempts. Please try again later."}), 429

        new_password = data.get("new_password") or request.form.get("new_password") or ""
        confirm_password = data.get("confirm_password") or request.form.get("confirm_password") or ""

        password_error = _password_error(new_password)
        if new_password != confirm_password or password_error:
            error = "Passwords do not match." if new_password != confirm_password else password_error
            if request.is_json:
                return jsonify({"error": error}), 400
            flash(error, "danger")
            return redirect(url_for("auth.forgot_password", token=form_token))

        try:
            email, user_name = _consume_reset_token(form_token, new_password)
        except jwt.ExpiredSignatureError:
            if request.is_json:
                return jsonify({"error": "Reset link expired."}), 400
            flash("Reset link expired. Please request a new one.", "danger")
            return redirect(url_for("auth.forgot_password"))
        except jwt.InvalidTokenError:
            if request.is_json:
                return jsonify({"error": "Invalid reset link."}), 400
            flash("Invalid reset link. Please request a new one.", "danger")
            return redirect(url_for("auth.forgot_password"))
        except Exception as e:
            logger.error(f"Password reset token validation failed: {e}")
            if request.is_json:
                return jsonify({"error": "The reset link could not be validated."}), 500
            flash("The reset link could not be validated.", "danger")
            return redirect(url_for("auth.forgot_password"))

        send_password_change_email(email, user_name)

        logger.info(f"Password reset successful for {email}")

        if request.is_json:
            return jsonify({"success": True})
        flash("Password was reset. Please log in.", "success")
        return redirect(url_for("auth.login"))

    # reset request submit (no token)
    email = (data.get("email") or request.form.get("email") or "").strip()
    logger.info(f"Password reset requested from {request.remote_addr} for email: {email}")

    if not email:
        if request.is_json:
            return jsonify({"error": "Missing email."}), 400
        flash("Missing email.", "danger")
        return redirect(url_for("auth.forgot_password"))

    remote_addr = request.remote_addr or "unknown"
    if _rate_limited("password-reset-ip", remote_addr, 10, 60 * 60):
        return jsonify({"error": "Too many password reset requests. Please try again later."}), 429

    generic_response = {
        "success": True,
        "message": "If an enabled account matches that email, a reset link will be sent.",
    }

    if _rate_limited("password-reset-email", email.casefold(), 3, 60 * 60):
        logger.warning(f"Password reset email rate limit reached for: {email}")
        return jsonify(generic_response)

    conn = None
    try:
        conn = get_auth_connection()
        user_name = get_enabled_user_name_by_email(conn, email)

        if not user_name:
            logger.info(f"Password reset requested for unknown or disabled account: {email}")
            return jsonify(generic_response)

        current_password_hash = get_user_password_hash(conn, email)
        if not current_password_hash:
            return jsonify(generic_response)

        reset_token = create_password_reset_token(email, current_password_hash, RESET_TOKEN_MINUTES)
        reset_url = _reset_url(reset_token)
        send_password_reset_email(email, user_name, reset_url)

        logger.info(f"Password reset link sent to {email}")
        return jsonify(generic_response)

    except Exception as e:
        logger.error(f"Fatal error during password reset for {email} from {request.remote_addr}: {repr(e)}")
        return jsonify({"error": "Internal server error."}), 500
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


@auth_bp.route("/logout")
def logout():
    # logout is protected by the gatekeeper, but redirecting to login is still fine if the token is missing
    response = make_response(redirect(url_for("auth.login")))
    response.set_cookie("token", "", expires=0)
    return response


@auth_bp.route("/profile", methods=["GET", "POST"])
def profile():
    # No manual token reading here; the gatekeeper guarantees authentication
    from flask import g

    user_email = getattr(g, "user_email", "")
    user_role = getattr(g, "user_role", "")
    user_name_from_token = getattr(g, "user_name", "")

    conn = get_auth_connection()
    cur = conn.cursor()
    try:
        if request.method == "POST":
            logger.info(f"Request for password change for user: {user_email}")
            data = request.get_json() or {}
            new_password = data.get("new_password")
            confirm_password = data.get("confirm_password")

            password_error = _password_error(new_password or "")
            if new_password != confirm_password or password_error:
                logger.warning(f"Password change for {user_email} failed validation.")
                error = "Passwords do not match." if new_password != confirm_password else password_error
                return jsonify({"error": error}), 400

            password_hash = generate_password_hash(new_password)
            update_user_password_hash(conn, user_email, password_hash)

            # for the email, use the name from DB, falling back to the token
            user_name_for_email = get_user_name_by_email(conn, user_email) or user_name_from_token or "user"
            send_password_change_email(user_email, user_name_for_email)

            logger.info(f"Password changed successfully for {user_email}")
            return jsonify({"message": "Password was changed and confirming email was sent."})

        # GET request – profile data
        user_data = get_full_user_data(conn, user_email)
        if not user_data:
            logger.error(f"User {user_email} not found in DB -> redirecting to /login")
            return redirect(url_for("auth.login"))

        user_name, mail, last_login = user_data
        citation = get_random_citation(conn)

        last_login_str = last_login.strftime("%Y-%m-%d") if last_login else "N/A"

        logger.info(f"Fetching profile for {user_email}")
        return render_template(
            "profile.html",
            user_name=user_name,
            user_email=mail,
            last_login=last_login_str,
            citation=citation,
            user_role=user_role,
        )

    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
