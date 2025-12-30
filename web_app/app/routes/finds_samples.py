# app/routes/finds_samples.py

from __future__ import annotations

import io
import os

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, jsonify, Response
)

from psycopg2.extras import Json

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db

from app.utils.media_map import MEDIA_TABLES, LINK_TABLES_FINDS, LINK_TABLES_SAMPLES

# reuse same utilities as polygon upload
from app.utils import storage
from app.utils.file_utils import (
    validate_extension, validate_mime, detect_mime, sha256_file
)
from app.utils.image_utils import make_thumbnail
from app.utils.exif_utils import extract_exif

from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.graphics.barcode import qr
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing

from app.queries import (
    list_find_types_sql, insert_find_type_sql,
    list_sample_types_sql, insert_sample_type_sql,
    list_polygons_names_sql,
    find_exists_sql, sample_exists_sql,
    insert_find_sql, update_find_sql, delete_find_sql, list_finds_sql, get_find_sql,
    insert_sample_sql, update_sample_sql, delete_sample_sql, list_samples_sql, get_sample_sql,
    link_find_photo_sql, link_find_sketch_sql,
    link_sample_photo_sql, link_sample_sketch_sql,
    insert_photo_sql, insert_sketch_sql,
)

finds_samples_bp = Blueprint("finds_samples", __name__)


# -------------------------
# Helpers
# -------------------------

