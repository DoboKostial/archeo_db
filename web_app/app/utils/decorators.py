# app/utils/decorators.py
# helpers - decorators

# imports standard library
import jwt
from functools import wraps
from flask import session, redirect, flash, request, url_for
# imports from app
from config import Config
from app.logger import logger
from app.database import get_auth_connection
from app.utils.auth import get_user_role


# this function is a decorator and enables requirement of 'selected db' in routes
def require_selected_db(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'selected_db' not in session:
            flash("Please select the DB You would like to work upon.", "warning")
            logger.info("Redirect to /index due to missing 'selected_db' in session")
            return redirect('/index')
        return f(*args, **kwargs)
    return decorated_function



def archeolog_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.cookies.get('token')
        if not token:
            logger.warning("Admin access without token -> /login")
            return redirect('/login')

        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            email = payload.get('email')
        except jwt.ExpiredSignatureError:
            logger.warning("Expired token on admin access -> /login")
            return redirect('/login')
        except jwt.InvalidTokenError:
            logger.warning("Invalid token on admin access -> /login")
            return redirect('/login')

        # check role directly from DB
        role = None
        try:
            with get_auth_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(get_user_role(), (email,))
                    role = cur.fetchone()[0] if cur.rowcount else None
        except Exception as e:
            logger.error(f"Role check failed for {email}: {e}")
            return redirect(url_for('main.index'))

        if role != 'archeolog':
            logger.warning(f"User {email} (role={role}) blocked from admin")
            return redirect(url_for('main.index'))

        # renewing session for further use (eg. flashy/UI)
        session['user_email'] = email
        session['user_role'] = role
        return f(*args, **kwargs)
    return decorated_function



def float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None