# web_app/app/routes/terr_photo.py
import os
from flask import (
    Blueprint, request, render_template, redirect, url_for,
    flash, session, send_from_directory
)
from werkzeug.utils import secure_filename
from PIL import Image

from app.logger import logger
from app.database import get_terrain_connection
from app.utils import require_selected_db, get_photo_dirs

terr_photo_bp = Blueprint('terr_photo', __name__)

@terr_photo_bp.route('/upload-foto', methods=['GET', 'POST'])
@require_selected_db
def upload_foto():
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)

    base_dir, thumb_dir = get_photo_dirs(selected_db)
    os.makedirs(base_dir, exist_ok=True)
    os.makedirs(thumb_dir, exist_ok=True)

    if request.method == 'POST':
        file = request.files.get('file')
        datum = request.form.get('datum') or None
        author = request.form.get('author') or None
        notes = request.form.get('notes') or None
        selected_sjs = request.form.getlist('ref_sj')
        selected_polygon = request.form.get('ref_polygon')  # reserved for future use

        if file:
            filename = secure_filename(file.filename)
            if not filename:
                flash('Invalid file name.', 'danger')
                return redirect(url_for('terr_photo.upload_foto'))

            filepath = os.path.join(base_dir, filename)
            file.save(filepath)

            # Thumbnail
            try:
                with Image.open(filepath) as img:
                    img.thumbnail((200, 150))
                    thumb_path = os.path.join(
                        thumb_dir,
                        f"{os.path.splitext(filename)[0]}_thumb.jpeg"
                    )
                    img.save(thumb_path, 'JPEG')
            except Exception as e:
                logger.error(f"[{selected_db}] Failed to create thumbnail for '{filename}': {e}")

            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO tab_foto (id_foto, datum, author, notes)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (filename, datum, author, notes)
                        )
                        for sj in selected_sjs:
                            cur.execute(
                                """
                                INSERT INTO tabaid_foto_sj (ref_foto, ref_sj)
                                VALUES (%s, %s)
                                """,
                                (filename, sj)
                            )
                logger.info(f"[{selected_db}] Terrain photo '{filename}' uploaded.")
                flash('Terrain photo was uploaded successfully.', 'success')
                return redirect(url_for('terr_photo.upload_foto'))

            except Exception as e:
                logger.error(f"[{selected_db}] Error during photo upload: {e}")
                flash(f'Error during the upload: {str(e)}', 'danger')

    # GET – prepare form data
    sj_options = []
    polygon_options = []
    author_options = []
    recent_photos = []

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id_sj FROM tab_sj ORDER BY id_sj")
            sj_options = [row[0] for row in cur.fetchall()]

            cur.execute("SELECT polygon_name FROM tab_polygons ORDER BY polygon_name")
            polygon_options = [row[0] for row in cur.fetchall()]

            cur.execute("SELECT mail FROM gloss_personalia ORDER BY mail")
            author_options = [row[0] for row in cur.fetchall()]

            cur.execute(
                """
                SELECT id_foto FROM tab_foto
                WHERE datum IS NOT NULL
                ORDER BY datum DESC
                LIMIT 10
                """
            )
            recent_photos = cur.fetchall()

    except Exception as e:
        logger.error(f"[{selected_db}] Error loading form data for terrain photos: {e}")
        flash('Error while loading form data.', 'danger')
    finally:
        conn.close()

    return render_template(
        'upload_foto.html',
        sj_options=sj_options,
        polygon_options=polygon_options,
        author_options=author_options,
        recent_photos=recent_photos,
        selected_db=selected_db
    )

@terr_photo_bp.route('/terr_foto/<path:filename>')
@require_selected_db
def serve_terr_foto(filename):
    selected_db = session.get('selected_db')
    base_dir, _ = get_photo_dirs(selected_db)
    return send_from_directory(base_dir, filename)

@terr_photo_bp.route('/terr_foto/thumbs/<path:filename>')
@require_selected_db
def serve_terr_thumb(filename):
    selected_db = session.get('selected_db')
    _, thumb_dir = get_photo_dirs(selected_db)
    return send_from_directory(thumb_dir, filename)