def _humanize_code(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    return s.replace("_", " ").capitalize()


def _a6_pagesize():
    # A6: 105 × 148 mm
    return (105 * mm, 148 * mm)


def _qr_widget(value: str, size_mm: float = 28.0) -> Drawing:
    w = qr.QrCodeWidget(value)
    bounds = w.getBounds()  # (x1,y1,x2,y2)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    d = Drawing(size_mm * mm, size_mm * mm)
    d.add(w)
    # scale to requested drawing size
    sx = (size_mm * mm) / width
    sy = (size_mm * mm) / height
    w.scale(sx, sy)
    return d


def _require_int(form_value: str, field_label: str) -> int:
    try:
        return int(str(form_value).strip())
    except Exception:
        raise ValueError(f"Invalid {field_label}.")


def _optional_int(form_value: str):
    v = (str(form_value).strip() if form_value is not None else "")
    return int(v) if v else None


# -------------------------
# Page
# -------------------------

@finds_samples_bp.get("/finds-samples")
@require_selected_db
def finds_samples():
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(list_find_types_sql())
            find_types = [r[0] for r in cur.fetchall()]

            cur.execute(list_sample_types_sql())
            sample_types = [r[0] for r in cur.fetchall()]

            cur.execute(list_polygons_names_sql())
            polygons = [r[0] for r in cur.fetchall()]

        # last entries for quick attach dropdowns (optional)
        with conn.cursor() as cur:
            cur.execute(list_finds_sql(), (20,))
            last_finds = cur.fetchall()

            cur.execute(list_samples_sql(), (20,))
            last_samples = cur.fetchall()

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return render_template(
        "finds_samples.html",
        find_types=find_types,
        sample_types=sample_types,
        polygons=polygons,
        last_finds=last_finds,
        last_samples=last_samples,
        allowed_ext=", ".join(sorted(Config.ALLOWED_EXTENSIONS)),
    )


# -------------------------
# Glossary (add-only)
# -------------------------

@finds_samples_bp.post("/finds-samples/find-type/add")
@require_selected_db
def add_find_type():
    selected_db = session["selected_db"]
    type_code = (request.form.get("type_code") or "").strip().lower()

    if not type_code:
        flash("Type code is required.", "warning")
        return redirect(url_for("finds_samples.finds_samples"))

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(insert_find_type_sql(), (type_code,))
        conn.commit()
        flash(f'Find type "{type_code}" saved.', "success")
        logger.info(f"[{selected_db}] add find type: {type_code}")
    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] add find type failed: {e}")
        flash(f"Add find type failed: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("finds_samples.finds_samples"))


@finds_samples_bp.post("/finds-samples/sample-type/add")
@require_selected_db
def add_sample_type():
    selected_db = session["selected_db"]
    type_code = (request.form.get("type_code") or "").strip().lower()

    if not type_code:
        flash("Type code is required.", "warning")
        return redirect(url_for("finds_samples.finds_samples"))

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(insert_sample_type_sql(), (type_code,))
        conn.commit()
        flash(f'Sample type "{type_code}" saved.', "success")
        logger.info(f"[{selected_db}] add sample type: {type_code}")
    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] add sample type failed: {e}")
        flash(f"Add sample type failed: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("finds_samples.finds_samples"))


# -------------------------
# CRUD: Finds
# -------------------------

@finds_samples_bp.post("/finds-samples/find/add")
@require_selected_db
def add_find():
    selected_db = session["selected_db"]
    try:
        id_find = _require_int(request.form.get("id_find"), "Find ID")
        ref_find_type = (request.form.get("ref_find_type") or "").strip().lower()
        ref_sj = _require_int(request.form.get("ref_sj"), "SJ")
        count = _require_int(request.form.get("count"), "Count")
        box = _require_int(request.form.get("box"), "Box")

        ref_geopt = _optional_int(request.form.get("ref_geopt"))
        ref_polygon = (request.form.get("ref_polygon") or "").strip() or None
        description = (request.form.get("description") or "").strip() or ""

        if not ref_find_type:
            raise ValueError("Find type is required.")
        if count <= 0:
            raise ValueError("Count must be > 0.")
        if box <= 0:
            raise ValueError("Box must be > 0.")

    except Exception as e:
        flash(str(e), "danger")
        return redirect(url_for("finds_samples.finds_samples"))

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(find_exists_sql(), (id_find,))
            if cur.fetchone():
                flash(f"Find ID {id_find} already exists.", "warning")
                return redirect(url_for("finds_samples.finds_samples"))

            cur.execute(
                insert_find_sql(),
                (id_find, ref_find_type, description, count, ref_sj, ref_geopt, ref_polygon, box),
            )
        conn.commit()
        logger.info(f"[{selected_db}] find added id_find={id_find}")
        flash("Find saved.", "success")
    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] add find failed: {e}")
        flash(f"Add find failed: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("finds_samples.finds_samples"))


@finds_samples_bp.get("/finds-samples/find/list")
@require_selected_db
def list_finds():
    selected_db = session["selected_db"]
    limit = int(request.args.get("limit") or 30)

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(list_finds_sql(), (limit,))
            rows = cur.fetchall()
        data = []
        for r in rows:
            data.append(
                dict(
                    id_find=r[0],
                    ref_find_type=r[1],
                    ref_sj=r[2],
                    count=r[3],
                    box=r[4],
                    ref_polygon=r[5],
                    ref_geopt=r[6],
                    description=r[7],
                )
            )
        return jsonify({"ok": True, "rows": data})
    except Exception as e:
        logger.exception(f"[{selected_db}] list finds failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@finds_samples_bp.post("/finds-samples/find/delete/<int:id_find>")
@require_selected_db
def delete_find(id_find: int):
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(delete_find_sql(), (id_find,))
        conn.commit()
        logger.info(f"[{selected_db}] find deleted id_find={id_find}")
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] delete find failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@finds_samples_bp.post("/finds-samples/find/update/<int:id_find>")
@require_selected_db
def update_find(id_find: int):
    selected_db = session["selected_db"]
    payload = request.get_json(silent=True) or {}

    try:
        ref_find_type = (payload.get("ref_find_type") or "").strip().lower()
        ref_sj = int(payload.get("ref_sj"))
        count = int(payload.get("count"))
        box = int(payload.get("box"))
        ref_geopt = payload.get("ref_geopt")
        ref_geopt = int(ref_geopt) if str(ref_geopt).strip() != "" else None
        ref_polygon = (payload.get("ref_polygon") or "").strip() or None
        description = (payload.get("description") or "").strip() or ""

        if not ref_find_type:
            raise ValueError("Find type is required.")
        if count <= 0:
            raise ValueError("Count must be > 0.")
        if box <= 0:
            raise ValueError("Box must be > 0.")

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                update_find_sql(),
                (ref_find_type, description, count, ref_sj, ref_geopt, ref_polygon, box, id_find),
            )
        conn.commit()
        logger.info(f"[{selected_db}] find updated id_find={id_find}")
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] update find failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


