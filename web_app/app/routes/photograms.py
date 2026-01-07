# app/routes/photograms.py
from __future__ import annotations

import os
import json
from typing import Any

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from psycopg2.extras import Json

from config import Config
from app.logger import logger
from app.database import get_terrain_connection

from app.utils import (
    save_to_uploads, cleanup_upload, move_into_place, delete_media_files,
    make_pk, validate_pk, final_paths,
    detect_mime, make_thumbnail,
    sha256_file, validate_extension, validate_mime
)

from app.utils.decorators import require_selected_db

from app.queries import (
    # INSERT/UPDATE/DELETE
    insert_photogram_sql,
    update_photogram_sql,
    delete_photogram_sql,

    # DEDUP checks
    photogram_checksum_exists_sql,
    photogram_exists_sql,

    # LINK ops
    link_photogram_sj_sql,
    unlink_photogram_sj_sql,
    link_photogram_polygon_sql,
    unlink_photogram_polygon_sql,
    link_photogram_section_sql,
    unlink_photogram_section_sql,

    # GEOPTS ranges
    insert_photogram_geopts_range_sql,
    delete_photogram_geopts_ranges_sql,
    select_photogram_geopts_ranges_sql,

    # LIST/DETAIL/STATS
    select_photograms_page_sql,
    select_photogram_detail_sql,
    select_photogram_links_sql,
    photograms_stats_sql,
    photograms_stats_by_type_sql,

    # SEARCH endpoints
    search_sj_sql,
    search_polygons_sql,
    search_sections_sql,
    search_sketches_sql,
    search_photos_sql,
)

photograms_bp = Blueprint("photograms", __name__)

PHOTOGRAM_TYP_CHOICES = ["stereo", "resection", "synthetic", "other"]


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


def _parse_int_list(vals: list[str]) -> list[int]:
    out: list[int] = []
    for v in vals or []:
        i = _as_int(v)
        if i is not None:
            out.append(i)
    # unique keep order
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    return uniq


def _parse_text_list(vals: list[str]) -> list[str]:
    out: list[str] = []
    for v in vals or []:
        s = (v or "").strip()
        if s:
            out.append(s)
    # unique keep order
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    return uniq


def _read_range_pairs(form: Any, from_name: str, to_name: str) -> list[tuple[int, int]]:
    from_list = form.getlist(from_name)
    to_list = form.getlist(to_name)

    pairs: list[tuple[int, int]] = []
    for f, t in zip(from_list, to_list):
        a = _as_int(f)
        b = _as_int(t)
        if a is None and b is None:
            continue
        if a is None or b is None:
            raise ValueError("Invalid geopts range (FROM/TO must be integers).")
        if a <= 0 or b <= 0:
            raise ValueError("Invalid geopts range (IDs must be positive).")
        if a > b:
            raise ValueError("Invalid geopts range (FROM must be <= TO).")
        pairs.append((a, b))
    return pairs


def _human_bytes(n: int | None) -> str:
    if n is None:
        return "0 B"
    x = float(n)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if x < 1024.0:
            return f"{x:.1f} {u}"
        x /= 1024.0
    return f"{x:.1f} PB"


