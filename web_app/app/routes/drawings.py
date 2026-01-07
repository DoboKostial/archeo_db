from __future__ import annotations

import json
import os
import mimetypes
from typing import Any, Dict, List, Tuple

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db
from app.utils import (
    cleanup_upload,
    delete_media_files,
    detect_mime,
    final_paths,
    make_pk,
    make_thumbnail,
    move_into_place,
    save_to_uploads,
    sha256_file,
    validate_extension,
    validate_mime,
    validate_pk,
)

# SQL imports (from app/queries)
from app.queries import (
    bulk_delete_drawings_sql,
    bulk_update_drawings_meta_sql,
    delete_drawing_sql,
    drawing_checksum_exists_sql,
    drawing_exists_sql,
    drawings_stats_sql,
    insert_drawing_sql,
    link_drawing_section_sql,
    link_drawing_sj_sql,
    select_drawing_detail_sql,
    select_drawing_links_sql,
    unlink_all_drawing_section_sql,
    unlink_all_drawing_sj_sql,
    update_drawing_file_sql,
    update_drawing_meta_sql,
    select_drawings_page_sql
)

drawings_bp = Blueprint("drawings", __name__)


# ---------------------------
# helpers
# ---------------------------

def _as_int(x: str | None) -> int | None:
    try:
        if x is None:
            return None
        x = str(x).strip()
        if not x:
            return None
        return int(x)
    except Exception:
        return None


def _as_date_str(x: str | None) -> str | None:
    # expects YYYY-MM-DD from <input type="date">
    if not x:
        return None
    x = str(x).strip()
    return x or None


def _human_bytes(n: int | None) -> str:
    if n is None:
        return "0 B"
    x = float(n)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if x < 1024.0:
            return f"{x:.1f} {u}"
        x /= 1024.0
    return f"{x:.1f} PB"


def _parse_int_list(values: List[str]) -> List[int]:
    out: List[int] = []
    for v in values or []:
        i = _as_int(v)
        if i is not None:
            out.append(i)
    # dedupe, stable order
    seen = set()
    res = []
    for i in out:
        if i not in seen:
            seen.add(i)
            res.append(i)
    return res


def _final_paths(selected_db: str, pk_name: str) -> Tuple[str, str]:
    media_dir = Config.MEDIA_DIRS["drawings"]
    return final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)


def _jsonb_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            x = json.loads(v)
            return x if isinstance(x, list) else []
        except Exception:
            return []
    return []

# ---------------------------
# serving files (fix: no direct FS paths in HTML)
# ---------------------------

@drawings_bp.get("/drawings/file/<path:id_drawing>")
@require_selected_db
def serve_drawing(id_drawing: str):
    selected_db = session["selected_db"]
    id_drawing = (id_drawing or "").strip()
    if not id_drawing:
        abort(404)

    final_path, _thumb_path = _final_paths(selected_db, id_drawing)
    if not os.path.exists(final_path):
        abort(404)

    mt = mimetypes.guess_type(final_path)[0] or "application/octet-stream"
    return send_file(final_path, mimetype=mt, as_attachment=False)


@drawings_bp.get("/drawings/thumb/<path:id_drawing>")
@require_selected_db
def serve_drawing_thumb(id_drawing: str):
    selected_db = session["selected_db"]
    id_drawing = (id_drawing or "").strip()
    if not id_drawing:
        abort(404)

    _final_path, thumb_path = _final_paths(selected_db, id_drawing)
    if not os.path.exists(thumb_path):
        abort(404)

    mt = mimetypes.guess_type(thumb_path)[0] or "application/octet-stream"
    return send_file(thumb_path, mimetype=mt, as_attachment=False)


# ---------------------------
# API search (SearchSelect)
# ---------------------------