# -------------------------
# CRUD: Samples
# -------------------------

@finds_samples_bp.post("/finds-samples/sample/add")
@require_selected_db
def add_sample():
    selected_db = session["selected_db"]
    try:
        id_sample = _require_int(request.form.get("id_sample"), "Sample ID")
        ref_sample_type = (request.form.get("ref_sample_type") or "").strip().lower()
        ref_sj = _require_int(request.form.get("ref_sj"), "SJ")

        ref_geopt = _optional_int(request.form.get("ref_geopt"))
        ref_polygon = (request.form.get("ref_polygon") or "").strip() or None
        description = (request.form.get("description") or "").strip() or ""

        if not ref_sample_type:
            raise ValueError("Sample type is required.")

    except Exception as e:
        flash(str(e), "danger")
        return redirect(url_for("finds_samples.finds_samples"))

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(sample_exists_sql(), (id_sample,))
            if cur.fetchone():
                flash(f"Sample ID {id_sample} already exists.", "warning")
                return redirect(url_for("finds_samples.finds_samples"))

            cur.execute(
                insert_sample_sql(),
                (id_sample, ref_sample_type, description, ref_sj, ref_geopt, ref_polygon),
            )
        conn.commit()
        logger.info(f"[{selected_db}] sample added id_sample={id_sample}")
        flash("Sample saved.", "success")
    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] add sample failed: {e}")
        flash(f"Add sample failed: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("finds_samples.finds_samples"))


@finds_samples_bp.get("/finds-samples/sample/list")
@require_selected_db
def list_samples():
    selected_db = session["selected_db"]
    limit = int(request.args.get("limit") or 30)

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(list_samples_sql(), (limit,))
            rows = cur.fetchall()
        data = []
        for r in rows:
            data.append(
                dict(
                    id_sample=r[0],
                    ref_sample_type=r[1],
                    ref_sj=r[2],
                    ref_polygon=r[3],
                    ref_geopt=r[4],
                    description=r[5],
                )
            )
        return jsonify({"ok": True, "rows": data})
    except Exception as e:
        logger.exception(f"[{selected_db}] list samples failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@finds_samples_bp.post("/finds-samples/sample/delete/<int:id_sample>")
@require_selected_db
def delete_sample(id_sample: int):
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(delete_sample_sql(), (id_sample,))
        conn.commit()
        logger.info(f"[{selected_db}] sample deleted id_sample={id_sample}")
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] delete sample failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@finds_samples_bp.post("/finds-samples/sample/update/<int:id_sample>")
@require_selected_db
def update_sample(id_sample: int):
    selected_db = session["selected_db"]
    payload = request.get_json(silent=True) or {}

    try:
        ref_sample_type = (payload.get("ref_sample_type") or "").strip().lower()
        ref_sj = int(payload.get("ref_sj"))
        ref_geopt = payload.get("ref_geopt")
        ref_geopt = int(ref_geopt) if str(ref_geopt).strip() != "" else None
        ref_polygon = (payload.get("ref_polygon") or "").strip() or None
        description = (payload.get("description") or "").strip() or ""

        if not ref_sample_type:
            raise ValueError("Sample type is required.")

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                update_sample_sql(),
                (ref_sample_type, description, ref_sj, ref_geopt, ref_polygon, id_sample),
            )
        conn.commit()
        logger.info(f"[{selected_db}] sample updated id_sample={id_sample}")
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] update sample failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


