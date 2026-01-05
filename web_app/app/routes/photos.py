# app/routes/photos.py
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from flask import (
    Blueprint, flash, jsonify, redirect, render_template, request, send_file, session, url_for
)
from psycopg2.extras import Json

from config import Config
from app.logger import logger
from app.database import get_terrain_connection

# SQLs imports from queries
from app.queries import (
    insert_photo_sql,
    photo_exists_sql,
    checksum_exists_sql,
    update_photo_sql,
    delete_photo_sql,
    get_photo_sql,
    list_photos_sql,
    count_photos_sql,
    stats_basic_sql,
    stats_by_type_sql,
    search_authors_sql,
    search_sj_sql,
    search_polygons_sql,
    search_sections_sql,
    search_finds_sql,
    search_samples_sql,
)

from app.utils.decorators import require_selected_db

# reuse your existing helpers (as in polygons upload)
from app.utils import storage
from app.utils import validate_mime, validate_extension, sha256_file
from app.utils.images import make_thumbnail, extract_exif, detect_mime

# media_map (whitelisted mapping for link tables/columns)
from app.utils.media_map import (
    LINK_TABLES_SJ,
    LINK_TABLES_POLYGON,
    LINK_TABLES_SECTION,
    LINK_TABLES_FINDS,
    LINK_TABLES_SAMPLES,
)

photos_bp = Blueprint("photos", __name__)

PHOTO_MEDIA_TYPE = "photos"
PHOTO_TYP_CHOICES = ["vertical", "horizontal", "skew", "general", "detail"]


# -------------------------
# media_map helpers (photos only)
# -------------------------

def _link_maps() -> Dict[str, Dict[str, str]]:
    """
    kind -> {table, fk_media, fk_entity}
    """

    def _extract_fk_entity(m: Dict[str, str]) -> str:
        for k, v in m.items():
            if k.startswith("fk_") and k != "fk_media":
                return v
        raise ValueError(f"Invalid link map (missing fk entity): {m}")

    maps: Dict[str, Dict[str, str]] = {}

    m = LINK_TABLES_SJ[PHOTO_MEDIA_TYPE]
    maps["sj"] = {"table": m["table"], "fk_media": m["fk_media"], "fk_entity": _extract_fk_entity(m)}

    m = LINK_TABLES_POLYGON[PHOTO_MEDIA_TYPE]
    maps["polygon"] = {"table": m["table"], "fk_media": m["fk_media"], "fk_entity": _extract_fk_entity(m)}

    m = LINK_TABLES_SECTION[PHOTO_MEDIA_TYPE]
    maps["section"] = {"table": m["table"], "fk_media": m["fk_media"], "fk_entity": _extract_fk_entity(m)}

    m = LINK_TABLES_FINDS[PHOTO_MEDIA_TYPE]
    maps["find"] = {"table": m["table"], "fk_media": m["fk_media"], "fk_entity": _extract_fk_entity(m)}

    m = LINK_TABLES_SAMPLES[PHOTO_MEDIA_TYPE]
    maps["sample"] = {"table": m["table"], "fk_media": m["fk_media"], "fk_entity": _extract_fk_entity(m)}

    return maps


LINKS = _link_maps()


def _sql_link_select(kind: str) -> str:
    m = LINKS[kind]
    return f"SELECT {m['fk_entity']} FROM {m['table']} WHERE {m['fk_media']}=%s ORDER BY {m['fk_entity']};"


def _sql_link_delete_all(kind: str) -> str:
    m = LINKS[kind]
    return f"DELETE FROM {m['table']} WHERE {m['fk_media']}=%s;"


def _sql_link_insert(kind: str) -> str:
    m = LINKS[kind]
    return f"INSERT INTO {m['table']} ({m['fk_media']}, {m['fk_entity']}) VALUES (%s, %s);"


def _sql_link_delete_any(kind: str) -> str:
    m = LINKS[kind]
    return f"DELETE FROM {m['table']} WHERE {m['fk_media']}=%s AND {m['fk_entity']} = ANY(%s);"


