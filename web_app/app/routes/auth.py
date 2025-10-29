# web_app/app/routes/auth.py

from datetime import datetime, timedelta
import jwt
from flask import Blueprint, request, render_template, jsonify, redirect, url_for, make_response
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
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

auth_bp = Blueprint('auth', __name__)


# login endpoint for application
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    # --- accept both JSON and HTML form ---
    email = password = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip()
        password = data.get('password') or ''
    else:
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''

    if not email or not password:
        logger.warning("Login failed: missing email or password")
        if request.is_json:
            return jsonify({"error": "Missing email or password."}), 400
        flash("Missing email or password.", "danger")
        return redirect(url_for('auth.login'))

    logger.info(f"Login attempt: {email}")
    conn = None
    try:
        conn = get_auth_connection()

        # account enabled?
        enabled = is_user_enabled(conn, email)
        if enabled is False:
            logger.warning(f"Login denied, account locked for: {email}")
            if request.is_json:
                return jsonify({"error": "Your account is inactive. Please contact administrator."}), 403
            flash("Your account is inactive. Please contact administrator.", "danger")
            return redirect(url_for('auth.login'))

        # password check
        password_hash = get_user_password_hash(conn, email)
        if password_hash and check_password_hash(password_hash, password):
            token = jwt.encode(
                {"email": email, "exp": datetime.utcnow() + timedelta(hours=1)},
                Config.SECRET_KEY,
                algorithm="HS256",
            )
            logger.info(f"Successful login for: {email}")

            if request.is_json:
                resp = make_response(jsonify({"success": True}))
            else:
                resp = make_response(redirect(url_for('main.index')))

            # common cookie settings
            resp.set_cookie('token', token, httponly=True, samesite='Lax')
            return resp

        # wrong credentials
        logger.warning(f"Invalid credentials for: {email}")
        if request.is_json:
            return jsonify({"error": "Invalid credentials."}), 403
        flash("Invalid credentials.", "danger")
        return redirect(url_for('auth.login'))

    except Exception as e:
        logger.error(f"Error during login verification for {email}: {e}")
        if request.is_json:
            return jsonify({"error": "Server fault"}), 500
        flash("Internal server error during login.", "danger")
        return redirect(url_for('auth.login'))
    finally:
        if conn:
            try: conn.close()
            except Exception: pass



# logic for reseting forgotten password
@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        logger.info(f"GET /forgot-password from {request.remote_addr}")
        return render_template('forgot_password.html')

    data = request.get_json()
    email = data.get('email') if data else None

    logger.info(f"Password reset requested from {request.remote_addr} for email: {email}")

    try:
        conn = get_auth_connection()
        user_name = get_enabled_user_name_by_email(conn, email)

        if not user_name:
            logger.warning(f"Password reset failed – no such enabled user: {email}")
            return jsonify({"error": "This account does not exist or is disabled."}), 400

        token = jwt.encode({
            'email': email,
            'exp': datetime.utcnow() + timedelta(minutes=30)
        }, Config.SECRET_KEY, algorithm='HS256')

        # POZN.: po přesunu do auth blueprintu se endpoint jmenuje 'auth.emergency_login'
        reset_url = url_for('auth.emergency_login', token=token, _external=True)

        send_password_reset_email(email, user_name, reset_url)

        logger.info(f"Password reset link sent to {email}")
        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Fatal error during password reset for {email} from {request.remote_addr}: {repr(e)}")
        return jsonify({"error": "Internal server error."}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


# here logic for emergency login with token per user
@auth_bp.route('/emergency-login/<token>')
def emergency_login(token):
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("Expiration of emergency JWT token -> redirecting to /login")
        return redirect('/login')
    except jwt.InvalidTokenError:
        logger.warning("Non valid emergency JWT token: redirecting to /login")
        return redirect('/login')

    conn = get_auth_connection()
    is_enabled = is_user_enabled(conn, user_email)
    if not is_enabled:
        logger.warning(f"Emergency login of disabled or non-existing user: {user_email}")
        conn.close()
        return redirect('/login')

    logger.info(f"Emergency login successfull for user: {user_email}")
    conn.close()

    response = redirect('/profile')
    response.set_cookie(
        'token',
        token,
        httponly=True,
        samesite='Lax',
        max_age=60 * 60 * 24  # 24 hours – customizable
    )
    return response


# user logout and get to main login endpoint
@auth_bp.route('/logout')
def logout():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload.get('email')

        if user_email:
            conn = get_auth_connection()
            update_last_login(conn, user_email)
            conn.close()

        logger.info(f"User {user_email} loged out successfully")
    except Exception as e:
        logger.error(f"Error during logout: {e}")

    response = make_response(redirect('/login'))
    response.set_cookie('token', '', expires=0)
    return response


# endpoint about currently logged in user with password change possibility
# beware of mail function - postfix should be configured on machine
@auth_bp.route('/profile', methods=['GET', 'POST'])
def profile():
    token = request.cookies.get('token')
    if not token:
        logger.warning("Access on /profile without token -> redirecting to /login")
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expiration -> redirecting to /login")
        return redirect('/login')

    conn = get_auth_connection()
    try:
        cur = conn.cursor()

        # Retrieving user role
        cur.execute(get_user_role(), (user_email,))
        user_role = cur.fetchone()[0] if cur.rowcount else 'neznámá'

        if request.method == 'POST':
            logger.info(f"Request for password change for user: {user_email}")
            data = request.get_json() or {}
            new_password = data.get('new_password')
            confirm_password = data.get('confirm_password')

            if new_password != confirm_password or not new_password:
                logger.warning(f"The change of password for {user_email} failed - passwords are not same or empty.")
                return jsonify({'error': 'Given passwords are not the same or are empty.'}), 400

            password_hash = generate_password_hash(new_password)
            update_user_password_hash(conn, user_email, password_hash)

            user_name_for_email = get_user_name_by_email(conn, user_email) or "uživatel"

            logger.info(f"Password changed successfully for {user_email}")
            send_password_change_email(user_email, user_name_for_email)
            logger.info(f"Confirming email about password change was sent to {user_email}")

            return jsonify({'message': 'Password was changed and confirming email was sent.'})

        # GET request – profile data
        user_data = get_full_user_data(conn, user_email)
        if not user_data:
            logger.error(f"User {user_email} was not found in database -> redirecting to /login")
            return redirect('/login')

        user_name, mail, last_login = user_data
        citation = get_random_citation(conn)

        if not last_login:
            logger.warning(f"User {user_email} has no recorded last_login.")
            last_login_str = "N/A"
        else:
            last_login_str = last_login.strftime('%Y-%m-%d')

        logger.info(f"Fetching the profile of user {user_email}")

        return render_template(
            'profile.html',
            user_name=user_name,
            user_email=mail,
            last_login=last_login_str,
            citation=citation,
            user_role=user_role
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