# -------------------------
# Detail endpoints (for QR URL)
# -------------------------

@finds_samples_bp.get("/finds-samples/find/<int:id_find>")
@require_selected_db
def find_detail(id_find: int):
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(get_find_sql(), (id_find,))
            r = cur.fetchone()
        if not r:
            return Response("Not found.", status=404)

        # minimal readable HTML (no extra template needed)
        html = f"""
        <html><head><meta charset="utf-8"><title>Find {id_find}</title></head>
        <body style="font-family: sans-serif">
          <h2>Find {id_find}</h2>
          <ul>
            <li>Type: <b>{r[1]}</b> ({_humanize_code(r[1])})</li>
            <li>SJ: <b>{r[2]}</b></li>
            <li>Count: <b>{r[3]}</b></li>
            <li>Box: <b>{r[4]}</b></li>
            <li>Polygon: {r[5] or "—"}</li>
            <li>Geopt: {r[6] or "—"}</li>
            <li>Description: {r[7] or "—"}</li>
          </ul>
          <p><a href="{url_for('finds_samples.finds_samples')}">Back</a></p>
        </body></html>
        """
        return Response(html, mimetype="text/html")
    finally:
        conn.close()


@finds_samples_bp.get("/finds-samples/sample/<int:id_sample>")
@require_selected_db
def sample_detail(id_sample: int):
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(get_sample_sql(), (id_sample,))
            r = cur.fetchone()
        if not r:
            return Response("Not found.", status=404)

        html = f"""
        <html><head><meta charset="utf-8"><title>Sample {id_sample}</title></head>
        <body style="font-family: sans-serif">
          <h2>Sample {id_sample}</h2>
          <ul>
            <li>Type: <b>{r[1]}</b> ({_humanize_code(r[1])})</li>
            <li>SJ: <b>{r[2]}</b></li>
            <li>Polygon: {r[3] or "—"}</li>
            <li>Geopt: {r[4] or "—"}</li>
            <li>Description: {r[5] or "—"}</li>
          </ul>
          <p><a href="{url_for('finds_samples.finds_samples')}">Back</a></p>
        </body></html>
        """
        return Response(html, mimetype="text/html")
    finally:
        conn.close()


# -------------------------
# Label printing (A6 PDF + QR URL)
# -------------------------

@finds_samples_bp.get("/finds-samples/find/label/<int:id_find>")
@require_selected_db
def print_find_label(id_find: int):
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(get_find_sql(), (id_find,))
            r = cur.fetchone()
        if not r:
            return Response("Not found.", status=404)
    finally:
        conn.close()

    url = request.url_root.rstrip("/") + url_for("finds_samples.find_detail", id_find=id_find)

    buf = io.BytesIO()
    w, h = _a6_pagesize()
    c = canvas.Canvas(buf, pagesize=(w, h))

    # QR
    d = _qr_widget(url, size_mm=30)
    renderPDF.draw(d, c, 8 * mm, h - 38 * mm)

    # Text
    c.setFont("Helvetica-Bold", 14)
    c.drawString(45 * mm, h - 15 * mm, f"FIND {r[0]}")

    c.setFont("Helvetica", 10)
    y = h - 25 * mm
    lines = [
        f"Type: {_humanize_code(r[1])} ({r[1]})",
        f"SJ: {r[2]}",
        f"Count: {r[3]}",
        f"Box: {r[4]}",
        f"Polygon: {r[5] or '—'}",
        f"Geopt: {r[6] or '—'}",
    ]
    for ln in lines:
        c.drawString(45 * mm, y, ln)
        y -= 5 * mm

    c.setFont("Helvetica", 8)
    c.drawString(8 * mm, 8 * mm, url)

    c.showPage()
    c.save()

    pdf = buf.getvalue()
    buf.close()

    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="find_{id_find}_label_a6.pdf"'}
    )