def _sql_link_exists(kind: str) -> str:
    m = LINKS[kind]
    return f"""
        EXISTS (
          SELECT 1 FROM {m['table']} l
          WHERE l.{m['fk_media']} = p.id_photo
            AND l.{m['fk_entity']} = ANY(%s)
        )
    """


def _sql_link_not_exists(kind: str) -> str:
    m = LINKS[kind]
    return f"NOT EXISTS (SELECT 1 FROM {m['table']} l WHERE l.{m['fk_media']} = p.id_photo)"


def _sql_link_count(kind: str) -> str:
    m = LINKS[kind]
    return f"SELECT COUNT(*) FROM {m['table']} WHERE {m['fk_media']}=%s;"


# -------------------------
# FS helpers
# -------------------------

def _photo_dir(selected_db: str) -> str:
    return os.path.join(Config.DATA_DIR, selected_db, Config.MEDIA_DIRS[PHOTO_MEDIA_TYPE])


def _photo_thumb_dir(selected_db: str) -> str:
    return os.path.join(_photo_dir(selected_db), "thumbs")


def _final_paths(selected_db: str, id_photo: str) -> Tuple[str, str]:
    final_path = os.path.join(_photo_dir(selected_db), id_photo)
    thumb_path = os.path.join(_photo_thumb_dir(selected_db), id_photo)
    return final_path, thumb_path


# -------------------------
# misc helpers
# -------------------------

def _validate_photo_typ(photo_typ: str) -> None:
    if photo_typ not in PHOTO_TYP_CHOICES:
        raise ValueError(f"Invalid photo type: {photo_typ}")


def _parse_int_list(values: List[str]) -> List[int]:
    out: List[int] = []
    for v in values:
        v = (v or "").strip()
        if not v:
            continue
        out.append(int(v))
    return out


