# web_app/app/routes/main.py
from flask import Blueprint, render_template, redirect, session, flash, get_flashed_messages
from flask import g

from config import Config
from app.logger import logger
from app.database import get_auth_connection
from app.queries import (
    get_user_name_and_last_login,
    get_pg_version,
    get_terrain_db_sizes,
)

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def root():
    return redirect("/index")


@main_bp.route("/index")
def index():
    # Gatekeeper garantuje přihlášení
    user_email = g.user_email
    user_role = g.user_role
    user_name_from_token = g.user_name

    try:
        conn = get_auth_connection()
        cur = conn.cursor()

        # User info (pokud chceš last_login z DB)
        user_data = get_user_name_and_last_login(conn, user_email)
        if user_data:
            user_name, last_login = user_data
        else:
            user_name, last_login = user_name_from_token or user_email, None

        # PostgreSQL version
        cur.execute(get_pg_version())
        pg_version = cur.fetchone()[0]

        # Existing databases
        cur.execute(get_terrain_db_sizes())
        terrain_dbs = cur.fetchall()
        db_sizes = [{"name": row[0], "size_mb": round(row[1] / (1024 * 1024), 2)} for row in terrain_dbs]

    except Exception as e:
        logger.error(f"Error fetching data for /index: {e}")
        return redirect("/login")
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
    flashed = get_flashed_messages(category_filter=["success"])
    if flashed:
        db_selected_message = flashed[0]

    return render_template(
        "index.html",
        user_name=user_name,
        last_login=last_login.strftime("%Y-%m-%d") if last_login else "You are logged first time.",
        pg_version=pg_version,
        db_sizes=db_sizes,
        user_role=user_role,
        db_selected_message=db_selected_message,
        app_version=getattr(Config, "APP_VERSION", ""),
    )


@main_bp.route("/select-db", methods=["POST"])
def select_db():
    # Gatekeeper garantuje přihlášení
    selected_db = session.get("selected_db")
    chosen = None

    chosen = (session.get("selected_db") or "").strip()
    # (pozn.: tvoje původní logika bere z formu; nechávám správně z formu)
    # ---- oprava: čti z formu ----
    # (při přepsání si pohlídej, ať tady skutečně bereš request.form)
    from flask import request
    selected_db = request.form.get("selected_db")

    if selected_db:
        session["selected_db"] = selected_db
        flash(f'Terrain DB "{selected_db}" was chosen ---> this will be Your working DB while logged in.', "success")
    else:
        flash("No terrain DB was chosen!", "warning")

    return redirect("/index")
