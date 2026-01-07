# app/routes/sketches.py
from __future__ import annotations

import json
import os
from typing import Any

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db

from app.utils import (
    save_to_uploads, cleanup_upload, move_into_place, delete_media_files,
    make_pk, validate_pk, final_paths,
    detect_mime, make_thumbnail,
    sha256_file, validate_extension, validate_mime
)

from app.queries import (
    # base CRUD
    insert_sketch_sql,
    update_sketch_sql,
    delete_sketch_sql,
    sketch_exists_sql,
    sketch_checksum_exists_sql,

    # links
    link_sketch_sj_sql,
    unlink_sketch_sj_sql,
    link_sketch_polygon_sql,
    unlink_sketch_polygon_sql,
    link_sketch_section_sql,
    unlink_sketch_section_sql,
    link_sketch_find_sql,
    unlink_sketch_find_sql,
    link_sketch_sample_sql,
    unlink_sketch_sample_sql,

    # list/detail/stats
    select_sketches_page_sql,
    select_sketch_detail_sql,
    select_sketch_links_sql,
    sketches_stats_sql,
    sketches_stats_by_type_sql,

    # search endpoints
    search_sj_sql,
    search_polygons_sql,
    search_sections_sql,
    search_finds_sql,
    search_samples_sql,
    search_authors_sql,
)

sketches_bp = Blueprint("sketches", __name__)

# app-level choices, not Db enums
SKETCH_TYP_CHOICES = ["sketch", "photosketch", "general", "other"]


def _as_int(val: str | None) -> int | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None


def _as_date_str(val: str | None) -> str | None:
    s = (val or "").strip()
    return s or None  # YYYY-MM-DD

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