def _parse_text_list(values: List[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        v = (v or "").strip()
        if v:
            out.append(v)
    return out


def _human_bytes(num: int) -> str:
    step = 1024.0
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(num)
    for u in units:
        if x < step:
            return f"{x:.1f} {u}"
        x /= step
    return f"{x:.1f} PB"


def _select2_payload(items: List[Tuple[str, str]], more: bool = False):
    return {"results": [{"id": i, "text": t} for i, t in items], "pagination": {"more": more}}


def _paginate(limit_default: int = 20) -> Tuple[str, int, int]:
    qtxt = (request.args.get("q") or "").strip()
    page = int(request.args.get("page") or 1)
    limit = int(request.args.get("limit") or limit_default)
    if limit < 1:
        limit = limit_default
    if limit > 50:
        limit = 50
    if page < 1:
        page = 1
    offset = (page - 1) * limit
    return qtxt, limit, offset


# -------------------------
# main page
# -------------------------

@photos_bp.get("/photos")
@require_selected_db
def photos():
    selected_db = session["selected_db"]

    photo_typs = _parse_text_list(request.args.getlist("photo_typ"))
    authors = _parse_text_list(request.args.getlist("author"))
    datum_from = (request.args.get("datum_from") or "").strip() or None
    datum_to = (request.args.get("datum_to") or "").strip() or None

    sj_ids = _parse_int_list(request.args.getlist("sj_ids"))
    polygon_names = _parse_text_list(request.args.getlist("polygon_names"))
    section_ids = _parse_int_list(request.args.getlist("section_ids"))
    find_ids = _parse_int_list(request.args.getlist("find_ids"))
    sample_ids = _parse_int_list(request.args.getlist("sample_ids"))

    has_gps = (request.args.get("has_gps") or "").strip() == "1"
    orphan_only = (request.args.get("orphan_only") or "").strip() == "1"

    page = int(request.args.get("page") or 1)
    per_page = int(request.args.get("per_page") or 20)
    if per_page > 50:
        per_page = 50
    if per_page < 1:
        per_page = 20
    if page < 1:
        page = 1
    offset = (page - 1) * per_page

    where_parts: List[str] = []
    params: List[Any] = []

    if photo_typs:
        where_parts.append("p.photo_typ = ANY(%s)")
        params.append(photo_typs)

    if authors:
        where_parts.append("p.author = ANY(%s)")
        params.append(authors)

    if datum_from:
        where_parts.append("p.datum >= %s")
        params.append(datum_from)

    if datum_to:
        where_parts.append("p.datum <= %s")
        params.append(datum_to)

    if has_gps:
        where_parts.append("(p.gps_lat IS NOT NULL AND p.gps_lon IS NOT NULL)")

    if sj_ids:
        where_parts.append(_sql_link_exists("sj"))
        params.append(sj_ids)

    if polygon_names:
        where_parts.append(_sql_link_exists("polygon"))
        params.append(polygon_names)

    if section_ids:
        where_parts.append(_sql_link_exists("section"))
        params.append(section_ids)

    if find_ids:
        where_parts.append(_sql_link_exists("find"))
        params.append(find_ids)

    if sample_ids:
        where_parts.append(_sql_link_exists("sample"))
        params.append(sample_ids)

    if orphan_only:
        where_parts.append(" AND ".join([
            _sql_link_not_exists("sj"),
            _sql_link_not_exists("polygon"),
            _sql_link_not_exists("section"),
            _sql_link_not_exists("find"),
            _sql_link_not_exists("sample"),
        ]))

    where_sql = ""
    if where_parts:
        where_sql = "WHERE " + " AND ".join([f"({p.strip()})" for p in where_parts])

    order_sql = "ORDER BY p.datum DESC NULLS LAST, p.id_photo DESC"
    limit_sql = "LIMIT %s OFFSET %s"

    list_sql = list_photos_sql(where_sql=where_sql, order_sql=order_sql, limit_sql=limit_sql)
    count_sql = count_photos_sql(where_sql=where_sql)

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(stats_basic_sql())
            total_cnt, total_bytes = cur.fetchone()

            cur.execute(stats_by_type_sql())
            by_type = cur.fetchall()

            orphans_sql = f"""
                SELECT COUNT(*)::bigint
                FROM tab_photos p
                WHERE {_sql_link_not_exists("sj")}
                  AND {_sql_link_not_exists("polygon")}
                  AND {_sql_link_not_exists("section")}
                  AND {_sql_link_not_exists("find")}
                  AND {_sql_link_not_exists("sample")};
            """
            cur.execute(orphans_sql)
            orphan_cnt = cur.fetchone()[0]

            cur.execute(count_sql, params)
            filtered_cnt = cur.fetchone()[0]

            cur.execute(list_sql, params + [per_page, offset])
            rows = cur.fetchall()

            photos_data = []
            for r in rows:
                id_photo = r[0]
                counts = {}
                for kind in ("sj", "polygon", "section", "find", "sample"):
                    cur.execute(_sql_link_count(kind), (id_photo,))
                    counts[kind] = cur.fetchone()[0]

                photos_data.append({
                    "id_photo": r[0],
                    "photo_typ": r[1],
                    "datum": r[2],
                    "author": r[3],
                    "notes": r[4],
                    "mime_type": r[5],
                    "file_size": r[6],
                    "checksum_sha256": r[7],
                    "shoot_datetime": r[8],
                    "gps_lat": r[9],
                    "gps_lon": r[10],
                    "gps_alt": r[11],
                    "link_counts": counts,
                })

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return render_template(
        "photos.html",
        selected_db=selected_db,
        photo_typ_choices=PHOTO_TYP_CHOICES,
        photos=photos_data,
        page=page,
        per_page=per_page,
        filtered_cnt=filtered_cnt,
        stats={
            "total_cnt": total_cnt,
            "total_bytes": total_bytes,
            "total_bytes_h": _human_bytes(int(total_bytes)),
            "by_type": by_type,
            "orphan_cnt": orphan_cnt,
        },
        filters={
            "photo_typ": photo_typs,
            "author": authors,
            "datum_from": datum_from,
            "datum_to": datum_to,
            "sj_ids": sj_ids,
            "polygon_names": polygon_names,
            "section_ids": section_ids,
            "find_ids": find_ids,
            "sample_ids": sample_ids,
            "has_gps": has_gps,
            "orphan_only": orphan_only,
        }
    )


# -------------------------
# Upload (atomic batch DB+FS+thumb)
# -------------------------

@photos_bp.post("/photos/upload")
@require_selected_db
def upload_photos():
    selected_db = session["selected_db"]

    # --- shared metadata (applies to all uploaded files) ---
    photo_typ = (request.form.get("photo_typ") or "").strip()
    datum = (request.form.get("datum") or "").strip()
    author = (request.form.get("author") or "").strip()
    notes = (request.form.get("notes") or "").strip() or None

    _validate_photo_typ(photo_typ)
    if not datum:
        flash("Date is required.", "danger")
        return redirect(url_for("photos.photos"))
    if not author:
        flash("Author is required.", "danger")
        return redirect(url_for("photos.photos"))

    # --- shared links (optional, multi) ---
    sj_ids = _parse_int_list(request.form.getlist("ref_sj"))
    polygon_names = _parse_text_list(request.form.getlist("ref_polygon"))
    section_ids = _parse_int_list(request.form.getlist("ref_section"))
    find_ids = _parse_int_list(request.form.getlist("ref_find"))
    sample_ids = _parse_int_list(request.form.getlist("ref_sample"))

    # --- files: multiple inputs with same name="files" ---
    files = request.files.getlist("files")
    # filter out empty inputs
    files = [f for f in files if f and getattr(f, "filename", None)]
    if not files:
        flash("No files provided.", "warning")
        return redirect(url_for("photos.photos"))

    staged_paths: List[str] = []
    moved_files: List[str] = []          # final_paths that were moved into place
    thumbs_planned: List[Tuple[str, str]] = []  # (final_path, thumb_path) for post-commit thumb generation
    blocks: List[Dict[str, Any]] = []

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False

    try:
        cur = conn.cursor()
        try:
            # ------------------------------------------------------------
            # A) stage + validate each file (fail-fast)
            # ------------------------------------------------------------
            seen_pk: set[str] = set()
            seen_checksum: set[str] = set()

            for f in files:
                # pk + ext validation
                pk_name = storage.make_pk(selected_db, f.filename)
                storage.validate_pk(pk_name)

                if pk_name in seen_pk:
                    raise ValueError(f"Duplicate filename in this upload: {pk_name}")
                seen_pk.add(pk_name)

                ext = pk_name.rsplit(".", 1)[-1].lower()
                validate_extension(ext, Config.ALLOWED_EXTENSIONS)

                final_path, thumb_path = _final_paths(selected_db, pk_name)

                # collisions (FS + DB)
                if os.path.exists(final_path):
                    raise ValueError(f"File already exists on FS: {pk_name}")
                cur.execute(photo_exists_sql(), (pk_name,))
                if cur.fetchone():
                    raise ValueError(f"Photo already exists in DB: {pk_name}")

                # stage to uploads
                tmp_path, _ = storage.save_to_uploads(Config.UPLOAD_FOLDER, f)
                staged_paths.append(tmp_path)

                # validate content by MIME + checksum (on staged file)
                mime = detect_mime(tmp_path)
                validate_mime(mime, Config.ALLOWED_MIME)

                checksum = sha256_file(tmp_path)
                if checksum in seen_checksum:
                    raise ValueError("Duplicate content among selected files (same checksum).")
                seen_checksum.add(checksum)

                cur.execute(checksum_exists_sql(), (checksum,))
                if cur.fetchone():
                    raise ValueError(f"Duplicate content (checksum already exists) for file: {pk_name}")

                blocks.append({
                    "pk_name": pk_name,
                    "tmp_path": tmp_path,
                    "final_path": final_path,
                    "thumb_path": thumb_path,
                    "mime": mime,
                    "checksum": checksum,
                })

            # ------------------------------------------------------------
            # B) existence checks for references (shared, fail-fast)
            # ------------------------------------------------------------
            def _assert_exists(sql: str, value: Any, err: str):
                cur.execute(sql, (value,))
                if not cur.fetchone():
                    raise ValueError(err)

            _assert_exists(
                "SELECT 1 FROM gloss_personalia WHERE mail=%s LIMIT 1;",
                author,
                f"Author not found: {author}"
            )

            for sj in sj_ids:
                _assert_exists("SELECT 1 FROM tab_sj WHERE id_sj=%s LIMIT 1;", sj, f"SU not found: {sj}")
            for poly in polygon_names:
                _assert_exists("SELECT 1 FROM tab_polygons WHERE polygon_name=%s LIMIT 1;", poly, f"Polygon not found: {poly}")
            for sec in section_ids:
                _assert_exists("SELECT 1 FROM tab_section WHERE id_section=%s LIMIT 1;", sec, f"Section not found: {sec}")
            for fid in find_ids:
                _assert_exists("SELECT 1 FROM tab_finds WHERE id_find=%s LIMIT 1;", fid, f"Find not found: {fid}")
            for sid in sample_ids:
                _assert_exists("SELECT 1 FROM tab_samples WHERE id_sample=%s LIMIT 1;", sid, f"Sample not found: {sid}")

            # ------------------------------------------------------------
            # C) move into place + DB inserts + links (single DB transaction)
            #    - thumbnails are NOT created here (only after commit)
            # ------------------------------------------------------------
            for b in blocks:
                storage.move_into_place(b["tmp_path"], b["final_path"])
                moved_files.append(b["final_path"])
                thumbs_planned.append((b["final_path"], b["thumb_path"]))

                shoot_dt = gps_lat = gps_lon = gps_alt = None
                exif_json = {}

                # EXIF only for JPEG/TIFF
                if b["mime"] in ("image/jpeg", "image/tiff"):
                    sdt, la, lo, al, exif = extract_exif(b["final_path"])
                    shoot_dt, gps_lat, gps_lon, gps_alt, exif_json = sdt, la, lo, al, exif

                cur.execute(
                    insert_photo_sql(),
                    (
                        b["pk_name"],
                        photo_typ,
                        datum,
                        author,
                        notes,
                        b["mime"],
                        os.path.getsize(b["final_path"]),
                        b["checksum"],
                        shoot_dt, gps_lat, gps_lon, gps_alt,
                        Json(exif_json),
                    )
                )

                pid = b["pk_name"]
                for sj in sj_ids:
                    cur.execute(_sql_link_insert("sj"), (pid, sj))
                for poly in polygon_names:
                    cur.execute(_sql_link_insert("polygon"), (pid, poly))
                for sec in section_ids:
                    cur.execute(_sql_link_insert("section"), (pid, sec))
                for fid in find_ids:
                    cur.execute(_sql_link_insert("find"), (pid, fid))
                for sid in sample_ids:
                    cur.execute(_sql_link_insert("sample"), (pid, sid))

            # commit DB transaction first
            conn.commit()

            # ------------------------------------------------------------
            # D) thumbnails AFTER COMMIT (best effort; DB already committed)
            # ------------------------------------------------------------
            thumb_ok = 0
            thumb_fail = 0
            for fp, tp in thumbs_planned:
                try:
                    make_thumbnail(fp, tp, Config.THUMB_MAX_SIDE)
                    thumb_ok += 1
                except Exception:
                    thumb_fail += 1
                    logger.warning(f"[{selected_db}] thumbnail failed for: {os.path.basename(fp)}")

            if thumb_fail:
                flash(f"Uploaded {len(blocks)} photo(s). Thumbnails: {thumb_ok} ok, {thumb_fail} failed.", "warning")
            else:
                flash(f"Uploaded {len(blocks)} photo(s).", "success")

            logger.info(f"[{selected_db}] photos upload ok: count={len(blocks)} thumbs_ok={thumb_ok} thumbs_fail={thumb_fail}")

        except Exception as e:
            # rollback DB
            try:
                conn.rollback()
            except Exception:
                pass

            # cleanup moved finals (no thumbnails should exist yet, but delete_media_files is safe)
            for b in blocks:
                try:
                    storage.delete_media_files(b.get("final_path"), b.get("thumb_path"))
                except Exception:
                    pass

            # cleanup staged uploads
            for sp in staged_paths:
                try:
                    storage.cleanup_upload(sp)
                except Exception:
                    pass

            logger.warning(f"[{selected_db}] photos upload failed: {e}")
            flash(f"Upload failed: {e}", "danger")
            return redirect(url_for("photos.photos"))

        finally:
            try:
                cur.close()
            except Exception:
                pass

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("photos.photos"))



# -------------------------
# Serve file / thumb
# -------------------------

@photos_bp.get("/photos/file/<path:id_photo>")
@require_selected_db
def serve_photo_file(id_photo: str):
    selected_db = session["selected_db"]
    final_path, _ = _final_paths(selected_db, id_photo)

    if not os.path.exists(final_path):
        flash("File not found on FS.", "danger")
        return redirect(url_for("photos.photos"))
    return send_file(final_path, as_attachment=False)


@photos_bp.get("/photos/thumb/<path:id_photo>")
@require_selected_db
def serve_photo_thumb(id_photo: str):
    selected_db = session["selected_db"]
    _, thumb_path = _final_paths(selected_db, id_photo)

    if not os.path.exists(thumb_path):
        return ("", 404)
    return send_file(thumb_path, as_attachment=False)


# -------------------------
# Detail API (edit modal preload)
# -------------------------

@photos_bp.get("/photos/api/detail/<path:id_photo>")
@require_selected_db
def api_photo_detail(id_photo: str):
    selected_db = session["selected_db"]

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(get_photo_sql(), (id_photo,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "not_found"}), 404

            links: Dict[str, List[Any]] = {}
            for kind in ("sj", "polygon", "section", "find", "sample"):
                cur.execute(_sql_link_select(kind), (id_photo,))
                links[kind] = [r[0] for r in cur.fetchall()]

        data = {
            "id_photo": row[0],
            "photo_typ": row[1],
            "datum": str(row[2]) if row[2] else "",
            "author": row[3],
            "notes": row[4] or "",
            "links": {
                "sj_ids": links["sj"],
                "polygon_names": links["polygon"],
                "section_ids": links["section"],
                "find_ids": links["find"],
                "sample_ids": links["sample"],
            }
        }
        return jsonify(data)

    finally:
        try:
            conn.close()
        except Exception:
            pass


# -------------------------
# Edit (replace links)
# -------------------------

@photos_bp.post("/photos/edit/<path:id_photo>")
@require_selected_db
def edit_photo(id_photo: str):
    selected_db = session["selected_db"]

    photo_typ = (request.form.get("photo_typ") or "").strip()
    datum = (request.form.get("datum") or "").strip()
    author = (request.form.get("author") or "").strip()
    notes = (request.form.get("notes") or "").strip() or None

    try:
        _validate_photo_typ(photo_typ)
        if not datum:
            raise ValueError("Date is required.")
        if not author:
            raise ValueError("Author is required.")
    except Exception as e:
        flash(f"Edit failed: {e}", "danger")
        return redirect(url_for("photos.photos"))

    sj_ids = _parse_int_list(request.form.getlist("ref_sj"))
    polygon_names = _parse_text_list(request.form.getlist("ref_polygon"))
    section_ids = _parse_int_list(request.form.getlist("ref_section"))
    find_ids = _parse_int_list(request.form.getlist("ref_find"))
    sample_ids = _parse_int_list(request.form.getlist("ref_sample"))

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(photo_exists_sql(), (id_photo,))
            if not cur.fetchone():
                raise ValueError("Photo not found.")

            cur.execute(update_photo_sql(), (photo_typ, datum, author, notes, id_photo))

            for kind in ("sj", "polygon", "section", "find", "sample"):
                cur.execute(_sql_link_delete_all(kind), (id_photo,))

            for sj in sj_ids:
                cur.execute(_sql_link_insert("sj"), (id_photo, sj))
            for poly in polygon_names:
                cur.execute(_sql_link_insert("polygon"), (id_photo, poly))
            for sec in section_ids:
                cur.execute(_sql_link_insert("section"), (id_photo, sec))
            for fid in find_ids:
                cur.execute(_sql_link_insert("find"), (id_photo, fid))
            for sid in sample_ids:
                cur.execute(_sql_link_insert("sample"), (id_photo, sid))

        conn.commit()
        flash("Photo updated.", "success")
        logger.info(f"[{selected_db}] photo edited: {id_photo}")

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f"Edit failed: {e}", "danger")
        logger.warning(f"[{selected_db}] photo edit failed {id_photo}: {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("photos.photos"))


# -------------------------
# Delete (DB first, then FS)
# -------------------------

@photos_bp.post("/photos/delete/<path:id_photo>")
@require_selected_db
def delete_photo(id_photo: str):
    selected_db = session["selected_db"]
    final_path, thumb_path = _final_paths(selected_db, id_photo)

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(photo_exists_sql(), (id_photo,))
            if not cur.fetchone():
                raise ValueError("Photo not found in DB.")

            cur.execute(delete_photo_sql(), (id_photo,))

        conn.commit()

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f"Delete failed: {e}", "danger")
        logger.warning(f"[{selected_db}] photo delete failed (DB) {id_photo}: {e}")
        return redirect(url_for("photos.photos"))

    finally:
        try:
            conn.close()
        except Exception:
            pass

    try:
        storage.delete_media_files(final_path, thumb_path)
        flash("Photo deleted.", "success")
        logger.info(f"[{selected_db}] photo deleted: {id_photo}")
    except Exception as e:
        flash("Photo deleted from DB, but FS delete failed (see logs).", "warning")
        logger.warning(f"[{selected_db}] photo deleted DB ok, FS delete failed {id_photo}: {e}")

    return redirect(url_for("photos.photos"))