# ---------------------------------------
# PAGE
# ---------------------------------------
@photograms_bp.get("/photograms")
@require_selected_db
def photograms():
    selected_db = session["selected_db"]

    # filters (GET)
    f_typ = request.args.getlist("photogram_typ")  # multi
    f_sketch = (request.args.get("ref_sketch") or "").strip() or None
    f_photo_from = (request.args.get("ref_photo_from") or "").strip() or None
    f_photo_to = (request.args.get("ref_photo_to") or "").strip() or None
    orphan_only = (request.args.get("orphan_only") == "1")

    # NEW: entity filters
    f_sj_ids = _parse_int_list(request.args.getlist("ref_sj"))
    f_polygon_names = _parse_text_list(request.args.getlist("ref_polygon"))
    f_section_ids = _parse_int_list(request.args.getlist("ref_section"))

    page = _as_int(request.args.get("page")) or 1
    per_page = _as_int(request.args.get("per_page")) or 24
    offset = (page - 1) * per_page

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(photograms_stats_sql())
            total_cnt, total_bytes, orphan_cnt = cur.fetchone()

            cur.execute(photograms_stats_by_type_sql())
            by_type = cur.fetchall()

            cur.execute(
                select_photograms_page_sql(
                    orphan_only=orphan_only,
                    has_typ=bool(f_typ),
                    has_sketch=bool(f_sketch),
                    has_pf=bool(f_photo_from),
                    has_pt=bool(f_photo_to),
                    has_sj=bool(f_sj_ids),
                    has_polygon=bool(f_polygon_names),
                    has_section=bool(f_section_ids),
                ),
                {
                    "typ_list": f_typ,
                    "ref_sketch": f_sketch,
                    "ref_photo_from": f_photo_from,
                    "ref_photo_to": f_photo_to,
                    "sj_ids": f_sj_ids,
                    "polygon_names": f_polygon_names,
                    "section_ids": f_section_ids,
                    "limit": per_page,
                    "offset": offset,
                },
            )
            rows = cur.fetchall()

    photograms_rows = []
    for r in rows:
        lc = r[6]
        if isinstance(lc, str):
            try:
                lc = json.loads(lc)
            except Exception:
                lc = {}
        if lc is None:
            lc = {}

        photograms_rows.append({
            "id_photogram": r[0],
            "photogram_typ": r[1],
            "ref_sketch": r[2],
            "notes": r[3],
            "ref_photo_from": r[4],
            "ref_photo_to": r[5],
            "link_counts": {
                "sj": int(lc.get("sj", 0)) if isinstance(lc, dict) else 0,
                "polygon": int(lc.get("polygon", 0)) if isinstance(lc, dict) else 0,
                "section": int(lc.get("section", 0)) if isinstance(lc, dict) else 0,
                "ranges": int(lc.get("ranges", 0)) if isinstance(lc, dict) else 0,
            },
        })

    stats = {
        "total_cnt": total_cnt,
        "total_bytes_h": _human_bytes(total_bytes),
        "orphan_cnt": orphan_cnt,
        "by_type": by_type,
    }

    filters = {
        "photogram_typ": f_typ,
        "ref_sketch": f_sketch,
        "ref_photo_from": f_photo_from,
        "ref_photo_to": f_photo_to,
        "orphan_only": orphan_only,
        "ref_sj": f_sj_ids,
        "ref_polygon": f_polygon_names,
        "ref_section": f_section_ids,
    }

    # pagination URLs preserving filters
    def _page_url(new_page: int) -> str:
        args = {}
        for k, vals in request.args.lists():
            if k == "page":
                continue
            args[k] = vals
        args["page"] = new_page
        args["per_page"] = per_page
        return url_for("photograms.photograms", **args)

    prev_url = _page_url(page - 1) if page > 1 else None
    next_url = _page_url(page + 1)

    return render_template(
        "photograms.html",
        selected_db=selected_db,
        photograms=photograms_rows,
        page=page,
        per_page=per_page,
        prev_url=prev_url,
        next_url=next_url,
        stats=stats,
        filters=filters,
        photogram_typ_choices=PHOTOGRAM_TYP_CHOICES,
    )