@drawings_bp.get("/drawings/api/search/authors")
@require_selected_db
def api_search_authors():
    q = (request.args.get("q") or "").strip()
    limit = _as_int(request.args.get("limit")) or 20
    page = _as_int(request.args.get("page")) or 1
    offset = (page - 1) * limit

    if not q:
        return jsonify({"results": []})

    selected_db = session["selected_db"]
    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT mail AS id, mail AS text
                FROM gloss_personalia
                WHERE mail ILIKE %s
                ORDER BY mail
                LIMIT %s OFFSET %s;
                """,
                (f"%{q}%", limit, offset),
            )
            rows = cur.fetchall()
    return jsonify({"results": [{"id": r[0], "text": r[1]} for r in rows]})


@drawings_bp.get("/drawings/api/search/sj")
@require_selected_db
def api_search_sj():
    q = (request.args.get("q") or "").strip()
    limit = _as_int(request.args.get("limit")) or 20
    page = _as_int(request.args.get("page")) or 1
    offset = (page - 1) * limit

    if not q:
        return jsonify({"results": []})

    selected_db = session["selected_db"]
    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id_sj::text AS id, ('SJ ' || id_sj::text) AS text
                FROM tab_sj
                WHERE id_sj::text ILIKE %s
                ORDER BY id_sj
                LIMIT %s OFFSET %s;
                """,
                (f"%{q}%", limit, offset),
            )
            rows = cur.fetchall()
    return jsonify({"results": [{"id": r[0], "text": r[1]} for r in rows]})


