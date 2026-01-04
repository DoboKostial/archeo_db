# app/routes/photograms.py
from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
import json
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
from app.utils.media_map import LINK_TABLES_SJ, LINK_TABLES_POLYGON, LINK_TABLES_SECTION  # reuse mapping

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

# hard-coded choices (app-level validation)
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


def _read_range_pairs(form: Any, from_name: str, to_name: str) -> list[tuple[int, int]]:
    """
    Reads multiple FROM/TO pairs (arrays) from form.
    Example names: geopt_from_0[] , geopt_to_0[]
    """
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

    page = _as_int(request.args.get("page")) or 1
    per_page = _as_int(request.args.get("per_page")) or 24
    offset = (page - 1) * per_page

    with get_terrain_connection(selected_db) as conn:
        with conn.cursor() as cur:
            # stats
            cur.execute(photograms_stats_sql())
            total_cnt, total_bytes, orphan_cnt = cur.fetchone()

            cur.execute(photograms_stats_by_type_sql())
            by_type = cur.fetchall()

            # page rows
            cur.execute(
                select_photograms_page_sql(orphan_only=orphan_only, has_typ=bool(f_typ), has_sketch=bool(f_sketch),
                                           has_pf=bool(f_photo_from), has_pt=bool(f_photo_to)),
                {
                    "typ_list": f_typ,
                    "ref_sketch": f_sketch,
                    "ref_photo_from": f_photo_from,
                    "ref_photo_to": f_photo_to,
                    "limit": per_page,
                    "offset": offset,
                },
            )
            rows = cur.fetchall()

    # convert tuples -> dicts so Jinja can use g.id_photogram, g.link_counts.sj etc.
    photograms = []
    for r in rows:
        # r = (id_photogram, photogram_typ, ref_sketch, notes, ref_photo_from, ref_photo_to, link_counts_json)
        lc = r[6]
        if isinstance(lc, str):
            try:
                lc = json.loads(lc)
            except Exception:
                lc = {}
        if lc is None:
            lc = {}

        photograms.append({
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
        "photogram_typ": f_typ,
        "ref_sketch": f_sketch,
        "ref_photo_from": f_photo_from,
        "ref_photo_to": f_photo_to,
        "orphan_only": orphan_only,
    }

    return render_template(
        "photograms.html",
        selected_db=selected_db,
        photograms=photograms,
        page=page,
        per_page=per_page,
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

    # blocks: index list (hidden idx fields)
    idx_list = request.form.getlist("idx")
    if not idx_list:
        flash("No photogram blocks provided.", "warning")
        return redirect(url_for("photograms.photograms"))

    ok, failed = 0, []

    for idx in idx_list:
        idx = str(idx).strip()

        # per-block fields
        file_field = f"file_{idx}"
        typ = (request.form.get(f"photogram_typ_{idx}") or "").strip()
        notes = (request.form.get(f"notes_{idx}") or "").strip() or None

        ref_sketch = (request.form.get(f"ref_sketch_{idx}") or "").strip() or None
        ref_photo_from = (request.form.get(f"ref_photo_from_{idx}") or "").strip() or None
        ref_photo_to = (request.form.get(f"ref_photo_to_{idx}") or "").strip() or None

        # links via hidden inputs (search-select)
        sj_ids = request.form.getlist(f"ref_sj_{idx}")
        polygons = request.form.getlist(f"ref_polygon_{idx}")
        sections = request.form.getlist(f"ref_section_{idx}")

        # geopts ranges (arrays)
        try:
            ranges = _read_range_pairs(request.form, f"geopt_from_{idx}[]", f"geopt_to_{idx}[]")
        except Exception as e:
            failed.append(f"Block {idx}: {e}")
            continue

        # validate typ
        if typ not in PHOTOGRAM_TYP_CHOICES:
            failed.append(f"Block {idx}: Invalid photogram_typ.")
            continue

        f = request.files.get(file_field)
        if not f or not f.filename:
            failed.append(f"Block {idx}: Missing file.")
            continue

        tmp_path = None
        final_path = None
        thumb_path = None

        try:
            # A) temp store
            tmp_path, _tmp_size = save_to_uploads(Config.UPLOAD_FOLDER, f)

            # B) pk + extension validate
            pk_name = make_pk(selected_db, f.filename)
            validate_pk(pk_name)
            ext = pk_name.rsplit(".", 1)[-1].lower()
            validate_extension(ext, Config.ALLOWED_EXTENSIONS)

            # C) final paths + collision
            media_dir = Config.MEDIA_DIRS["photograms"]
            final_path, thumb_path = final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)
            if os.path.exists(final_path):
                raise ValueError(f"File already exists: {pk_name}")

            # D) move into place then MIME validate + checksum
            move_into_place(tmp_path, final_path)
            tmp_path = None

            mime = detect_mime(final_path)
            validate_mime(mime, Config.ALLOWED_MIME)
            checksum = sha256_file(final_path)

            # E) DB transaction (one per photogram) + thumbnail best-effort inside try
            with get_terrain_connection(selected_db) as conn:
                with conn.cursor() as cur:
                    # reject duplicate content (checksum)
                    cur.execute(photogram_checksum_exists_sql(), (checksum,))
                    if cur.fetchone():
                        raise ValueError("Duplicate content (checksum already exists).")

                    # insert photogram row
                    cur.execute(
                        insert_photogram_sql(),
                        (
                            pk_name,
                            typ,
                            ref_sketch,
                            notes,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                            ref_photo_from,
                            ref_photo_to,
                        ),
                    )

                    # link tables (optional; multiple)
                    for sj in sj_ids:
                        sj_i = _as_int(sj)
                        if sj_i is None:
                            continue
                        cur.execute(link_photogram_sj_sql(), (pk_name, sj_i))

                    for p in polygons:
                        p = (p or "").strip()
                        if not p:
                            continue
                        cur.execute(link_photogram_polygon_sql(), (p, pk_name))

                    for s in sections:
                        s_i = _as_int(s)
                        if s_i is None:
                            continue
                        cur.execute(link_photogram_section_sql(), (s_i, pk_name))

                    # ranges
                    for a, b in ranges:
                        cur.execute(insert_photogram_geopts_range_sql(), (pk_name, a, b))

                conn.commit()

            # thumbnail after DB success; if thumb fails, do NOT fail upload
            try:
                make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
            except Exception:
                pass

            ok += 1

        except Exception as e:
            failed.append(f"{f.filename}: {e}")
            logger.warning(f"[{selected_db}] photogram upload failed {f.filename}: {e}")

            # cleanup FS on failure
            try:
                if final_path:
                    delete_media_files(final_path, thumb_path)
            except Exception:
                pass

        finally:
            if tmp_path:
                try:
                    cleanup_upload(tmp_path)
                except Exception:
                    pass

    if failed:
        flash(
            f"Uploaded {ok} photogram(s), {len(failed)} failed: " + "; ".join(failed),
            "warning" if ok else "danger",
        )
    else:
        flash(f"Uploaded {ok} photogram(s).", "success")

    return redirect(url_for("photograms.photograms"))


# ---------------------------------------
# BULK (links only: SU / polygon / section)
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
            for pid in ids:
                pid = (pid or "").strip()
                if not pid:
                    continue

                # SU
                for sj in sj_ids:
                    sj_i = _as_int(sj)
                    if sj_i is None:
                        continue
                    if action == "add_links":
                        cur.execute(link_photogram_sj_sql(), (pid, sj_i))
                    else:
                        cur.execute(unlink_photogram_sj_sql(), (pid, sj_i))

                # polygon
                for p in polygons:
                    p = (p or "").strip()
                    if not p:
                        continue
                    if action == "add_links":
                        cur.execute(link_photogram_polygon_sql(), (p, pid))
                    else:
                        cur.execute(unlink_photogram_polygon_sql(), (p, pid))

                # section
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
            links = cur.fetchone()  # arrays

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

    # replacement file optional
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

                # if replace: store new file first to temp final, validate, checksum, then swap after commit
                new_mime = None
                new_size = None
                new_checksum = None

                if replace:
                    # temp store
                    tmp_path, _ = save_to_uploads(Config.UPLOAD_FOLDER, repl)

                    # validate name of upload file only by extension/mime; photogram ID stays same
                    ext = repl.filename.rsplit(".", 1)[-1].lower() if "." in repl.filename else ""
                    validate_extension(ext, Config.ALLOWED_EXTENSIONS)

                    # move temp upload to a temp-final path in same folder
                    tmp_final_path = final_path + ".tmp_replace"
                    tmp_thumb_path = thumb_path + ".tmp_replace"

                    # ensure no leftovers
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

                    # reject duplicate content
                    cur.execute(photogram_checksum_exists_sql(), (new_checksum,))
                    if cur.fetchone():
                        raise ValueError("Duplicate content (checksum already exists).")

                    # generate thumb for tmp file (best-effort)
                    try:
                        make_thumbnail(tmp_final_path, tmp_thumb_path, Config.THUMB_MAX_SIDE)
                    except Exception:
                        tmp_thumb_path = None

                # update main row (if not replace, keep existing file fields)
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

                # reset links
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

        # swap files after DB commit
        if replace and tmp_final_path:
            # replace original
            try:
                os.replace(tmp_final_path, final_path)
            finally:
                tmp_final_path = None

            # replace thumb if we created it
            if tmp_thumb_path and os.path.exists(tmp_thumb_path):
                try:
                    os.replace(tmp_thumb_path, thumb_path)
                finally:
                    tmp_thumb_path = None
            else:
                # regenerate thumb best-effort
                try:
                    make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
                except Exception:
                    pass

        flash("Photogram updated.", "success")

    except Exception as e:
        logger.warning(f"[{selected_db}] photogram edit failed {pid}: {e}")
        flash(f"Edit failed: {e}", "danger")

        # cleanup temp replace files
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

        # delete files
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
# FILE SERVE (same pattern as photos)
# ---------------------------------------
@photograms_bp.get("/photograms/file/<path:id_photogram>")
@require_selected_db
def serve_photogram_file(id_photogram: str):
    # implement same as photos.serve_photo_file (send_from_directory with safe path)
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
# SEARCH endpoints for SearchSelect
# returns {results:[{id,text}], page, ...}
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