# -------------------------
# Bulk actions (add/remove links)
# -------------------------

@photos_bp.post("/photos/bulk")
@require_selected_db
def bulk_photos():
    selected_db = session["selected_db"]

    photo_ids = _parse_text_list(request.form.getlist("photo_ids"))
    action = (request.form.get("action") or "").strip()

    if not photo_ids:
        flash("No photos selected.", "warning")
        return redirect(url_for("photos.photos"))
    if action not in ("add_links", "remove_links"):
        flash("Invalid bulk action.", "danger")
        return redirect(url_for("photos.photos"))

    sj_ids = _parse_int_list(request.form.getlist("ref_sj"))
    polygon_names = _parse_text_list(request.form.getlist("ref_polygon"))
    section_ids = _parse_int_list(request.form.getlist("ref_section"))
    find_ids = _parse_int_list(request.form.getlist("ref_find"))
    sample_ids = _parse_int_list(request.form.getlist("ref_sample"))

    if not (sj_ids or polygon_names or section_ids or find_ids or sample_ids):
        flash("No links selected for bulk operation.", "warning")
        return redirect(url_for("photos.photos"))

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for pid in photo_ids:
                cur.execute(photo_exists_sql(), (pid,))
                if not cur.fetchone():
                    raise ValueError(f"Photo not found: {pid}")

            if action == "add_links":
                for pid in photo_ids:
                    for sj in sj_ids:
                        cur.execute(_sql_link_insert("sj"), (pid, sj))
                    for poly in polygon_names:
                        cur.execute(_sql_link_insert("polygon"), (pid, poly))
                    for sec in section_ids:
                        cur.execute(_sql_link_insert("section"), (pid, sec))
                    for fid in find_ids:
                        cur.execute(_sql_link_insert("find"), (pid, fid))
                    for sid in sample_ids:
                        cur.execute(_sql_link_insert("sample"), (pid, sid))

            else:
                for pid in photo_ids:
                    if sj_ids:
                        cur.execute(_sql_link_delete_any("sj"), (pid, sj_ids))
                    if polygon_names:
                        cur.execute(_sql_link_delete_any("polygon"), (pid, polygon_names))
                    if section_ids:
                        cur.execute(_sql_link_delete_any("section"), (pid, section_ids))
                    if find_ids:
                        cur.execute(_sql_link_delete_any("find"), (pid, find_ids))
                    if sample_ids:
                        cur.execute(_sql_link_delete_any("sample"), (pid, sample_ids))

        conn.commit()
        flash("Bulk operation completed.", "success")
        logger.info(f"[{selected_db}] photos bulk {action}: photos={len(photo_ids)}")

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f"Bulk failed: {e}", "danger")
        logger.warning(f"[{selected_db}] photos bulk failed: {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("photos.photos"))


# -------------------------
# AJAX search endpoints (select2)
# -------------------------

@photos_bp.get("/api/search/authors")
@require_selected_db
def api_search_authors():
    selected_db = session["selected_db"]
    qtxt, limit, offset = _paginate()
    like = f"%{qtxt}%"

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(search_authors_sql(), (like, limit, offset))
            rows = cur.fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items = [(r[0], r[0]) for r in rows]
    return jsonify(_select2_payload(items, more=(len(items) == limit)))


@photos_bp.get("/api/search/sj")
@require_selected_db
def api_search_sj():
    selected_db = session["selected_db"]
    qtxt, limit, offset = _paginate()
    like = f"%{qtxt}%"

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(search_sj_sql(), (like, limit, offset))
            rows = cur.fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items = [(str(r[0]), f"SU {r[0]}") for r in rows]
    return jsonify(_select2_payload(items, more=(len(items) == limit)))


@photos_bp.get("/api/search/polygons")
@require_selected_db
def api_search_polygons():
    selected_db = session["selected_db"]
    qtxt, limit, offset = _paginate()
    like = f"%{qtxt}%"

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(search_polygons_sql(), (like, limit, offset))
            rows = cur.fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items = [(r[0], r[0]) for r in rows]
    return jsonify(_select2_payload(items, more=(len(items) == limit)))


@photos_bp.get("/api/search/sections")
@require_selected_db
def api_search_sections():
    selected_db = session["selected_db"]
    qtxt, limit, offset = _paginate()
    like = f"%{qtxt}%"

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(search_sections_sql(), (like, limit, offset))
            rows = cur.fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items = [(str(r[0]), f"Section {r[0]}") for r in rows]
    return jsonify(_select2_payload(items, more=(len(items) == limit)))


@photos_bp.get("/api/search/finds")
@require_selected_db
def api_search_finds():
    selected_db = session["selected_db"]
    qtxt, limit, offset = _paginate()
    like = f"%{qtxt}%"

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(search_finds_sql(), (like, limit, offset))
            rows = cur.fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items = [(str(r[0]), f"Find {r[0]}") for r in rows]
    return jsonify(_select2_payload(items, more=(len(items) == limit)))


@photos_bp.get("/api/search/samples")
@require_selected_db
def api_search_samples():
    selected_db = session["selected_db"]
    qtxt, limit, offset = _paginate()
    like = f"%{qtxt}%"

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(search_samples_sql(), (like, limit, offset))
            rows = cur.fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items = [(str(r[0]), f"Sample {r[0]}") for r in rows]
    return jsonify(_select2_payload(items, more=(len(items) == limit)))
