# web_app/app/routes/main.py
from flask import Blueprint, request, render_template, redirect, session, flash, get_flashed_messages
import jwt

from config import Config
from app.logger import logger
from app.database import get_auth_connection
from app.queries import (
    get_user_name_and_last_login,
    get_user_role,
    get_pg_version,
    get_terrain_db_sizes,
)

main_bp = Blueprint('main', __name__)

# getting to webroot - check, if logged in, if not, redirect
@main_bp.route('/')
def root():
    return redirect('/index')


# if logged in, redirected here - basic info about app
@main_bp.route('/index')
def index():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        user_email = payload['email']
    except jwt.ExpiredSignatureError:
        return redirect('/login')

    try:
        conn = get_auth_connection()
        cur = conn.cursor()

        # User info
        user_data = get_user_name_and_last_login(conn, user_email)
        if not user_data:
            return redirect('/login')
        user_name, last_login = user_data

        # Logged-in user role
        cur.execute(get_user_role(), (user_email,))
        user_role = cur.fetchone()[0] if cur.rowcount else 'neznámá'

        # PostgreSQL version
        cur.execute(get_pg_version())
        pg_version = cur.fetchone()[0]

        # Existing databases
        cur.execute(get_terrain_db_sizes())
        terrain_dbs = cur.fetchall()
        db_sizes = [
            {'name': row[0], 'size_mb': round(row[1] / (1024 * 1024), 2)}
            for row in terrain_dbs
        ]

    except Exception as e:
        logger.error(f"Error fetching data for /index: {e}")
        return redirect('/login')
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    db_selected_message = None
    flashed = get_flashed_messages(category_filter=['success'])
    if flashed:
        db_selected_message = flashed[0]

    return render_template(
        'index.html',
        user_name=user_name,
        last_login=last_login.strftime("%Y-%m-%d") if last_login else "You are logged first time.",
        pg_version=pg_version,
        db_sizes=db_sizes,
        user_role=user_role,
        db_selected_message=db_selected_message,
        app_version=Config.APP_VERSION,
    )


# user would have to choose terrain DB to work with - here logic
@main_bp.route('/select-db', methods=['POST'])
def select_db():
    token = request.cookies.get('token')
    if not token:
        return redirect('/login')

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        # user_email = payload['email']  # (nepoužito, ale ponechávám logiku validace tokenu)
    except jwt.ExpiredSignatureError:
        return redirect('/login')

    selected_db = request.form.get('selected_db')
    if selected_db:
        session['selected_db'] = selected_db
        flash(f'Terrain DB "{selected_db}" was chosen ---> this will be Your working DB while logged in.', 'success')
    else:
        flash('No terrain DB was chosen!', 'warning')

    return redirect('/index')
