# web_app/app/routes/main.py
import os
import hashlib
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from flask import Blueprint, render_template, redirect, request, session, flash, Response
from flask import g
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing

from config import Config
from app.logger import logger
from app.database import get_auth_connection
from app.queries import (
    get_user_name_and_last_login,
    get_pg_version,
    get_terrain_db_list,
    get_terrain_db_sizes,
    create_mobile_login_grant,
)
from app.utils.analyze_checks import count_bad_checks
from app.utils.storage import validate_db_name

main_bp = Blueprint("main", __name__)

_DIRECTORY_SIZE_CACHE = {}
_DIRECTORY_SIZE_CACHE_LOCK = threading.Lock()


def _directory_size_bytes(path: str) -> int:
    cache_key = os.path.realpath(path)
    now = time.monotonic()
    ttl = int(getattr(Config, "DIRECTORY_SIZE_CACHE_SECONDS", 300))
    with _DIRECTORY_SIZE_CACHE_LOCK:
        cached = _DIRECTORY_SIZE_CACHE.get(cache_key)
        if cached and now - cached[0] < ttl:
            return cached[1]

    total = 0
    if not os.path.isdir(path):
        return total

    for root, _dirs, files in os.walk(path):
        for filename in files:
            file_path = os.path.join(root, filename)
            try:
                total += os.path.getsize(file_path)
            except OSError:
                logger.warning(f"Skipping unreadable file while counting data size: {file_path}")

    with _DIRECTORY_SIZE_CACHE_LOCK:
        if len(_DIRECTORY_SIZE_CACHE) >= 256:
            _DIRECTORY_SIZE_CACHE.clear()
        _DIRECTORY_SIZE_CACHE[cache_key] = (now, total)
    return total


def _mobile_api_qr_payload(login_code: str) -> str:
    mobile_api_base_url = (getattr(Config, "MOBILE_API_BASE_URL", "") or "").strip()
    return (
        "archeodb-mobile://login"
        f"?server={quote(mobile_api_base_url, safe='')}"
        f"&code={quote(login_code, safe='')}"
    )


def _mobile_login_grant_seconds() -> int:
    configured = int(getattr(Config, "MOBILE_LOGIN_GRANT_SECONDS", 120))
    return max(30, min(configured, 300))


def _create_mobile_login_code(user_email: str) -> str:
    login_code = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(login_code.encode("ascii")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_mobile_login_grant_seconds())

    conn = get_auth_connection()
    try:
        create_mobile_login_grant(conn, user_email, token_hash, expires_at)
    finally:
        conn.close()

    return login_code


def _mobile_api_qr_svg(payload: str) -> str:
    qr_widget = qr.QrCodeWidget(payload)
    left, bottom, right, top = qr_widget.getBounds()
    width = right - left
    height = top - bottom

    drawing = Drawing(
        width,
        height,
        transform=[1, 0, 0, 1, -left, -bottom],
    )
    drawing.add(qr_widget)
    return renderSVG.drawToString(drawing)


@main_bp.route("/")
def root():
    return redirect("/index")


@main_bp.route("/index")
def index():
    # The gatekeeper guarantees authentication
    user_email = g.user_email
    user_role = g.user_role
    user_name_from_token = g.user_name
    selected_db = session.get("selected_db")
    selected_db_bad_checks = None

    try:
        conn = get_auth_connection()
        cur = conn.cursor()

        # User info (including last_login from DB if available)
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
        db_sizes = []
        for row in terrain_dbs:
            db_name = row[0]
            db_bytes = int(row[1] or 0)
            files_bytes = _directory_size_bytes(os.path.join(Config.DATA_DIR, db_name))
            total_bytes = db_bytes + files_bytes
            db_sizes.append(
                {
                    "name": db_name,
                    "db_size_mb": round(db_bytes / (1024 * 1024), 2),
                    "files_size_mb": round(files_bytes / (1024 * 1024), 2),
                    "total_size_mb": round(total_bytes / (1024 * 1024), 2),
                    "size_mb": round(total_bytes / (1024 * 1024), 2),
                }
            )

        available_dbs = {db["name"] for db in db_sizes}
        if selected_db:
            try:
                validate_db_name(selected_db)
                if selected_db in available_dbs:
                    selected_db_bad_checks = count_bad_checks(selected_db)
            except Exception as e:
                selected_db_bad_checks = None
                logger.warning(f"Could not compute analyze BAD checks for {selected_db}: {e}")

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

    return render_template(
        "index.html",
        user_name=user_name,
        last_login=last_login.strftime("%Y-%m-%d") if last_login else "You are logged first time.",
        pg_version=pg_version,
        db_sizes=db_sizes,
        selected_db=selected_db,
        selected_db_bad_checks=selected_db_bad_checks,
        user_role=user_role,
        app_version=getattr(Config, "APP_VERSION", ""),
        mobile_api_base_url=(getattr(Config, "MOBILE_API_BASE_URL", "") or "").strip(),
        mobile_login_grant_seconds=_mobile_login_grant_seconds(),
    )


@main_bp.route("/mobile-api-qr.svg")
def mobile_api_qr():
    mobile_api_base_url = (getattr(Config, "MOBILE_API_BASE_URL", "") or "").strip()
    if not mobile_api_base_url:
        return Response(status=404)

    try:
        login_code = _create_mobile_login_code(g.user_email)
        svg = _mobile_api_qr_svg(_mobile_api_qr_payload(login_code))
    except Exception as e:
        logger.error(f"Error generating mobile login QR for {g.user_email}: {e}")
        return Response(status=500)

    response = Response(svg, mimetype="image/svg+xml")
    response.headers["Cache-Control"] = "no-store, no-cache, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@main_bp.route("/select-db", methods=["POST"])
def select_db():
    # The gatekeeper guarantees authentication
    selected_db = (request.form.get("selected_db") or "").strip()

    try:
        validate_db_name(selected_db)
    except ValueError:
        session.pop("selected_db", None)
        flash("No terrain DB was chosen!", "warning")
        return redirect("/index")

    conn = None
    try:
        conn = get_auth_connection()
        if selected_db not in get_terrain_db_list(conn):
            session.pop("selected_db", None)
            logger.warning(f"Rejected unavailable terrain DB selection: {selected_db}")
            flash("The selected terrain DB is not available.", "warning")
            return redirect("/index")
    except Exception as e:
        logger.error(f"Failed to validate terrain DB selection: {e}")
        flash("The terrain DB selection could not be validated.", "danger")
        return redirect("/index")
    finally:
        if conn is not None:
            conn.close()

    session["selected_db"] = selected_db
    flash(f'Terrain DB "{selected_db}" was chosen ---> this will be Your working DB while logged in.', "success")

    return redirect("/index")