def _parse_text_list(values: List[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        v = (v or "").strip()
        if v:
            out.append(v)
    return out

# ---------------------------------------
# PAGE
# ---------------------------------------
@sketches_bp.get("/sketches")
@require_selected_db
def sketches():
    selected_db = session["selected_db"]

    # filters (GET)
    f_typ = request.args.getlist("sketch_typ")
    f_author = (request.args.get("author") or "").strip() or None
    f_date_from = _as_date_str(request.args.get("date_from"))
    f_date_to = _as_date_str(request.args.get("date_to"))
    orphan_only = (request.args.get("orphan_only") == "1")
    # entity filters (GET) from search-select hidden inputs
    f_sj = _parse_int_list(request.args.getlist("ref_sj"))
    f_polygon = _parse_text_list(request.args.getlist("ref_polygon"))
    f_section = _parse_int_list(request.args.getlist("ref_section"))
    f_find = _parse_int_list(request.args.getlist("ref_find"))
    f_sample = _parse_int_list(request.args.getlist("ref_sample"))

    page = _as_int(request.args.get("page")) or 1
    per_page = _as_int(request.args.get("per_page")) or 24
    offset = (page - 1) * per_page

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            # stats
            cur.execute(sketches_stats_sql())
            total_cnt, total_bytes, orphan_cnt = cur.fetchone()

            cur.execute(sketches_stats_by_type_sql())
            by_type = cur.fetchall()

            # page rows
            cur.execute(
                select_sketches_page_sql(
                    orphan_only=orphan_only,
                    has_typ=bool(f_typ),
                    has_author=bool(f_author),
                    has_df=bool(f_date_from),
                    has_dt=bool(f_date_to),
                    has_sj=bool(f_sj),
                    has_polygon=bool(f_polygon),
                    has_section=bool(f_section),
                    has_find=bool(f_find),
                    has_sample=bool(f_sample),
                ),
                {
                    "typ_list": f_typ,
                    "author": f_author,
                    "date_from": f_date_from,
                    "date_to": f_date_to,
                    "sj_list": f_sj,
                    "polygon_list": f_polygon,
                    "section_list": f_section,
                    "find_list": f_find,
                    "sample_list": f_sample,
                    "limit": per_page,
                    "offset": offset,
                },
            )
            rows = cur.fetchall()

    # tuple -> dict for Jinja
    sketches_rows = []
    for r in rows:
        # (id_sketch, sketch_typ, author, datum, notes, link_counts_json)
        lc = r[5]
        if isinstance(lc, str):
            try:
                lc = json.loads(lc)
            except Exception:
                lc = {}
        if lc is None:
            lc = {}
        sketches_rows.append({
            "id_sketch": r[0],
            "sketch_typ": r[1],
            "author": r[2],
            "datum": r[3].strftime("%Y-%m-%d") if r[3] else "",
            "notes": r[4],
            "link_counts": {
                "sj": int(lc.get("sj", 0)) if isinstance(lc, dict) else 0,
                "polygon": int(lc.get("polygon", 0)) if isinstance(lc, dict) else 0,
                "section": int(lc.get("section", 0)) if isinstance(lc, dict) else 0,
                "find": int(lc.get("find", 0)) if isinstance(lc, dict) else 0,
                "sample": int(lc.get("sample", 0)) if isinstance(lc, dict) else 0,
            }
        })

    def _human_bytes(n: int | None) -> str:
        if n is None:
            return "0 B"
        x = float(n)
        for u in ["B", "KB", "MB", "GB", "TB"]:
            if x < 1024.0:
                return f"{x:.1f} {u}"
            x /= 1024.0
        return f"{x:.1f} PB"

    stats = {
        "total_cnt": total_cnt,
        "total_bytes_h": _human_bytes(total_bytes),
        "orphan_cnt": orphan_cnt,
        "by_type": by_type,
    }

    filters = {
        "sketch_typ": f_typ,
        "author": f_author,
        "date_from": f_date_from,
        "date_to": f_date_to,
        "orphan_only": orphan_only,
        "ref_sj": f_sj,
        "ref_polygon": f_polygon,
        "ref_section": f_section,
        "ref_find": f_find,
        "ref_sample": f_sample,
    }

    return render_template(
        "sketches.html",
        selected_db=selected_db,
        sketches=sketches_rows,
        page=page,
        per_page=per_page,
        stats=stats,
        filters=filters,
        sketch_typ_choices=SKETCH_TYP_CHOICES,
    )


# ---------------------------------------
# UPLOAD (multi-block)
# ---------------------------------------
@sketches_bp.post("/sketches/upload")
@require_selected_db
def upload_sketches():
    selected_db = session["selected_db"]

    # ---- 1) shared fields (single form, many files) ----
    sketch_typ = (request.form.get("sketch_typ") or "").strip()
    author = (request.form.get("author") or "").strip() or None
    datum = _as_date_str(request.form.get("datum"))
    notes = (request.form.get("notes") or "").strip() or None

    if sketch_typ not in SKETCH_TYP_CHOICES:
        flash("Upload failed: Invalid sketch_typ.", "danger")
        return redirect(url_for("sketches.sketches"))
    if not author:
        flash("Upload failed: Missing author.", "danger")
        return redirect(url_for("sketches.sketches"))

    sj_ids = request.form.getlist("ref_sj")
    polygons = request.form.getlist("ref_polygon")
    sections = request.form.getlist("ref_section")
    finds = request.form.getlist("ref_find")
    samples = request.form.getlist("ref_sample")

    files = request.files.getlist("files")
    files = [f for f in files if f and f.filename]
    if not files:
        flash("Upload failed: No files provided.", "danger")
        return redirect(url_for("sketches.sketches"))

    # ---- 2) stage / validate all first ----
    staged_paths = []
    final_pairs = []
    items = []
    batch_checksums = set()

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # ---- 2a) validate referenced entities (fail-fast) ----
            def _assert_exists(sql: str, value, err: str):
                cur.execute(sql, (value,))
                if not cur.fetchone():
                    raise ValueError(err)

            _assert_exists("SELECT 1 FROM gloss_personalia WHERE mail=%s LIMIT 1;",
                          author, f"Author not found: {author}")

            for sj in sj_ids:
                sj_i = _as_int(sj)
                if sj_i is None:
                    continue
                _assert_exists("SELECT 1 FROM tab_sj WHERE id_sj=%s LIMIT 1;",
                              sj_i, f"SU not found: {sj_i}")

            for p in polygons:
                p = (p or "").strip()
                if not p:
                    continue
                _assert_exists("SELECT 1 FROM tab_polygons WHERE polygon_name=%s LIMIT 1;",
                              p, f"Polygon not found: {p}")

            for s in sections:
                s_i = _as_int(s)
                if s_i is None:
                    continue
                _assert_exists("SELECT 1 FROM tab_section WHERE id_section=%s LIMIT 1;",
                              s_i, f"Section not found: {s_i}")

            for fd in finds:
                fd_i = _as_int(fd)
                if fd_i is None:
                    continue
                _assert_exists("SELECT 1 FROM tab_finds WHERE id_find=%s LIMIT 1;",
                              fd_i, f"Find not found: {fd_i}")

            for sp in samples:
                sp_i = _as_int(sp)
                if sp_i is None:
                    continue
                _assert_exists("SELECT 1 FROM tab_samples WHERE id_sample=%s LIMIT 1;",
                              sp_i, f"Sample not found: {sp_i}")

            # ---- 2b) stage each file + validate ----
            for f in files:
                tmp_path, _ = save_to_uploads(Config.UPLOAD_FOLDER, f)
                staged_paths.append(tmp_path)

                pk_name = make_pk(selected_db, f.filename)
                validate_pk(pk_name)
                ext = pk_name.rsplit(".", 1)[-1].lower()
                validate_extension(ext, Config.ALLOWED_EXTENSIONS)

                media_dir = Config.MEDIA_DIRS["sketches"]
                final_path, thumb_path = final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)

                if os.path.exists(final_path):
                    raise ValueError(f"File already exists on FS: {pk_name}")

                cur.execute("SELECT 1 FROM tab_sketches WHERE id_sketch=%s LIMIT 1;", (pk_name,))
                if cur.fetchone():
                    raise ValueError(f"Sketch already exists in DB: {pk_name}")

                mime = detect_mime(tmp_path)
                validate_mime(mime, Config.ALLOWED_MIME)
                checksum = sha256_file(tmp_path)

                cur.execute(sketch_checksum_exists_sql(), (checksum,))
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

            # ---- 3) move -> thumbnail -> DB insert + links in ONE transaction ----
            for it in items:
                move_into_place(it["tmp_path"], it["final_path"])
                it["tmp_path"] = None
                final_pairs.append((it["final_path"], it["thumb_path"]))

                make_thumbnail(it["final_path"], it["thumb_path"], Config.THUMB_MAX_SIDE)

                cur.execute(
                    insert_sketch_sql(),
                    (
                        it["pk_name"], sketch_typ, author, datum, notes,
                        it["mime"], os.path.getsize(it["final_path"]), it["checksum"],
                    ),
                )

                for sj in sj_ids:
                    sj_i = _as_int(sj)
                    if sj_i is not None:
                        cur.execute(link_sketch_sj_sql(), (sj_i, it["pk_name"]))

                for p in polygons:
                    p = (p or "").strip()
                    if p:
                        cur.execute(link_sketch_polygon_sql(), (p, it["pk_name"]))

                for s in sections:
                    s_i = _as_int(s)
                    if s_i is not None:
                        cur.execute(link_sketch_section_sql(), (s_i, it["pk_name"]))

                for fd in finds:
                    fd_i = _as_int(fd)
                    if fd_i is not None:
                        cur.execute(link_sketch_find_sql(), (fd_i, it["pk_name"]))

                for sp in samples:
                    sp_i = _as_int(sp)
                    if sp_i is not None:
                        cur.execute(link_sketch_sample_sql(), (sp_i, it["pk_name"]))

            conn.commit()
            flash(f"Uploaded {len(items)} sketch(es).", "success")
            logger.info(f"[{selected_db}] sketches upload ok: count={len(items)}")

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

        logger.warning(f"[{selected_db}] sketches upload failed: {e}")
        flash(f"Upload failed: {e}", "danger")
        return redirect(url_for("sketches.sketches"))

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("sketches.sketches"))


