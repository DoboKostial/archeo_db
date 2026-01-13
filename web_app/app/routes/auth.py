# web_app/app/routes/auth.py

from datetime import datetime, timedelta
import jwt
from flask import Blueprint, request, render_template, jsonify, redirect, url_for, make_response, flash
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from app.extensions import csrf
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
)
from app.utils.auth import send_password_reset_email, send_password_change_email

auth_bp = Blueprint("auth", __name__)

JWT_SESSION_MINUTES = 60
RESET_TOKEN_MINUTES = 120


@auth_bp.route("/login", methods=["GET", "POST"])
@csrf.exempt
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

        # update last_login on successful login (správná semantika)
        try:
            update_last_login(conn, email)
        except Exception as e:
            logger.warning(f"Could not update last_login for {email}: {e}")

        token = jwt.encode(
            {
                "email": email,
                "name": name,
                "role": role,
                "iat": datetime.utcnow(),
                "exp": datetime.utcnow() + timedelta(minutes=JWT_SESSION_MINUTES),
            },
            Config.SECRET_KEY,
            algorithm="HS256",
        )

        logger.info(f"Successful login for: {email} role={role}")

        if request.is_json:
            resp = make_response(jsonify({"success": True}))
        else:
            # pokud přijde next=, vrať se tam
            nxt = request.args.get("next")
            resp = make_response(redirect(nxt or url_for("main.index")))

        resp.set_cookie(
            "token",
            token,
            httponly=True,
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
@csrf.exempt
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

        # token present => show reset form
        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
            if payload.get("purpose") != "pwreset":
                raise jwt.InvalidTokenError("wrong purpose")
            email = payload.get("email")
        except jwt.ExpiredSignatureError:
            flash("Reset link expired. Please request a new one.", "danger")
            return redirect(url_for("auth.forgot_password"))
        except Exception:
            flash("Invalid reset link. Please request a new one.", "danger")
            return redirect(url_for("auth.forgot_password"))

        return render_template("reset_password.html", token=token, email=email)

    # --- POST ---
    # Accept JSON or form
    data = request.get_json(silent=True) or {}
    form_token = (data.get("token") or request.form.get("token") or "").strip()
    if form_token:
        # reset submit
        new_password = data.get("new_password") or request.form.get("new_password") or ""
        confirm_password = data.get("confirm_password") or request.form.get("confirm_password") or ""

        if not new_password or new_password != confirm_password:
            if request.is_json:
                return jsonify({"error": "Passwords do not match or are empty."}), 400
            flash("Passwords do not match or are empty.", "danger")
            return redirect(url_for("auth.forgot_password", token=form_token))

        try:
            payload = jwt.decode(form_token, Config.SECRET_KEY, algorithms=["HS256"])
            if payload.get("purpose") != "pwreset":
                raise jwt.InvalidTokenError("wrong purpose")
            email = payload["email"]
        except jwt.ExpiredSignatureError:
            if request.is_json:
                return jsonify({"error": "Reset link expired."}), 400
            flash("Reset link expired. Please request a new one.", "danger")
            return redirect(url_for("auth.forgot_password"))
        except Exception:
            if request.is_json:
                return jsonify({"error": "Invalid reset link."}), 400
            flash("Invalid reset link. Please request a new one.", "danger")
            return redirect(url_for("auth.forgot_password"))

        conn = get_auth_connection()
        try:
            # must still be enabled
            user_name = get_enabled_user_name_by_email(conn, email)
            if not user_name:
                if request.is_json:
                    return jsonify({"error": "This account does not exist or is disabled."}), 400
                flash("This account does not exist or is disabled.", "danger")
                return redirect(url_for("auth.forgot_password"))

            password_hash = generate_password_hash(new_password)
            update_user_password_hash(conn, email, password_hash)

            send_password_change_email(email, user_name)

            logger.info(f"Password reset successful for {email}")

            if request.is_json:
                return jsonify({"success": True})
            flash("Password was reset. Please log in.", "success")
            return redirect(url_for("auth.login"))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # reset request submit (no token)
    email = (data.get("email") or request.form.get("email") or "").strip()
    logger.info(f"Password reset requested from {request.remote_addr} for email: {email}")

    if not email:
        if request.is_json:
            return jsonify({"error": "Missing email."}), 400
        flash("Missing email.", "danger")
        return redirect(url_for("auth.forgot_password"))

    conn = None
    try:
        conn = get_auth_connection()
        user_name = get_enabled_user_name_by_email(conn, email)

        if not user_name:
            logger.warning(f"Password reset failed – no such enabled user: {email}")
            return jsonify({"error": "This account does not exist or is disabled."}), 400

        reset_token = jwt.encode(
            {
                "email": email,
                "purpose": "pwreset",
                "iat": datetime.utcnow(),
                "exp": datetime.utcnow() + timedelta(minutes=RESET_TOKEN_MINUTES),
            },
            Config.SECRET_KEY,
            algorithm="HS256",
        )

        reset_url = url_for("auth.forgot_password", token=reset_token, _external=True)
        send_password_reset_email(email, user_name, reset_url)

        logger.info(f"Password reset link sent to {email}")
        return jsonify({"success": True})

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
    # logout je chráněný (gatekeeper), ale i kdyby token chyběl, redirect na login je OK
    response = make_response(redirect(url_for("auth.login")))
    response.set_cookie("token", "", expires=0)
    return response


@auth_bp.route("/profile", methods=["GET", "POST"])
def profile():
    # Tady už žádné ruční čtení tokenu – gatekeeper garantuje přihlášení
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

            if new_password != confirm_password or not new_password:
                logger.warning(f"Password change for {user_email} failed - mismatch/empty.")
                return jsonify({"error": "Given passwords are not the same or are empty."}), 400

            password_hash = generate_password_hash(new_password)
            update_user_password_hash(conn, user_email, password_hash)

            # pro e-mail vezmeme jméno z DB, fallback token
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