@finds_samples_bp.get("/finds-samples/sample/label/<int:id_sample>")
@require_selected_db
def print_sample_label(id_sample: int):
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(get_sample_sql(), (id_sample,))
            r = cur.fetchone()
        if not r:
            return Response("Not found.", status=404)
    finally:
        conn.close()

    url = request.url_root.rstrip("/") + url_for("finds_samples.sample_detail", id_sample=id_sample)

    buf = io.BytesIO()
    w, h = _a6_pagesize()
    c = canvas.Canvas(buf, pagesize=(w, h))

    d = _qr_widget(url, size_mm=30)
    renderPDF.draw(d, c, 8 * mm, h - 38 * mm)

    c.setFont("Helvetica-Bold", 14)
    c.drawString(45 * mm, h - 15 * mm, f"SAMPLE {r[0]}")

    c.setFont("Helvetica", 10)
    y = h - 25 * mm
    lines = [
        f"Type: {_humanize_code(r[1])} ({r[1]})",
        f"SJ: {r[2]}",
        f"Polygon: {r[3] or '—'}",
        f"Geopt: {r[4] or '—'}",
    ]
    for ln in lines:
        c.drawString(45 * mm, y, ln)
        y -= 5 * mm

    c.setFont("Helvetica", 8)
    c.drawString(8 * mm, 8 * mm, url)

    c.showPage()
    c.save()

    pdf = buf.getvalue()
    buf.close()

    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="sample_{id_sample}_label_a6.pdf"'}
    )


# -------------------------
# Media uploads (finds/samples) – copied from polygons style
# -------------------------