# ---------------------------------------
# BULK (links only)
# ---------------------------------------
@sketches_bp.post("/sketches/bulk")
@require_selected_db
def bulk_sketches():
    selected_db = session["selected_db"]

    action = (request.form.get("action") or "").strip()
    ids = request.form.getlist("sketch_ids")
    if not ids:
        flash("No sketches selected.", "warning")
        return redirect(url_for("sketches.sketches"))

    sj_ids = request.form.getlist("ref_sj")
    polygons = request.form.getlist("ref_polygon")
    sections = request.form.getlist("ref_section")
    finds = request.form.getlist("ref_find")
    samples = request.form.getlist("ref_sample")

    if action not in ("add_links", "remove_links"):
        flash("Invalid bulk action.", "danger")
        return redirect(url_for("sketches.sketches"))

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            for sid in ids:
                sid = (sid or "").strip()
                if not sid:
                    continue

                for sj in sj_ids:
                    sj_i = _as_int(sj)
                    if sj_i is None:
                        continue
                    if action == "add_links":
                        cur.execute(link_sketch_sj_sql(), (sj_i, sid))
                    else:
                        cur.execute(unlink_sketch_sj_sql(), (sj_i, sid))

                for p in polygons:
                    p = (p or "").strip()
                    if not p:
                        continue
                    if action == "add_links":
                        cur.execute(link_sketch_polygon_sql(), (p, sid))
                    else:
                        cur.execute(unlink_sketch_polygon_sql(), (p, sid))

                for s in sections:
                    s_i = _as_int(s)
                    if s_i is None:
                        continue
                    if action == "add_links":
                        cur.execute(link_sketch_section_sql(), (s_i, sid))
                    else:
                        cur.execute(unlink_sketch_section_sql(), (s_i, sid))

                for fd in finds:
                    fd_i = _as_int(fd)
                    if fd_i is None:
                        continue
                    if action == "add_links":
                        cur.execute(link_sketch_find_sql(), (fd_i, sid))
                    else:
                        cur.execute(unlink_sketch_find_sql(), (fd_i, sid))

                for sp in samples:
                    sp_i = _as_int(sp)
                    if sp_i is None:
                        continue
                    if action == "add_links":
                        cur.execute(link_sketch_sample_sql(), (sp_i, sid))
                    else:
                        cur.execute(unlink_sketch_sample_sql(), (sp_i, sid))

        conn.commit()

    flash("Bulk operation applied.", "success")
    return redirect(url_for("sketches.sketches"))