# ---------------------------------------
# UPLOAD
# ---------------------------------------
@photograms_bp.post("/photograms/upload")
@require_selected_db
def upload_photograms():
    selected_db = session["selected_db"]

    typ = (request.form.get("photogram_typ") or "").strip()
    notes = (request.form.get("notes") or "").strip() or None

    ref_sketch = (request.form.get("ref_sketch") or "").strip() or None
    ref_photo_from = (request.form.get("ref_photo_from") or "").strip() or None
    ref_photo_to = (request.form.get("ref_photo_to") or "").strip() or None

    sj_ids = request.form.getlist("ref_sj")
    polygons = request.form.getlist("ref_polygon")
    sections = request.form.getlist("ref_section")

    try:
        ranges = _read_range_pairs(request.form, "geopt_from[]", "geopt_to[]")
    except Exception as e:
        flash(f"Upload failed: {e}", "danger")
        return redirect(url_for("photograms.photograms"))

    if typ not in PHOTOGRAM_TYP_CHOICES:
        flash("Upload failed: Invalid photogram_typ.", "danger")
        return redirect(url_for("photograms.photograms"))

    files = request.files.getlist("files")
    files = [f for f in files if f and f.filename]
    if not files:
        flash("Upload failed: No files provided.", "danger")
        return redirect(url_for("photograms.photograms"))

    staged_paths = []
    final_pairs = []  # (final_path, thumb_path)
    items = []
    batch_checksums = set()

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            def _assert_exists(sql: str, value, err: str):
                cur.execute(sql, (value,))
                if not cur.fetchone():
                    raise ValueError(err)

            if ref_sketch:
                _assert_exists("SELECT 1 FROM tab_sketches WHERE id_sketch=%s LIMIT 1;",
                              ref_sketch, f"Ref sketch not found: {ref_sketch}")

            if ref_photo_from:
                _assert_exists("SELECT 1 FROM tab_photos WHERE id_photo=%s LIMIT 1;",
                              ref_photo_from, f"Ref photo_from not found: {ref_photo_from}")

            if ref_photo_to:
                _assert_exists("SELECT 1 FROM tab_photos WHERE id_photo=%s LIMIT 1;",
                              ref_photo_to, f"Ref photo_to not found: {ref_photo_to}")

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

            for f in files:
                tmp_path, _ = save_to_uploads(Config.UPLOAD_FOLDER, f)
                staged_paths.append(tmp_path)

                pk_name = make_pk(selected_db, f.filename)
                validate_pk(pk_name)
                ext = pk_name.rsplit(".", 1)[-1].lower()
                validate_extension(ext, Config.ALLOWED_EXTENSIONS)

                media_dir = Config.MEDIA_DIRS["photograms"]
                final_path, thumb_path = final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)

                if os.path.exists(final_path):
                    raise ValueError(f"File already exists on FS: {pk_name}")

                cur.execute("SELECT 1 FROM tab_photograms WHERE id_photogram=%s LIMIT 1;", (pk_name,))
                if cur.fetchone():
                    raise ValueError(f"Photogram already exists in DB: {pk_name}")

                mime = detect_mime(tmp_path)
                validate_mime(mime, Config.ALLOWED_MIME)
                checksum = sha256_file(tmp_path)

                cur.execute(photogram_checksum_exists_sql(), (checksum,))
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

            for it in items:
                move_into_place(it["tmp_path"], it["final_path"])
                it["tmp_path"] = None
                final_pairs.append((it["final_path"], it["thumb_path"]))

                make_thumbnail(it["final_path"], it["thumb_path"], Config.THUMB_MAX_SIDE)

                cur.execute(
                    insert_photogram_sql(),
                    (
                        it["pk_name"],
                        typ,
                        ref_sketch,
                        notes,
                        it["mime"],
                        os.path.getsize(it["final_path"]),
                        it["checksum"],
                        ref_photo_from,
                        ref_photo_to,
                    ),
                )

                for sj in sj_ids:
                    sj_i = _as_int(sj)
                    if sj_i is not None:
                        cur.execute(link_photogram_sj_sql(), (it["pk_name"], sj_i))

                for p in polygons:
                    p = (p or "").strip()
                    if p:
                        cur.execute(link_photogram_polygon_sql(), (p, it["pk_name"]))

                for s in sections:
                    s_i = _as_int(s)
                    if s_i is not None:
                        cur.execute(link_photogram_section_sql(), (s_i, it["pk_name"]))

                for a, b in ranges:
                    cur.execute(insert_photogram_geopts_range_sql(), (it["pk_name"], a, b))

            conn.commit()
            flash(f"Uploaded {len(items)} photogram(s).", "success")
            logger.info(f"[{selected_db}] photograms upload ok: count={len(items)}")

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

        logger.warning(f"[{selected_db}] photograms upload failed: {e}")
        flash(f"Upload failed: {e}", "danger")
        return redirect(url_for("photograms.photograms"))

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("photograms.photograms"))