@finds_samples_bp.post("/finds-samples/find/upload/<media_type>")
@require_selected_db
def upload_find_media(media_type: str):
    selected_db = session["selected_db"]

    if media_type not in MEDIA_TABLES:
        flash("Invalid media type.", "danger")
        return redirect(url_for("finds_samples.finds_samples"))
    if media_type not in LINK_TABLES_FINDS:
        flash("This media type is not supported for finds.", "danger")
        return redirect(url_for("finds_samples.finds_samples"))

    id_find_raw = (request.form.get("id_find") or "").strip()
    if not id_find_raw:
        flash("You must select a find first.", "warning")
        return redirect(url_for("finds_samples.finds_samples"))

    try:
        id_find = int(id_find_raw)
    except Exception:
        flash("Invalid find ID.", "danger")
        return redirect(url_for("finds_samples.finds_samples"))

    files = request.files.getlist("files")
    if not files:
        flash("No files provided.", "warning")
        return redirect(url_for("finds_samples.finds_samples"))

    # verify find exists
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(find_exists_sql(), (id_find,))
            if not cur.fetchone():
                flash(f'Find "{id_find}" not found.', "danger")
                return redirect(url_for("finds_samples.finds_samples"))
    finally:
        conn.close()

    notes = (request.form.get("notes") or "").strip() or None

    if media_type == "photos":
        photo_typ = (request.form.get("photo_typ") or "").strip()
        datum = (request.form.get("datum") or "").strip() or None
        author = (request.form.get("author") or "").strip() or None
    elif media_type == "sketches":
        sketch_typ = (request.form.get("sketch_typ") or "").strip()
        author = (request.form.get("author") or "").strip() or None
        datum = (request.form.get("datum") or "").strip() or None
    else:
        flash("Unsupported media type for finds.", "danger")
        return redirect(url_for("finds_samples.finds_samples"))

    ok, failed = 0, []

    for f in files:
        tmp_path = None
        final_path = None
        thumb_path = None

        try:
            tmp_path, _ = storage.save_to_uploads(Config.UPLOAD_FOLDER, f)

            pk_name = storage.make_pk(selected_db, f.filename)
            storage.validate_pk(pk_name)
            ext = pk_name.rsplit(".", 1)[-1].lower()
            validate_extension(ext, Config.ALLOWED_EXTENSIONS)

            media_dir = Config.MEDIA_DIRS[media_type]
            final_path, thumb_path = storage.final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)
            if os.path.exists(final_path):
                raise ValueError(f"File already exists: {pk_name}")

            storage.move_into_place(tmp_path, final_path)
            tmp_path = None

            mime = detect_mime(final_path)
            validate_mime(mime, Config.ALLOWED_MIME)
            checksum = sha256_file(final_path)

            try:
                make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
            except Exception:
                pass

            shoot_dt = gps_lat = gps_lon = gps_alt = None
            exif_json = {}
            if media_type == "photos" and mime in ("image/jpeg", "image/tiff"):
                sdt, la, lo, al, exif = extract_exif(final_path)
                shoot_dt, gps_lat, gps_lon, gps_alt, exif_json = sdt, la, lo, al, exif

            conn2 = get_terrain_connection(selected_db)
            cur2 = conn2.cursor()
            try:
                if media_type == "photos":
                    cur2.execute(
                        insert_photo_sql(),
                        (
                            pk_name,
                            photo_typ or "",
                            datum,
                            author,
                            notes,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                            shoot_dt, gps_lat, gps_lon, gps_alt,
                            Json(exif_json),
                        )
                    )
                    # link (idempotent)
                    cur2.execute(link_find_photo_sql(), (id_find, pk_name, id_find, pk_name))

                elif media_type == "sketches":
                    cur2.execute(
                        insert_sketch_sql(),
                        (
                            pk_name,
                            sketch_typ or "",
                            author,
                            datum,
                            notes,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                        )
                    )
                    cur2.execute(link_find_sketch_sql(), (id_find, pk_name, id_find, pk_name))

                conn2.commit()
                ok += 1

            except Exception:
                conn2.rollback()
                try:
                    storage.delete_media_files(final_path, thumb_path)
                except Exception:
                    pass
                raise

            finally:
                try:
                    cur2.close()
                except Exception:
                    pass
                try:
                    conn2.close()
                except Exception:
                    pass

        except Exception as e:
            failed.append(f"{f.filename}: {e}")
            logger.warning(f"[{selected_db}] find media upload failed ({media_type}) {f.filename}: {e}")

        finally:
            if tmp_path:
                try:
                    storage.cleanup_upload(tmp_path)
                except Exception:
                    pass

    if failed:
        flash(
            f"Uploaded {ok} file(s), {len(failed)} failed: " + "; ".join(failed),
            "warning" if ok else "danger"
        )
    else:
        flash(f"Uploaded {ok} file(s).", "success")

    logger.info(f"[{selected_db}] find-media upload: id_find={id_find} type={media_type} ok={ok} failed={len(failed)}")
    return redirect(url_for("finds_samples.finds_samples"))


