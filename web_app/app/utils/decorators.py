# app/utils/decorators.py
# helpers - decorators

from functools import wraps
from flask import g, session, redirect, flash, url_for
# imports from app
from app.logger import logger
from app.utils.storage import validate_db_name


# this function is a decorator and enables requirement of 'selected db' in routes
def require_selected_db(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        selected_db = session.get('selected_db')
        try:
            validate_db_name(selected_db)
        except ValueError:
            session.pop('selected_db', None)
            flash("Please select the DB You would like to work upon.", "warning")
            logger.warning("Redirect to /index due to missing or invalid 'selected_db' in session")
            return redirect('/index')
        return f(*args, **kwargs)
    return decorated_function



def archeolog_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        email = getattr(g, 'user_email', '')
        role = getattr(g, 'user_role', '')

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