# ---------------------------------------
# BULK (links only)
# ---------------------------------------
@photograms_bp.post("/photograms/bulk")
@require_selected_db
def bulk_photograms():
    selected_db = session["selected_db"]

    action = (request.form.get("action") or "").strip()
    ids = request.form.getlist("photogram_ids")
    if not ids:
        flash("No photograms selected.", "warning")
        return redirect(url_for("photograms.photograms"))

    sj_ids = request.form.getlist("ref_sj")
    polygons = request.form.getlist("ref_polygon")
    sections = request.form.getlist("ref_section")

    if action not in ("add_links", "remove_links"):
        flash("Invalid bulk action.", "danger")
        return redirect(url_for("photograms.photograms"))

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            def _assert_exists(sql: str, value, err: str):
                cur.execute(sql, (value,))
                if not cur.fetchone():
                    raise ValueError(err)

            # validate entities once
            for sj in sj_ids:
                sj_i = _as_int(sj)
                if sj_i is None:
                    continue
                _assert_exists("SELECT 1 FROM tab_sj WHERE id_sj=%s LIMIT 1;", sj_i, f"SU not found: {sj_i}")

            for p in polygons:
                p = (p or "").strip()
                if not p:
                    continue
                _assert_exists("SELECT 1 FROM tab_polygons WHERE polygon_name=%s LIMIT 1;", p, f"Polygon not found: {p}")

            for s in sections:
                s_i = _as_int(s)
                if s_i is None:
                    continue
                _assert_exists("SELECT 1 FROM tab_section WHERE id_section=%s LIMIT 1;", s_i, f"Section not found: {s_i}")

            for pid in ids:
                pid = (pid or "").strip()
                if not pid:
                    continue

                for sj in sj_ids:
                    sj_i = _as_int(sj)
                    if sj_i is None:
                        continue
                    if action == "add_links":
                        cur.execute(link_photogram_sj_sql(), (pid, sj_i))
                    else:
                        cur.execute(unlink_photogram_sj_sql(), (pid, sj_i))

                for p in polygons:
                    p = (p or "").strip()
                    if not p:
                        continue
                    if action == "add_links":
                        cur.execute(link_photogram_polygon_sql(), (p, pid))
                    else:
                        cur.execute(unlink_photogram_polygon_sql(), (p, pid))

                for s in sections:
                    s_i = _as_int(s)
                    if s_i is None:
                        continue
                    if action == "add_links":
                        cur.execute(link_photogram_section_sql(), (s_i, pid))
                    else:
                        cur.execute(unlink_photogram_section_sql(), (s_i, pid))

        conn.commit()

    flash("Bulk operation applied.", "success")
    return redirect(url_for("photograms.photograms"))