@finds_samples_bp.post("/finds-samples/sample/upload/<media_type>")
@require_selected_db
def upload_sample_media(media_type: str):
    selected_db = session["selected_db"]

    if media_type not in MEDIA_TABLES:
        flash("Invalid media type.", "danger")
        return redirect(url_for("finds_samples.finds_samples"))
    if media_type not in LINK_TABLES_SAMPLES:
        flash("This media type is not supported for samples.", "danger")
        return redirect(url_for("finds_samples.finds_samples"))

    id_sample_raw = (request.form.get("id_sample") or "").strip()
    if not id_sample_raw:
        flash("You must select a sample first.", "warning")
        return redirect(url_for("finds_samples.finds_samples"))

    try:
        id_sample = int(id_sample_raw)
    except Exception:
        flash("Invalid sample ID.", "danger")
        return redirect(url_for("finds_samples.finds_samples"))

    files = request.files.getlist("files")
    if not files:
        flash("No files provided.", "warning")
        return redirect(url_for("finds_samples.finds_samples"))

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(sample_exists_sql(), (id_sample,))
            if not cur.fetchone():
                flash(f'Sample "{id_sample}" not found.', "danger")
                return redirect(url_for("finds_samples.finds_samples"))
    finally:
        conn.close()

    notes = (request.form.get("notes") or "").strip() or None

    if media_type == "photos":
        photo_typ = (request.form.get("photo_typ") or "").strip()
        datum = (request.form.get("datum") or "").strip() or None
        author = (request.form.get("author") or "").strip() or None
    elif media_type == "sketches":
        sketch_typ = (request.form.get("sketch_typ") or "").strip()
        author = (request.form.get("author") or "").strip() or None
        datum = (request.form.get("datum") or "").strip() or None
    else:
        flash("Unsupported media type for samples.", "danger")
        return redirect(url_for("finds_samples.finds_samples"))

    ok, failed = 0, []

    for f in files:
        tmp_path = None
        final_path = None
        thumb_path = None

        try:
            tmp_path, _ = storage.save_to_uploads(Config.UPLOAD_FOLDER, f)

            pk_name = storage.make_pk(selected_db, f.filename)
            storage.validate_pk(pk_name)
            ext = pk_name.rsplit(".", 1)[-1].lower()
            validate_extension(ext, Config.ALLOWED_EXTENSIONS)

            media_dir = Config.MEDIA_DIRS[media_type]
            final_path, thumb_path = storage.final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)
            if os.path.exists(final_path):
                raise ValueError(f"File already exists: {pk_name}")

            storage.move_into_place(tmp_path, final_path)
            tmp_path = None

            mime = detect_mime(final_path)
            validate_mime(mime, Config.ALLOWED_MIME)
            checksum = sha256_file(final_path)

            try:
                make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
            except Exception:
                pass

            shoot_dt = gps_lat = gps_lon = gps_alt = None
            exif_json = {}
            if media_type == "photos" and mime in ("image/jpeg", "image/tiff"):
                sdt, la, lo, al, exif = extract_exif(final_path)
                shoot_dt, gps_lat, gps_lon, gps_alt, exif_json = sdt, la, lo, al, exif

            conn2 = get_terrain_connection(selected_db)
            cur2 = conn2.cursor()
            try:
                if media_type == "photos":
                    cur2.execute(
                        insert_photo_sql(),
                        (
                            pk_name,
                            photo_typ or "",
                            datum,
                            author,
                            notes,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                            shoot_dt, gps_lat, gps_lon, gps_alt,
                            Json(exif_json),
                        )
                    )
                    cur2.execute(link_sample_photo_sql(), (id_sample, pk_name, id_sample, pk_name))

                elif media_type == "sketches":
                    cur2.execute(
                        insert_sketch_sql(),
                        (
                            pk_name,
                            sketch_typ or "",
                            author,
                            datum,
                            notes,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                        )
                    )
                    cur2.execute(link_sample_sketch_sql(), (id_sample, pk_name, id_sample, pk_name))

                conn2.commit()
                ok += 1

            except Exception:
                conn2.rollback()
                try:
                    storage.delete_media_files(final_path, thumb_path)
                except Exception:
                    pass
                raise

            finally:
                try:
                    cur2.close()
                except Exception:
                    pass
                try:
                    conn2.close()
                except Exception:
                    pass

        except Exception as e:
            failed.append(f"{f.filename}: {e}")
            logger.warning(f"[{selected_db}] sample media upload failed ({media_type}) {f.filename}: {e}")

        finally:
            if tmp_path:
                try:
                    storage.cleanup_upload(tmp_path)
                except Exception:
                    pass

    if failed:
        flash(
            f"Uploaded {ok} file(s), {len(failed)} failed: " + "; ".join(failed),
            "warning" if ok else "danger"
        )
    else:
        flash(f"Uploaded {ok} file(s).", "success")

    logger.info(f"[{selected_db}] sample-media upload: id_sample={id_sample} type={media_type} ok={ok} failed={len(failed)}")
    return redirect(url_for("finds_samples.finds_samples"))
