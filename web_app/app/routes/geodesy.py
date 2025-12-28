# app/routes/geodesy.py

from __future__ import annotations

import csv
import io

from flask import Blueprint, jsonify, render_template, request, flash, redirect, url_for, session

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db, float_or_none

from app.queries import (
    find_geopts_srid_sql,
    upsert_geopt_sql,
    list_geopts_sql,
    delete_geopt_sql,
    update_geopt_sql,
    geojson_geopts_bbox_sql,
    geojson_polygons_bbox_sql,
    geojson_photos_bbox_sql,
    geopts_extent_4326_sql
)

geodesy_bp = Blueprint('geodesy', __name__)


# -------------------------
# Helpers (local for now)
# -------------------------

def _read_text_file(file_storage) -> str:
    """
    Read uploaded file as text. Tries UTF-8 first, then CP1250, then Latin-1.
    """
    raw = file_storage.read()
    for enc in ("utf-8", "cp1250", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _is_header_row(row: list[str]) -> bool:
    if not row:
        return False
    head = " ".join([c.lower().strip() for c in row])
    return ("id" in head and "x" in head and "y" in head) or ("id_pts" in head)


def _parse_points(text: str) -> list[dict]:
    """
    Accepts:
      - CSV (comma/semicolon)
      - whitespace separated
    Expected columns:
      id_pts, x, y, h, code(optional), notes(optional)

    Returns list of dicts: {id_pts, x, y, h, code, notes}
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith("#") and not ln.startswith("//")]

    if not lines:
        return []

    sample = "\n".join(lines[:10])
    delim = None
    if ";" in sample and sample.count(";") >= sample.count(","):
        delim = ";"
    elif "," in sample:
        delim = ","

    rows: list[list[str]] = []
    if delim:
        reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
        for row in reader:
            row = [c.strip() for c in row]
            if row and not all(not c for c in row):
                rows.append(row)
    else:
        for ln in lines:
            rows.append(ln.split())

    if rows and _is_header_row(rows[0]):
        rows = rows[1:]

    pts: list[dict] = []
    for row in rows:
        if len(row) < 4:
            continue

        try:
            id_pts = int(str(row[0]).strip())
        except Exception:
            continue

        # allow comma decimal
        x = float_or_none(str(row[1]).strip().replace(",", "."))
        y = float_or_none(str(row[2]).strip().replace(",", "."))
        h = float_or_none(str(row[3]).strip().replace(",", "."))

        if x is None or y is None or h is None:
            continue

        code = row[4].strip() if len(row) >= 5 and row[4] is not None else None
        notes = row[5].strip() if len(row) >= 6 and row[5] is not None else None

        pts.append(
            dict(
                id_pts=id_pts,
                x=x,
                y=y,
                h=h,
                code=code,
                notes=notes,
            )
        )

    return pts


def _parse_bbox(bbox_str: str):
    """
    bbox is expected in EPSG:4326: 'minx,miny,maxx,maxy' (lon/lat)
    """
    if not bbox_str:
        return None
    parts = [p.strip() for p in bbox_str.split(",")]
    if len(parts) != 4:
        return None
    try:
        minx, miny, maxx, maxy = [float(p) for p in parts]
    except Exception:
        return None
    if minx >= maxx or miny >= maxy:
        return None
    return minx, miny, maxx, maxy


def _get_target_srid(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(find_geopts_srid_sql())
        row = cur.fetchone()
        srid = int(row[0]) if row and row[0] else 0
    return srid


# -------------------------
# Routes
# -------------------------

@geodesy_bp.route('/geodesy', methods=['GET'])
@require_selected_db
def geodesy():
    """
    Page with upload form + Leaflet preview map.
    """
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)
    try:
        target_srid = _get_target_srid(conn)
    finally:
        conn.close()

    # Optional: expose codes list for UI
    codes = ['SU', 'FX', 'EP', 'FP', 'NI', 'PF', 'SP']
    return render_template('geodesy.html', target_srid=target_srid, codes=codes)


@geodesy_bp.route('/geodesy/upload', methods=['POST'])
@require_selected_db
def upload_geopts():
    """
    Upload CSV/TXT from total station, parse points and upsert them into tab_geopts.
    """
    selected_db = session.get('selected_db')
    file = request.files.get('file')
    source_epsg = (request.form.get('source_epsg') or '').strip()

    if not file:
        flash('Musíš vybrat soubor (CSV/TXT).', 'danger')
        return redirect(url_for('geodesy.geodesy'))

    conn = get_terrain_connection(selected_db)
    try:
        target_srid = _get_target_srid(conn)
        if target_srid <= 0:
            flash('Projektový SRID není nastaven (Find_SRID pro tab_geopts.pts_geom).', 'danger')
            return redirect(url_for('geodesy.geodesy'))

        src_epsg = int(source_epsg) if source_epsg else int(target_srid)

        text = _read_text_file(file)
        pts = _parse_points(text)

        if not pts:
            flash('Soubor neobsahuje žádné validní body.', 'warning')
            return redirect(url_for('geodesy.geodesy'))

        sql = upsert_geopt_sql()
        upserted = 0

        with conn.cursor() as cur:
            for p in pts:
                # upsert_geopt_sql expects code 3x (CASE uses it 3 times)
                cur.execute(
                    sql,
                    (
                        p['x'], p['y'], p['h'], src_epsg, target_srid,
                        p['id_pts'], p['h'],
                        p.get('code'), p.get('code'), p.get('code'),
                        # notes are not in current upsert_geopt_sql (your queries.py version)
                        # If you extend SQL to include notes, append p.get('notes') here.
                    ),
                )
                upserted += 1

        conn.commit()
        logger.info(f"[{selected_db}] geodesy upload: upserted={upserted}, source_epsg={src_epsg}, target_srid={target_srid}")
        flash(f'Import hotov: zpracováno {upserted} bodů.', 'success')
        return redirect(url_for('geodesy.geodesy'))

    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] geodesy upload failed: {e}")
        flash(f'Import selhal: {e}', 'danger')
        return redirect(url_for('geodesy.geodesy'))
    finally:
        conn.close()


@geodesy_bp.route('/geodesy/list', methods=['GET'])
@require_selected_db
def list_geopts():
    """
    JSON list of existing points (for modal table).
    Supports filters: q, id_from, id_to, limit
    """
    selected_db = session.get('selected_db')

    q = (request.args.get('q') or '').strip() or None
    id_from = (request.args.get('id_from') or '').strip()
    id_to = (request.args.get('id_to') or '').strip()
    limit = int(request.args.get('limit') or 500)

    id_from_v = int(id_from) if id_from else None
    id_to_v = int(id_to) if id_to else None
    q_like = f"%{q}%" if q else None

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                list_geopts_sql(),
                (
                    q, q_like, q_like,
                    id_from_v, id_from_v,
                    id_to_v, id_to_v,
                    limit,
                ),
            )
            rows = cur.fetchall()

        data = [
            dict(
                id_pts=r[0],
                x=float(r[1]),
                y=float(r[2]),
                h=float(r[3]),
                code=r[4],
                notes=r[5] if len(r) > 5 else None,
            )
            for r in rows
        ]
        return jsonify({"ok": True, "rows": data})

    except Exception as e:
        logger.exception(f"[{selected_db}] geodesy list failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@geodesy_bp.route('/geodesy/delete/<int:id_pts>', methods=['POST'])
@require_selected_db
def delete_geopt(id_pts: int):
    """
    Delete one point by id_pts.
    """
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(delete_geopt_sql(), (id_pts,))
        conn.commit()
        logger.info(f"[{selected_db}] geodesy delete id_pts={id_pts}")
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] geodesy delete failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@geodesy_bp.route('/geodesy/update/<int:id_pts>', methods=['POST'])
@require_selected_db
def update_geopt(id_pts: int):
    """
    Update x,y,h,code,notes for point id_pts.
    Trigger maintains pts_geom.
    """
    selected_db = session.get('selected_db')
    payload = request.get_json(silent=True) or {}

    try:
        x = float(payload.get('x'))
        y = float(payload.get('y'))
        h = float(payload.get('h'))
    except Exception:
        return jsonify({"ok": False, "error": "Invalid x/y/h"}), 400

    code = (payload.get('code') or '').strip()
    notes = (payload.get('notes') or '').strip()

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            # update_geopt_sql uses code 3x
            cur.execute(update_geopt_sql(), (x, y, h, code, code, code, notes, id_pts))
        conn.commit()
        logger.info(f"[{selected_db}] geodesy update id_pts={id_pts}")
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        logger.exception(f"[{selected_db}] geodesy update failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@geodesy_bp.route('/geodesy/geojson', methods=['GET'])
@require_selected_db
def geopts_geojson():
    """
    GeoJSON FeatureCollection of points inside bbox (EPSG:4326).
    Query params:
      bbox=minx,miny,maxx,maxy
      code=SU|FX|...
      q=free text
      id_from, id_to
      limit
    """
    selected_db = session.get('selected_db')
    bbox = _parse_bbox(request.args.get('bbox', ''))
    if not bbox:
        return jsonify({"type": "FeatureCollection", "features": []})

    code = (request.args.get('code') or '').strip().upper() or None
    q = (request.args.get('q') or '').strip() or None
    id_from = (request.args.get('id_from') or '').strip()
    id_to = (request.args.get('id_to') or '').strip()
    limit = int(request.args.get('limit') or 5000)

    id_from_v = int(id_from) if id_from else None
    id_to_v = int(id_to) if id_to else None
    q_like = f"%{q}%" if q else None

    conn = get_terrain_connection(selected_db)
    try:
        target_srid = _get_target_srid(conn)
        if target_srid <= 0:
            return jsonify({"type": "FeatureCollection", "features": []})

        with conn.cursor() as cur:
            cur.execute(
                geojson_geopts_bbox_sql(),
                (
                    bbox[0], bbox[1], bbox[2], bbox[3],
                    target_srid,
                    code, code,
                    q, q_like, q_like,
                    id_from_v, id_from_v,
                    id_to_v, id_to_v,
                    limit,
                ),
            )
            fc = cur.fetchone()[0]

        return jsonify(fc)

    except Exception as e:
        logger.exception(f"[{selected_db}] geodesy geojson failed: {e}")
        return jsonify({"type": "FeatureCollection", "features": [], "error": str(e)}), 500
    finally:
        conn.close()


@geodesy_bp.route('/geodesy/polygons-geojson', methods=['GET'])
@require_selected_db
def polygons_geojson():
    """
    GeoJSON FeatureCollection of polygon geom_top within bbox (EPSG:4326).
    Query params:
      bbox=minx,miny,maxx,maxy
      limit
    """
    selected_db = session.get('selected_db')
    bbox = _parse_bbox(request.args.get('bbox', ''))
    if not bbox:
        return jsonify({"type": "FeatureCollection", "features": []})

    limit = int(request.args.get('limit') or 2000)

    conn = get_terrain_connection(selected_db)
    try:
        target_srid = _get_target_srid(conn)
        if target_srid <= 0:
            return jsonify({"type": "FeatureCollection", "features": []})

        with conn.cursor() as cur:
            cur.execute(
                geojson_polygons_bbox_sql(),
                (bbox[0], bbox[1], bbox[2], bbox[3], target_srid, limit),
            )
            fc = cur.fetchone()[0]

        return jsonify(fc)

    except Exception as e:
        logger.exception(f"[{selected_db}] geodesy polygons geojson failed: {e}")
        return jsonify({"type": "FeatureCollection", "features": [], "error": str(e)}), 500
    finally:
        conn.close()


@geodesy_bp.route('/geodesy/photos-geojson', methods=['GET'])
@require_selected_db
def photos_geojson():
    """
    GeoJSON FeatureCollection of photo points (gps_lon/gps_lat) inside bbox (EPSG:4326).
    Query params:
      bbox=minx,miny,maxx,maxy
      limit
    """
    selected_db = session.get('selected_db')
    bbox = _parse_bbox(request.args.get('bbox', ''))
    if not bbox:
        return jsonify({"type": "FeatureCollection", "features": []})

    limit = int(request.args.get('limit') or 5000)

    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                geojson_photos_bbox_sql(),
                (bbox[0], bbox[1], bbox[2], bbox[3], limit),
            )
            fc = cur.fetchone()[0]

        return jsonify(fc)

    except Exception as e:
        logger.exception(f"[{selected_db}] geodesy photos geojson failed: {e}")
        return jsonify({"type": "FeatureCollection", "features": [], "error": str(e)}), 500
    finally:
        conn.close()

# route for adjusting geodesy map preview extent
@geodesy_bp.route('/geodesy/extent', methods=['GET'])
@require_selected_db
def geopts_extent():
    """
    Returns bbox of geodetic points in EPSG:4326:
      { ok: True, bbox: [minx, miny, maxx, maxy] }  or bbox: null if no points
    """
    selected_db = session.get('selected_db')
    conn = get_terrain_connection(selected_db)
    try:
        with conn.cursor() as cur:
            cur.execute(geopts_extent_4326_sql())
            row = cur.fetchone()

        if not row or any(v is None for v in row):
            return jsonify({"ok": True, "bbox": None})

        minx, miny, maxx, maxy = [float(v) for v in row]
        # sanity
        if minx >= maxx or miny >= maxy:
            return jsonify({"ok": True, "bbox": None})

        return jsonify({"ok": True, "bbox": [minx, miny, maxx, maxy]})

    except Exception as e:
        logger.exception(f"[{selected_db}] geodesy extent failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()