# ---------------------------------------
# API: DETAIL (for edit modal)
# ---------------------------------------
@photograms_bp.get("/photograms/api/detail/<path:id_photogram>")
@require_selected_db
def api_detail(id_photogram: str):
    selected_db = session["selected_db"]
    pid = (id_photogram or "").strip()

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            cur.execute(select_photogram_detail_sql(), (pid,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "not found"}), 404

            cur.execute(select_photogram_links_sql(), (pid,))
            links = cur.fetchone()

            cur.execute(select_photogram_geopts_ranges_sql(), (pid,))
            ranges = cur.fetchall()

    data = {
        "id_photogram": row[0],
        "photogram_typ": row[1],
        "ref_sketch": row[2],
        "notes": row[3],
        "ref_photo_from": row[4],
        "ref_photo_to": row[5],
        "links": {
            "sj_ids": links[0] or [],
            "polygon_names": links[1] or [],
            "section_ids": links[2] or [],
        },
        "geopts_ranges": [{"from": r[0], "to": r[1]} for r in ranges],
    }
    return jsonify(data)


# ---------------------------------------
# EDIT (replace file optional)
# ---------------------------------------
@photograms_bp.post("/photograms/edit/<path:id_photogram>")
@require_selected_db
def edit_photogram(id_photogram: str):
    selected_db = session["selected_db"]
    pid = (id_photogram or "").strip()

    typ = (request.form.get("photogram_typ") or "").strip()
    notes = (request.form.get("notes") or "").strip() or None
    ref_sketch = (request.form.get("ref_sketch") or "").strip() or None
    ref_photo_from = (request.form.get("ref_photo_from") or "").strip() or None
    ref_photo_to = (request.form.get("ref_photo_to") or "").strip() or None

    if typ not in PHOTOGRAM_TYP_CHOICES:
        flash("Invalid photogram type.", "danger")
        return redirect(url_for("photograms.photograms"))

    sj_ids = request.form.getlist("ref_sj")
    polygons = request.form.getlist("ref_polygon")
    sections = request.form.getlist("ref_section")
    ranges = _read_range_pairs(request.form, "geopt_from[]", "geopt_to[]")

    repl = request.files.get("replace_file")
    replace = bool(repl and repl.filename)

    media_dir = Config.MEDIA_DIRS["photograms"]
    final_path, thumb_path = final_paths(Config.DATA_DIR, selected_db, media_dir, pid)

    tmp_path = None
    tmp_final_path = None
    tmp_thumb_path = None

    try:
        with get_terrain_connection(selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(photogram_exists_sql(), (pid,))
                if not cur.fetchone():
                    flash("Photogram not found.", "danger")
                    return redirect(url_for("photograms.photograms"))

                new_mime = None
                new_size = None
                new_checksum = None

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

                    cur.execute(photogram_checksum_exists_sql(), (new_checksum,))
                    if cur.fetchone():
                        raise ValueError("Duplicate content (checksum already exists).")

                    try:
                        make_thumbnail(tmp_final_path, tmp_thumb_path, Config.THUMB_MAX_SIDE)
                    except Exception:
                        tmp_thumb_path = None

                if not replace:
                    cur.execute("SELECT mime_type, file_size, checksum_sha256 FROM tab_photograms WHERE id_photogram=%s", (pid,))
                    old_mime, old_size, old_checksum = cur.fetchone()
                    new_mime, new_size, new_checksum = old_mime, old_size, old_checksum

                cur.execute(
                    update_photogram_sql(),
                    (
                        typ,
                        ref_sketch,
                        notes,
                        new_mime,
                        new_size,
                        new_checksum,
                        ref_photo_from,
                        ref_photo_to,
                        pid,
                    ),
                )

                cur.execute("DELETE FROM tabaid_photogram_sj WHERE ref_photogram=%s", (pid,))
                cur.execute("DELETE FROM tabaid_polygon_photograms WHERE ref_photogram=%s", (pid,))
                cur.execute("DELETE FROM tabaid_section_photograms WHERE ref_photogram=%s", (pid,))
                cur.execute(delete_photogram_geopts_ranges_sql(), (pid,))

                for sj in sj_ids:
                    sj_i = _as_int(sj)
                    if sj_i is None:
                        continue
                    cur.execute(link_photogram_sj_sql(), (pid, sj_i))

                for p in polygons:
                    p = (p or "").strip()
                    if p:
                        cur.execute(link_photogram_polygon_sql(), (p, pid))

                for s in sections:
                    s_i = _as_int(s)
                    if s_i is None:
                        continue
                    cur.execute(link_photogram_section_sql(), (s_i, pid))

                for a, b in ranges:
                    cur.execute(insert_photogram_geopts_range_sql(), (pid, a, b))

            conn.commit()

        if replace and tmp_final_path:
            try:
                os.replace(tmp_final_path, final_path)
            finally:
                tmp_final_path = None

            if tmp_thumb_path and os.path.exists(tmp_thumb_path):
                try:
                    os.replace(tmp_thumb_path, thumb_path)
                finally:
                    tmp_thumb_path = None
            else:
                try:
                    make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
                except Exception:
                    pass

        flash("Photogram updated.", "success")

    except Exception as e:
        logger.warning(f"[{selected_db}] photogram edit failed {pid}: {e}")
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

    return redirect(url_for("photograms.photograms"))


# ---------------------------------------
# DELETE
# ---------------------------------------
@photograms_bp.post("/photograms/delete/<path:id_photogram>")
@require_selected_db
def delete_photogram(id_photogram: str):
    selected_db = session["selected_db"]
    pid = (id_photogram or "").strip()

    media_dir = Config.MEDIA_DIRS["photograms"]
    final_path, thumb_path = final_paths(Config.DATA_DIR, selected_db, media_dir, pid)

    try:
        with get_terrain_connection(selected_db) as conn:
            with conn.cursor() as cur:
                cur.execute(delete_photogram_sql(), (pid,))
            conn.commit()

        try:
            delete_media_files(final_path, thumb_path)
        except Exception:
            pass

        flash("Photogram deleted.", "success")

    except Exception as e:
        logger.warning(f"[{selected_db}] photogram delete failed {pid}: {e}")
        flash(f"Delete failed: {e}", "danger")

    return redirect(url_for("photograms.photograms"))


# ---------------------------------------
# FILE SERVE
# ---------------------------------------
@photograms_bp.get("/photograms/file/<path:id_photogram>")
@require_selected_db
def serve_photogram_file(id_photogram: str):
    from flask import send_from_directory

    selected_db = session["selected_db"]
    pid = (id_photogram or "").strip()

    dir_path = os.path.join(Config.DATA_DIR, selected_db, Config.MEDIA_DIRS["photograms"])
    return send_from_directory(dir_path, pid, as_attachment=False)


@photograms_bp.get("/photograms/thumb/<path:id_photogram>")
@require_selected_db
def serve_photogram_thumb(id_photogram: str):
    from flask import send_from_directory

    selected_db = session["selected_db"]
    pid = (id_photogram or "").strip()

    dir_path = os.path.join(Config.DATA_DIR, selected_db, Config.MEDIA_DIRS["photograms"], "thumbs")
    return send_from_directory(dir_path, pid, as_attachment=False)


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


@photograms_bp.get("/photograms/api/search/sj")
@require_selected_db
def api_search_sj():
    return _api_search(session["selected_db"], search_sj_sql(), request.args.get("q", ""))


@photograms_bp.get("/photograms/api/search/polygons")
@require_selected_db
def api_search_polygons():
    return _api_search(session["selected_db"], search_polygons_sql(), request.args.get("q", ""))


@photograms_bp.get("/photograms/api/search/sections")
@require_selected_db
def api_search_sections():
    return _api_search(session["selected_db"], search_sections_sql(), request.args.get("q", ""))


@photograms_bp.get("/photograms/api/search/sketches")
@require_selected_db
def api_search_sketches():
    return _api_search(session["selected_db"], search_sketches_sql(), request.args.get("q", ""))


@photograms_bp.get("/photograms/api/search/photos")
@require_selected_db
def api_search_photos():
    return _api_search(session["selected_db"], search_photos_sql(), request.args.get("q", ""))
