# web_app/app/routes/main.py
import os
from urllib.parse import quote
from flask import Blueprint, render_template, redirect, session, flash, get_flashed_messages, Response
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
    get_terrain_db_sizes,
)

main_bp = Blueprint("main", __name__)


def _directory_size_bytes(path: str) -> int:
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
    return total


def _mobile_api_qr_payload() -> str:
    mobile_api_base_url = (getattr(Config, "MOBILE_API_BASE_URL", "") or "").strip()
    return f"archeodb-mobile://configure?server={quote(mobile_api_base_url, safe='')}"


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
        mobile_api_base_url=(getattr(Config, "MOBILE_API_BASE_URL", "") or "").strip(),
    )


@main_bp.route("/mobile-api-qr.svg")
def mobile_api_qr():
    mobile_api_base_url = (getattr(Config, "MOBILE_API_BASE_URL", "") or "").strip()
    if not mobile_api_base_url:
        return Response(status=404)

    try:
        svg = _mobile_api_qr_svg(_mobile_api_qr_payload())
    except Exception as e:
        logger.error(f"Error generating mobile API QR: {e}")
        return Response(status=500)

    return Response(svg, mimetype="image/svg+xml")


@main_bp.route("/select-db", methods=["POST"])
def select_db():
    # The gatekeeper guarantees authentication
    selected_db = session.get("selected_db")
    chosen = None

    chosen = (session.get("selected_db") or "").strip()
    # Note: the correct source here is the submitted form data
    # ---- fix: read from request.form ----
    # If this gets refactored later, make sure it still reads request.form here
    from flask import request
    selected_db = request.form.get("selected_db")

    if selected_db:
        session["selected_db"] = selected_db
        flash(f'Terrain DB "{selected_db}" was chosen ---> this will be Your working DB while logged in.', "success")
    else:
        flash("No terrain DB was chosen!", "warning")

    return redirect("/index")