# ---------------------------------------
# API: DETAIL (edit modal)
# ---------------------------------------
@sketches_bp.get("/sketches/api/detail/<path:id_sketch>")
@require_selected_db
def api_detail(id_sketch: str):
    selected_db = session["selected_db"]
    sid = (id_sketch or "").strip()

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(select_sketch_detail_sql(), (sid,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "not found"}), 404

            cur.execute(select_sketch_links_sql(), (sid, sid, sid, sid, sid))
            links = cur.fetchone()

    data = {
        "id_sketch": row[0],
        "sketch_typ": row[1],
        "author": row[2],
        "datum": row[3].strftime("%Y-%m-%d") if row[3] else "",
        "notes": row[4] or "",
        "links": {
            "sj_ids": links[0] or [],
            "polygon_names": links[1] or [],
            "section_ids": links[2] or [],
            "find_ids": links[3] or [],
            "sample_ids": links[4] or [],
        },
    }
    return jsonify(data)


# ---------------------------------------
# EDIT (replace file optional)
# ---------------------------------------
@sketches_bp.post("/sketches/edit/<path:id_sketch>")
@require_selected_db
def edit_sketch(id_sketch: str):
    selected_db = session["selected_db"]
    sid = (id_sketch or "").strip()

    sketch_typ = (request.form.get("sketch_typ") or "").strip()
    author = (request.form.get("author") or "").strip() or None
    datum = _as_date_str(request.form.get("datum"))
    notes = (request.form.get("notes") or "").strip() or None

    if sketch_typ not in SKETCH_TYP_CHOICES:
        flash("Invalid sketch type.", "danger")
        return redirect(url_for("sketches.sketches"))
    if not author:
        flash("Missing author.", "danger")
        return redirect(url_for("sketches.sketches"))

    sj_ids = request.form.getlist("ref_sj")
    polygons = request.form.getlist("ref_polygon")
    sections = request.form.getlist("ref_section")
    finds = request.form.getlist("ref_find")
    samples = request.form.getlist("ref_sample")

    repl = request.files.get("replace_file")
    replace = bool(repl and repl.filename)

    media_dir = Config.MEDIA_DIRS["sketches"]
    final_path, thumb_path = final_paths(Config.DATA_DIR, selected_db, media_dir, sid)

    tmp_path = None
    tmp_final_path = None
    tmp_thumb_path = None

    try:
        with get_terrain_connection(selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(sketch_exists_sql(), (sid,))
                if not cur.fetchone():
                    flash("Sketch not found.", "danger")
                    return redirect(url_for("sketches.sketches"))

                new_mime = new_size = new_checksum = None

                if replace:
                    tmp_path, _ = save_to_uploads(Config.UPLOAD_FOLDER, repl)

                    ext = repl.filename.rsplit(".", 1)[-1].lower() if "." in repl.filename else ""
                    validate_extension(ext, Config.ALLOWED_EXTENSIONS)

                    tmp_final_path = final_path + ".tmp_replace"
                    tmp_thumb_path = thumb_path + ".tmp_replace"

                    try:
                        if os.path.exists(tmp_final_path):
                            os.remove(tmp_final_path)
                        if os.path.exists(tmp_thumb_path):
                            os.remove(tmp_thumb_path)
                    except Exception:
                        pass

                    move_into_place(tmp_path, tmp_final_path)
                    tmp_path = None

                    new_mime = detect_mime(tmp_final_path)
                    validate_mime(new_mime, Config.ALLOWED_MIME)
                    new_checksum = sha256_file(tmp_final_path)
                    new_size = os.path.getsize(tmp_final_path)

                    cur.execute(sketch_checksum_exists_sql(), (new_checksum,))
                    if cur.fetchone():
                        raise ValueError("Duplicate content (checksum already exists).")

                    try:
                        make_thumbnail(tmp_final_path, tmp_thumb_path, Config.THUMB_MAX_SIDE)
                    except Exception:
                        tmp_thumb_path = None

                else:
                    cur.execute("SELECT mime_type, file_size, checksum_sha256 FROM tab_sketches WHERE id_sketch=%s", (sid,))
                    new_mime, new_size, new_checksum = cur.fetchone()

                cur.execute(
                    update_sketch_sql(),
                    (
                        sketch_typ, author, datum, notes,
                        new_mime, new_size, new_checksum,
                        sid,
                    ),
                )

                # reset links
                cur.execute("DELETE FROM tabaid_sj_sketch WHERE ref_sketch=%s", (sid,))
                cur.execute("DELETE FROM tabaid_polygon_sketches WHERE ref_sketch=%s", (sid,))
                cur.execute("DELETE FROM tabaid_section_sketches WHERE ref_sketch=%s", (sid,))
                cur.execute("DELETE FROM tabaid_finds_sketches WHERE ref_sketch=%s", (sid,))
                cur.execute("DELETE FROM tabaid_samples_sketches WHERE ref_sketch=%s", (sid,))

                for sj in sj_ids:
                    sj_i = _as_int(sj)
                    if sj_i is not None:
                        cur.execute(link_sketch_sj_sql(), (sj_i, sid))

                for p in polygons:
                    p = (p or "").strip()
                    if p:
                        cur.execute(link_sketch_polygon_sql(), (p, sid))

                for s in sections:
                    s_i = _as_int(s)
                    if s_i is not None:
                        cur.execute(link_sketch_section_sql(), (s_i, sid))

                for fd in finds:
                    fd_i = _as_int(fd)
                    if fd_i is not None:
                        cur.execute(link_sketch_find_sql(), (fd_i, sid))

                for sp in samples:
                    sp_i = _as_int(sp)
                    if sp_i is not None:
                        cur.execute(link_sketch_sample_sql(), (sp_i, sid))

            conn.commit()

        # swap files after commit
        if replace and tmp_final_path:
            os.replace(tmp_final_path, final_path)
            tmp_final_path = None

            if tmp_thumb_path and os.path.exists(tmp_thumb_path):
                os.replace(tmp_thumb_path, thumb_path)
                tmp_thumb_path = None
            else:
                try:
                    make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
                except Exception:
                    pass

        flash("Sketch updated.", "success")

    except Exception as e:
        logger.warning(f"[{selected_db}] sketch edit failed {sid}: {e}")
        flash(f"Edit failed: {e}", "danger")
        try:
            if tmp_final_path and os.path.exists(tmp_final_path):
                os.remove(tmp_final_path)
            if tmp_thumb_path and os.path.exists(tmp_thumb_path):
                os.remove(tmp_thumb_path)
        except Exception:
            pass
    finally:
        if tmp_path:
            try:
                cleanup_upload(tmp_path)
            except Exception:
                pass

    return redirect(url_for("sketches.sketches"))


# ---------------------------------------
# DELETE
# ---------------------------------------
@sketches_bp.post("/sketches/delete/<path:id_sketch>")
@require_selected_db
def delete_sketch(id_sketch: str):
    selected_db = session["selected_db"]
    sid = (id_sketch or "").strip()

    media_dir = Config.MEDIA_DIRS["sketches"]
    final_path, thumb_path = final_paths(Config.DATA_DIR, selected_db, media_dir, sid)

    try:
        with get_terrain_connection(selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(delete_sketch_sql(), (sid,))
            conn.commit()

        try:
            delete_media_files(final_path, thumb_path)
        except Exception:
            pass

        flash("Sketch deleted.", "success")
    except Exception as e:
        logger.warning(f"[{selected_db}] sketch delete failed {sid}: {e}")
        flash(f"Delete failed: {e}", "danger")

    return redirect(url_for("sketches.sketches"))


# ---------------------------------------
# FILE SERVE
# ---------------------------------------
@sketches_bp.get("/sketches/file/<path:id_sketch>")
@require_selected_db
def serve_sketch_file(id_sketch: str):
    from flask import send_from_directory
    selected_db = session["selected_db"]
    sid = (id_sketch or "").strip()
    dir_path = os.path.join(Config.DATA_DIR, selected_db, Config.MEDIA_DIRS["sketches"])
    return send_from_directory(dir_path, sid, as_attachment=False)


@sketches_bp.get("/sketches/thumb/<path:id_sketch>")
@require_selected_db
def serve_sketch_thumb(id_sketch: str):
    from flask import send_from_directory
    selected_db = session["selected_db"]
    sid = (id_sketch or "").strip()
    dir_path = os.path.join(Config.DATA_DIR, selected_db, Config.MEDIA_DIRS["sketches"], "thumbs")
    return send_from_directory(dir_path, sid, as_attachment=False)


# ---------------------------------------
# SEARCH endpoints (SearchSelect)
# ---------------------------------------
def _api_search(selected_db: str, sql: str, q: str):
    q = (q or "").strip()
    if not q:
        return jsonify({"results": []})
    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (f"%{q}%", 20, 0))
            rows = cur.fetchall()
    return jsonify({"results": [{"id": r[0], "text": r[1]} for r in rows]})


@sketches_bp.get("/sketches/api/search/sj")
@require_selected_db
def api_search_sj():
    return _api_search(session["selected_db"], search_sj_sql(), request.args.get("q", ""))


@sketches_bp.get("/sketches/api/search/polygons")
@require_selected_db
def api_search_polygons():
    return _api_search(session["selected_db"], search_polygons_sql(), request.args.get("q", ""))


@sketches_bp.get("/sketches/api/search/sections")
@require_selected_db
def api_search_sections():
    return _api_search(session["selected_db"], search_sections_sql(), request.args.get("q", ""))


@sketches_bp.get("/sketches/api/search/finds")
@require_selected_db
def api_search_finds():
    return _api_search(session["selected_db"], search_finds_sql(), request.args.get("q", ""))


@sketches_bp.get("/sketches/api/search/samples")
@require_selected_db
def api_search_samples():
    return _api_search(session["selected_db"], search_samples_sql(), request.args.get("q", ""))


@sketches_bp.get("/sketches/api/search/authors")
@require_selected_db
def api_search_authors():
    return _api_search(session["selected_db"], search_authors_sql(), request.args.get("q", ""))