@drawings_bp.get("/drawings/api/search/sections")
@require_selected_db
def api_search_sections():
    q = (request.args.get("q") or "").strip()
    limit = _as_int(request.args.get("limit")) or 20
    page = _as_int(request.args.get("page")) or 1
    offset = (page - 1) * limit

    if not q:
        return jsonify({"results": []})

    selected_db = session["selected_db"]
    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id_section::text AS id, ('Section ' || id_section::text) AS text
                FROM tab_section
                WHERE id_section::text ILIKE %s
                ORDER BY id_section
                LIMIT %s OFFSET %s;
                """,
                (f"%{q}%", limit, offset),
            )
            rows = cur.fetchall()
    return jsonify({"results": [{"id": r[0], "text": r[1]} for r in rows]})


# ---------------------------
# main page
# ---------------------------

@drawings_bp.get("/drawings")
@require_selected_db
def drawings():
    selected_db = session["selected_db"]

    # filters (GET)
    f_author = (request.args.get("author") or "").strip() or None
    f_df = _as_date_str(request.args.get("date_from"))  # "YYYY-MM-DD" or None
    f_dt = _as_date_str(request.args.get("date_to"))    # "YYYY-MM-DD" or None
    orphan_only = (request.args.get("orphan_only") == "1")

    f_sj_ids = _parse_int_list(request.args.getlist("ref_sj"))
    f_section_ids = _parse_int_list(request.args.getlist("ref_section"))

    page = _as_int(request.args.get("page")) or 1
    per_page = _as_int(request.args.get("per_page")) or 24
    offset = (page - 1) * per_page

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            # stats
            cur.execute(drawings_stats_sql())
            total_cnt, total_bytes, orphan_cnt = cur.fetchone()

            # page rows
            cur.execute(
                select_drawings_page_sql(
                    orphan_only=orphan_only,
                    has_author=bool(f_author),
                    has_df=bool(f_df),
                    has_dt=bool(f_dt),
                    has_sj=bool(f_sj_ids),
                    has_section=bool(f_section_ids),
                ),
                {
                    "author": f_author,
                    "date_from": f_df,
                    "date_to": f_dt,
                    "sj_list": f_sj_ids,
                    "section_list": f_section_ids,
                    "limit": per_page,
                    "offset": offset,
                },
            )
            rows = cur.fetchall()

    drawings_out = []
    for r in rows:
        # r = (id_drawing, author, datum, notes, mime_type, file_size, sj_ids_jsonb, section_ids_jsonb)
        sj_ids = _jsonb_list(r[6])
        section_ids = _jsonb_list(r[7])

        drawings_out.append({
            "id_drawing": r[0],
            "author": r[1],
            "datum": r[2],
            "notes": r[3],
            "mime_type": r[4],
            "file_size": r[5],
            "links": {
                "sj": [int(x) for x in sj_ids if str(x).isdigit()],
                "section": [int(x) for x in section_ids if str(x).isdigit()],
            },
            "link_counts": {
                "sj": len(sj_ids),
                "section": len(section_ids),
            },
        })

    stats = {
        "total_cnt": total_cnt,
        "total_bytes_h": _human_bytes(total_bytes),
        "orphan_cnt": orphan_cnt,
    }

    filters = {
        "author": f_author,
        "date_from": f_df,
        "date_to": f_dt,
        "orphan_only": orphan_only,
        "ref_sj": f_sj_ids,
        "ref_section": f_section_ids,
    }

    return render_template(
        "drawings.html",
        selected_db=selected_db,
        drawings=drawings_out,
        page=page,
        per_page=per_page,
        stats=stats,
        filters=filters,
    )


# ---------------------------
# upload (multi files, shared props) - TRANSACTIONAL including thumbnails
# ---------------------------

@drawings_bp.post("/drawings/upload")
@require_selected_db
def upload_drawings():
    selected_db = session["selected_db"]

    author = (request.form.get("author") or "").strip() or None
    datum = _as_date_str(request.form.get("datum"))
    notes = (request.form.get("notes") or "").strip() or None

    if not author:
        flash("Upload failed: Missing author.", "danger")
        return redirect(url_for("drawings.drawings"))
    if not datum:
        flash("Upload failed: Missing date.", "danger")
        return redirect(url_for("drawings.drawings"))

    sj_ids = request.form.getlist("ref_sj")
    section_ids = request.form.getlist("ref_section")

    files = request.files.getlist("files")
    files = [f for f in files if f and f.filename]
    if not files:
        flash("Upload failed: No files provided.", "danger")
        return redirect(url_for("drawings.drawings"))

    staged_paths: List[str] = []
    final_pairs: List[Tuple[str, str]] = []
    items: List[Dict[str, Any]] = []
    batch_checksums = set()

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # validate author exists
            cur.execute("SELECT 1 FROM gloss_personalia WHERE mail=%s LIMIT 1;", (author,))
            if not cur.fetchone():
                raise ValueError(f"Author not found: {author}")

            # validate links exist (fail-fast)
            for sj in sj_ids:
                sj_i = _as_int(sj)
                if sj_i is None:
                    continue
                cur.execute("SELECT 1 FROM tab_sj WHERE id_sj=%s LIMIT 1;", (sj_i,))
                if not cur.fetchone():
                    raise ValueError(f"SU not found: {sj_i}")

            for s in section_ids:
                s_i = _as_int(s)
                if s_i is None:
                    continue
                cur.execute("SELECT 1 FROM tab_section WHERE id_section=%s LIMIT 1;", (s_i,))
                if not cur.fetchone():
                    raise ValueError(f"Section not found: {s_i}")

            # stage + validate each file
            for f in files:
                tmp_path, _ = save_to_uploads(Config.UPLOAD_FOLDER, f)
                staged_paths.append(tmp_path)

                pk_name = make_pk(selected_db, f.filename)
                validate_pk(pk_name)
                ext = pk_name.rsplit(".", 1)[-1].lower()
                validate_extension(ext, Config.ALLOWED_EXTENSIONS)

                final_path, thumb_path = _final_paths(selected_db, pk_name)

                if os.path.exists(final_path):
                    raise ValueError(f"File already exists on FS: {pk_name}")

                cur.execute(drawing_exists_sql(), (pk_name,))
                if cur.fetchone():
                    raise ValueError(f"Drawing already exists in DB: {pk_name}")

                mime = detect_mime(tmp_path)
                validate_mime(mime, Config.ALLOWED_MIME)
                checksum = sha256_file(tmp_path)

                cur.execute(drawing_checksum_exists_sql(), (checksum,))
                if cur.fetchone():
                    raise ValueError(f"Duplicate content (checksum already exists): {pk_name}")

                if checksum in batch_checksums:
                    raise ValueError(f"Duplicate content within this upload batch: {pk_name}")
                batch_checksums.add(checksum)

                items.append({
                    "pk_name": pk_name,
                    "tmp_path": tmp_path,
                    "final_path": final_path,
                    "thumb_path": thumb_path,
                    "mime": mime,
                    "checksum": checksum,
                })

            # move + thumb + DB insert + links in one transaction
            for it in items:
                move_into_place(it["tmp_path"], it["final_path"])
                it["tmp_path"] = None
                final_pairs.append((it["final_path"], it["thumb_path"]))

                # thumbnail is part of transaction
                make_thumbnail(it["final_path"], it["thumb_path"], Config.THUMB_MAX_SIDE)

                cur.execute(
                    insert_drawing_sql(),
                    (
                        it["pk_name"],
                        author,
                        datum,
                        notes,
                        it["mime"],
                        os.path.getsize(it["final_path"]),
                        it["checksum"],
                    ),
                )

                for sj in sj_ids:
                    sj_i = _as_int(sj)
                    if sj_i is not None:
                        cur.execute(link_drawing_sj_sql(), (it["pk_name"], sj_i))

                for s in section_ids:
                    s_i = _as_int(s)
                    if s_i is not None:
                        cur.execute(link_drawing_section_sql(), (s_i, it["pk_name"]))

            conn.commit()
            flash(f"Uploaded {len(items)} drawing(s).", "success")
            logger.info(f"[{selected_db}] drawings upload ok: count={len(items)}")

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass

        for fp, tp in final_pairs:
            try:
                delete_media_files(fp, tp)
            except Exception:
                pass

        for sp in staged_paths:
            try:
                cleanup_upload(sp)
            except Exception:
                pass

        logger.warning(f"[{selected_db}] drawings upload failed: {e}")
        flash(f"Upload failed: {e}", "danger")
        return redirect(url_for("drawings.drawings"))

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("drawings.drawings"))


# ---------------------------
# detail API for edit modal
# ---------------------------

@drawings_bp.get("/drawings/api/detail/<path:id_drawing>")
@require_selected_db
def api_drawing_detail(id_drawing: str):
    selected_db = session["selected_db"]
    id_drawing = (id_drawing or "").strip()

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(select_drawing_detail_sql(), (id_drawing,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "not found"}), 404

            cur.execute(select_drawing_links_sql(), (id_drawing, id_drawing))
            sj_ids, section_ids = cur.fetchone()

    return jsonify({
        "id_drawing": row[0],
        "author": row[1],
        "datum": row[2],
        "notes": row[3],
        "mime_type": row[4],
        "file_size": row[5],
        "links": {
            "sj_ids": sj_ids or [],
            "section_ids": section_ids or [],
        }
    })


# ---------------------------
# edit (replace file optional) + replace links
# ---------------------------

@drawings_bp.post("/drawings/edit/<path:id_drawing>")
@require_selected_db
def edit_drawing(id_drawing: str):
    selected_db = session["selected_db"]
    id_drawing = (id_drawing or "").strip()

    author = (request.form.get("author") or "").strip() or None
    datum = _as_date_str(request.form.get("datum"))
    notes = (request.form.get("notes") or "").strip() or None

    if not author or not datum:
        flash("Edit failed: author and date are required.", "danger")
        return redirect(url_for("drawings.drawings"))

    sj_ids = request.form.getlist("ref_sj")
    section_ids = request.form.getlist("ref_section")

    # optional file replacement
    f = request.files.get("file")
    do_replace = bool(f and f.filename)

    staged_paths: List[str] = []
    final_pairs: List[Tuple[str, str]] = []

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # validate author exists
            cur.execute("SELECT 1 FROM gloss_personalia WHERE mail=%s LIMIT 1;", (author,))
            if not cur.fetchone():
                raise ValueError(f"Author not found: {author}")

            # validate links exist
            for sj in sj_ids:
                sj_i = _as_int(sj)
                if sj_i is None:
                    continue
                cur.execute("SELECT 1 FROM tab_sj WHERE id_sj=%s LIMIT 1;", (sj_i,))
                if not cur.fetchone():
                    raise ValueError(f"SU not found: {sj_i}")

            for s in section_ids:
                s_i = _as_int(s)
                if s_i is None:
                    continue
                cur.execute("SELECT 1 FROM tab_section WHERE id_section=%s LIMIT 1;", (s_i,))
                if not cur.fetchone():
                    raise ValueError(f"Section not found: {s_i}")

            final_path, thumb_path = _final_paths(selected_db, id_drawing)

            # replace file if requested
            if do_replace:
                tmp_path, _ = save_to_uploads(Config.UPLOAD_FOLDER, f)
                staged_paths.append(tmp_path)

                mime = detect_mime(tmp_path)
                validate_mime(mime, Config.ALLOWED_MIME)
                checksum = sha256_file(tmp_path)

                cur.execute(drawing_checksum_exists_sql(), (checksum,))
                hit = cur.fetchone()
                if hit:
                    # allow if it's the same drawing (optional strictness); keep strict like Photos:
                    raise ValueError("Duplicate content (checksum already exists).")

                # move into place + new thumb
                move_into_place(tmp_path, final_path)
                staged_paths.remove(tmp_path)
                final_pairs.append((final_path, thumb_path))

                make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)

                # update file meta in DB
                cur.execute(
                    update_drawing_file_sql(),
                    (mime, os.path.getsize(final_path), checksum, id_drawing),
                )

            # update meta
            cur.execute(update_drawing_meta_sql(), (author, datum, notes, id_drawing))

            # replace links
            cur.execute(unlink_all_drawing_sj_sql(), (id_drawing,))
            cur.execute(unlink_all_drawing_section_sql(), (id_drawing,))

            for sj in sj_ids:
                sj_i = _as_int(sj)
                if sj_i is not None:
                    cur.execute(link_drawing_sj_sql(), (id_drawing, sj_i))

            for s in section_ids:
                s_i = _as_int(s)
                if s_i is not None:
                    cur.execute(link_drawing_section_sql(), (s_i, id_drawing))

            conn.commit()
            flash("Drawing updated.", "success")

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass

        # staged cleanup
        for sp in staged_paths:
            try:
                cleanup_upload(sp)
            except Exception:
                pass

        logger.warning(f"[{selected_db}] drawing edit failed {id_drawing}: {e}")
        flash(f"Edit failed: {e}", "danger")
        return redirect(url_for("drawings.drawings"))

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("drawings.drawings"))


# ---------------------------
# delete (DB + FS)
# ---------------------------

@drawings_bp.post("/drawings/delete/<path:id_drawing>")
@require_selected_db
def delete_drawing(id_drawing: str):
    selected_db = session["selected_db"]
    id_drawing = (id_drawing or "").strip()

    final_path, thumb_path = _final_paths(selected_db, id_drawing)

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(delete_drawing_sql(), (id_drawing,))
        conn.commit()

    try:
        delete_media_files(final_path, thumb_path)
    except Exception:
        pass

    flash("Drawing deleted.", "success")
    return redirect(url_for("drawings.drawings"))


# ---------------------------
# bulk operations
# ---------------------------

@drawings_bp.post("/drawings/bulk")
@require_selected_db
def bulk_drawings():
    selected_db = session["selected_db"]

    ids = request.form.getlist("drawing_ids")
    ids = [i for i in ids if (i or "").strip()]
    if not ids:
        flash("No drawings selected.", "warning")
        return redirect(url_for("drawings.drawings"))

    action = (request.form.get("action") or "").strip()

    if action == "delete":
        with get_terrain_connection(selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(bulk_delete_drawings_sql(), (ids,))
            conn.commit()

        for did in ids:
            fp, tp = _final_paths(selected_db, did)
            try:
                delete_media_files(fp, tp)
            except Exception:
                pass

        flash(f"Deleted {len(ids)} drawing(s).", "success")
        return redirect(url_for("drawings.drawings"))

    if action == "update_meta":
        author = (request.form.get("bulk_author") or "").strip() or None
        datum = _as_date_str(request.form.get("bulk_datum"))
        notes = (request.form.get("bulk_notes") or "").strip()

        set_author = bool(author)
        set_date = bool(datum)
        set_notes = (notes != "")

        if not (set_author or set_date or set_notes):
            flash("Nothing to update.", "warning")
            return redirect(url_for("drawings.drawings"))

        with get_terrain_connection(selected_db) as conn:
            with conn.cursor() as cur:
                if set_author:
                    cur.execute("SELECT 1 FROM gloss_personalia WHERE mail=%s LIMIT 1;", (author,))
                    if not cur.fetchone():
                        flash(f"Bulk failed: author not found: {author}", "danger")
                        return redirect(url_for("drawings.drawings"))

                cur.execute(
                    bulk_update_drawings_meta_sql(set_author, set_date, set_notes),
                    {
                        "ids": ids,
                        "author": author,
                        "datum": datum,
                        "notes": notes if set_notes else None,
                    }
                )
            conn.commit()

        flash(f"Updated {len(ids)} drawing(s).", "success")
        return redirect(url_for("drawings.drawings"))

    flash("Unknown bulk action.", "danger")
    return redirect(url_for("drawings.drawings"))
