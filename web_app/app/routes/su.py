# web_app/app/routes/su.py
import os
from datetime import datetime
from psycopg2.extras import Json

import networkx as nx
from networkx.algorithms.dag import transitive_reduction
import matplotlib

matplotlib.use("Agg")  # backend without GUI (no Tk)

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import Counter

from flask import (
    Blueprint,
    request,
    render_template,
    redirect,
    url_for,
    flash,
    session,
    send_from_directory,
)

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db, float_or_none
from app.utils.admin import get_hmatrix_dirs

from app.queries import (
    count_sj_by_type,
    count_total_sj,
    fetch_stratigraphy_relations,
    get_all_sj_with_types,
    get_all_objects,
    get_sj_with_object_refs,
    list_polygon_names_sql,
    list_last_su_sql,
    list_su_for_media_select_sql,
    insert_sj_polygon_link_sql,
    delete_su_sql,
)

from app.utils import (
    save_to_uploads,
    cleanup_upload,
    make_pk,
    validate_pk,
    validate_mime,
    validate_extension,
    detect_mime,
    final_paths,
    move_into_place,
    make_thumbnail,
    sha256_file,
    extract_exif,
    delete_media_files,
)

from app.utils.media_map import MEDIA_TABLES, LINK_TABLES_SJ

su_bp = Blueprint("su", __name__)


# -------------------------------------------------------------------
# SU: main page (new SU + SU list + attach media)
# -------------------------------------------------------------------
@su_bp.route("/add-su", methods=["GET", "POST"])
@su_bp.route("/add-sj", methods=["GET", "POST"])  # backward compatibility
@require_selected_db
def add_su():
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    # values needed for rendering (always)
    suggested_id = None
    authors = []
    polygons = []
    su_for_media = []
    last_sus = []
    form_data = {}

    try:
        # Suggested next SU id
        cur.execute("SELECT COALESCE(MAX(id_sj), 0) + 1 FROM tab_sj;")
        suggested_id = cur.fetchone()[0]

        # Authors list
        cur.execute("SELECT mail FROM gloss_personalia ORDER BY mail;")
        authors = [row[0] for row in cur.fetchall()]

        # Polygons list for in-page filtering
        cur.execute(list_polygon_names_sql())
        polygons = [r[0] for r in cur.fetchall()]

        # SU list for Attach graphic documentation
        cur.execute(list_su_for_media_select_sql())
        su_for_media = [
            {"id": int(r[0]), "typ": (r[1] or ""), "desc": (r[2] or "")} for r in cur.fetchall()
        ]

        # Last 10 SUs
        cur.execute(list_last_su_sql(10))
        last_sus = [
            {
                "id": int(r[0]),
                "typ": (r[1] or ""),
                "desc": (r[2] or ""),
                "recorded": r[3],
                "author": (r[4] or ""),
            }
            for r in cur.fetchall()
        ]

        # Overview counts
        cur.execute(count_total_sj())
        sj_count_total = cur.fetchone()[0]

        cur.execute(*count_sj_by_type("deposit"))
        sj_count_deposit = cur.fetchone()[0]

        cur.execute(*count_sj_by_type("negativ"))
        sj_count_negativ = cur.fetchone()[0]

        cur.execute(*count_sj_by_type("structure"))
        sj_count_structure = cur.fetchone()[0]

        if request.method == "POST":
            try:
                id_sj = int(request.form.get("id_sj") or "0")
                if id_sj <= 0:
                    raise ValueError("Invalid SU ID.")

                # uniqueness
                cur.execute("SELECT 1 FROM tab_sj WHERE id_sj = %s;", (id_sj,))
                if cur.fetchone():
                    flash(
                        f"ID of stratigraphic unit #{id_sj} already exists. Please provide another ID.",
                        "warning",
                    )
                    form_data = request.form.to_dict(flat=True)
                    return render_template(
                        "add_su.html",
                        selected_db=selected_db,
                        suggested_id=suggested_id,
                        authors=authors,
                        polygons=polygons,
                        su_for_media=su_for_media,
                        last_sus=last_sus,
                        sj_count_total=sj_count_total,
                        sj_count_deposit=sj_count_deposit,
                        sj_count_negativ=sj_count_negativ,
                        sj_count_structure=sj_count_structure,
                        form_data=form_data,
                    )

                sj_typ = (request.form.get("sj_typ") or "").strip().lower()
                description = request.form.get("description")
                interpretation = request.form.get("interpretation")
                author = request.form.get("author")
                recorded = datetime.now().date()  # DDL uses date
                docu_plan = "docu_plan" in request.form
                docu_vertical = "docu_vertical" in request.form

                # Insert into tab_sj (base)
                cur.execute(
                    """
                    INSERT INTO tab_sj
                      (id_sj, sj_typ, description, interpretation, author, recorded, docu_plan, docu_vertical)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (id_sj, sj_typ, description, interpretation, author, recorded, docu_plan, docu_vertical),
                )

                # Insert into type-specific tables
                if sj_typ == "deposit":
                    cur.execute(
                        """
                        INSERT INTO tab_sj_deposit
                          (id_deposit, deposit_typ, color, boundary_visibility, "structure", compactness, deposit_removed)
                        VALUES
                          (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            id_sj,
                            request.form.get("deposit_typ"),
                            request.form.get("color"),
                            request.form.get("boundary_visibility"),
                            request.form.get("structure"),
                            request.form.get("compactness"),
                            request.form.get("deposit_removed"),
                        ),
                    )
                elif sj_typ == "negativ":
                    cur.execute(
                        """
                        INSERT INTO tab_sj_negativ
                          (id_negativ, negativ_typ, excav_extent, ident_niveau_cut, shape_plan, shape_sides, shape_bottom)
                        VALUES
                          (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            id_sj,
                            request.form.get("negativ_typ"),
                            request.form.get("excav_extent"),
                            "ident_niveau_cut" in request.form,
                            request.form.get("shape_plan"),
                            request.form.get("shape_sides"),
                            request.form.get("shape_bottom"),
                        ),
                    )
                elif sj_typ == "structure":
                    cur.execute(
                        """
                        INSERT INTO tab_sj_structure
                          (id_structure, structure_typ, construction_typ, binder, basic_material, length_m, width_m, height_m)
                        VALUES
                          (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            id_sj,
                            request.form.get("structure_typ"),
                            request.form.get("construction_typ"),
                            request.form.get("binder"),
                            request.form.get("basic_material"),
                            float_or_none(request.form.get("length_m")),
                            float_or_none(request.form.get("width_m")),
                            float_or_none(request.form.get("height_m")),
                        ),
                    )
                else:
                    raise ValueError("Invalid type of stratigraphic unit.")

                # NEW: link SU to polygons (M:N)
                polygon_names = request.form.getlist("polygon_names")
                polygon_names = [(p or "").strip() for p in polygon_names if (p or "").strip()]
                if polygon_names:
                    sql_link = insert_sj_polygon_link_sql()
                    for poly_name in polygon_names:
                        # validate polygon exists (cheap and clear error)
                        cur.execute("SELECT 1 FROM tab_polygons WHERE polygon_name=%s;", (poly_name,))
                        if not cur.fetchone():
                            raise ValueError(f'Polygon "{poly_name}" does not exist.')
                        cur.execute(sql_link, (id_sj, poly_name))

                # Stratigraphic relations (store exactly as user says)
                # above_* means: current SU is above related SU -> relation '>'
                # below_* means: current SU is below related SU -> relation '<'
                relation_inputs = [
                    (">", request.form.get("above_1")),
                    (">", request.form.get("above_2")),
                    ("<", request.form.get("below_1")),
                    ("<", request.form.get("below_2")),
                    ("=", request.form.get("equal")),
                ]

                for rel, sj_str in relation_inputs:
                    sj_str = (sj_str or "").strip()
                    if not sj_str:
                        continue
                    try:
                        related_sj = int(sj_str)
                    except ValueError:
                        flash(
                            f"Invalid stratigraphic unit ID '{sj_str}' for relation '{rel}' — relation not saved.",
                            "warning",
                        )
                        continue

                    cur.execute(
                        """
                        INSERT INTO tab_sj_stratigraphy (ref_sj1, relation, ref_sj2)
                        VALUES (%s, %s, %s)
                        """,
                        (id_sj, rel, related_sj),
                    )

                conn.commit()
                flash(f"SU #{id_sj} has been saved.", "success")
                logger.info(f"[{selected_db}] SU saved id={id_sj} type={sj_typ}")

                return redirect(url_for("su.add_su"))

            except Exception as e:
                conn.rollback()
                flash(f"Error while saving SU: {e}", "danger")
                logger.error(f"[{selected_db}] add_su save error: {e}")
                form_data = request.form.to_dict(flat=True)

        return render_template(
            "add_su.html",
            selected_db=selected_db,
            suggested_id=suggested_id,
            authors=authors,
            polygons=polygons,
            su_for_media=su_for_media,
            last_sus=last_sus,
            sj_count_total=sj_count_total,
            sj_count_deposit=sj_count_deposit,
            sj_count_negativ=sj_count_negativ,
            sj_count_structure=sj_count_structure,
            form_data=form_data,
        )

    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


# -------------------------------------------------------------------
# SU: delete (with confirm modal in UI)
# -------------------------------------------------------------------
@su_bp.post("/su/delete")
@require_selected_db
def delete_su():
    selected_db = session["selected_db"]
    sj_id_raw = (request.form.get("id_sj") or "").strip()

    try:
        sj_id = int(sj_id_raw)
    except ValueError:
        flash("Invalid SU ID.", "warning")
        return redirect(url_for("su.add_su"))

    conn = get_terrain_connection(selected_db)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # 0) delete stratigraphy relations explicitly (no FK now)
            cur.execute(
                "DELETE FROM tab_sj_stratigraphy WHERE ref_sj1=%s OR ref_sj2=%s;",
                (sj_id, sj_id),
            )

            # 1) try delete base row
            try:
                cur.execute(delete_su_sql(), (sj_id,))
            except Exception:
                conn.rollback()
                with conn.cursor() as cur2:
                    # subtype tables might block if FK is not ON DELETE CASCADE
                    cur2.execute("DELETE FROM tab_sj_deposit WHERE id_deposit=%s;", (sj_id,))
                    cur2.execute("DELETE FROM tab_sj_negativ WHERE id_negativ=%s;", (sj_id,))
                    cur2.execute("DELETE FROM tab_sj_structure WHERE id_structure=%s;", (sj_id,))
                    # also ensure stratigraphy removed even after rollback
                    cur2.execute(
                        "DELETE FROM tab_sj_stratigraphy WHERE ref_sj1=%s OR ref_sj2=%s;",
                        (sj_id, sj_id),
                    )
                    cur2.execute(delete_su_sql(), (sj_id,))


        conn.commit()
        flash(f"SU #{sj_id} deleted.", "success")
        logger.info(f"[{selected_db}] SU deleted id={sj_id}")

    except Exception as e:
        conn.rollback()
        flash(f"Error while deleting SU: {e}", "danger")
        logger.error(f"[{selected_db}] SU delete error: {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("su.add_su"))


# -------------------------------------------------------------------
# SU: media upload (Attach graphic documentation uses selected SU)
# -------------------------------------------------------------------
@su_bp.post("/su/<int:sj_id>/upload/<media_type>")
@require_selected_db
def upload_su_media(sj_id, media_type):
    selected_db = session["selected_db"]

    if media_type not in MEDIA_TABLES:
        flash("Invalid media type.", "danger")
        return redirect(request.referrer or url_for("su.add_su"))

    files = request.files.getlist("files")
    if not files:
        flash("No files provided.", "warning")
        return redirect(request.referrer or url_for("su.add_su"))

    # verify SU exists (clear error, avoids FS garbage)
    conn_chk = get_terrain_connection(selected_db)
    try:
        with conn_chk.cursor() as cur_chk:
            cur_chk.execute("SELECT 1 FROM tab_sj WHERE id_sj=%s;", (sj_id,))
            if not cur_chk.fetchone():
                flash(f"SU #{sj_id} not found.", "danger")
                return redirect(request.referrer or url_for("su.add_su"))
    finally:
        try:
            conn_chk.close()
        except Exception:
            pass

    meta_cols = MEDIA_TABLES[media_type]["extra_cols"]
    ok, failed = 0, []

    for f in files:
        tmp_path = None
        final_path = None
        thumb_path = None

        try:
            # 1) temporary storing
            tmp_path, _tmp_size = save_to_uploads(Config.UPLOAD_FOLDER, f)

            # 2) extension / pk
            pk_name = make_pk(selected_db, f.filename)  # e.g. "456_IMG_25.jpg"
            validate_pk(pk_name)
            ext = pk_name.rsplit(".", 1)[-1].lower()
            validate_extension(ext, Config.ALLOWED_EXTENSIONS)

            # 3) final storage + collision
            media_dir = Config.MEDIA_DIRS[media_type]
            final_path, thumb_path = final_paths(Config.DATA_DIR, selected_db, media_dir, pk_name)
            if os.path.exists(final_path):
                raise ValueError(f"File already exists: {pk_name}")

            # 4) move + mime + checksum + thumb
            move_into_place(tmp_path, final_path)
            tmp_path = None

            mime = detect_mime(final_path)
            validate_mime(mime, Config.ALLOWED_MIME)
            checksum = sha256_file(final_path)

            try:
                make_thumbnail(final_path, thumb_path, Config.THUMB_MAX_SIDE)
            except Exception:
                pass

            # 5) EXIF (only photos JPEG/TIFF)
            shoot_dt = gps_lat = gps_lon = gps_alt = None
            exif_json = {}
            if media_type == "photos" and mime in ("image/jpeg", "image/tiff"):
                sdt, la, lo, al, exif = extract_exif(final_path)
                shoot_dt, gps_lat, gps_lon, gps_alt, exif_json = sdt, la, lo, al, exif

            # 6) insert into tab_<type> + link to tabaid_*
            t = MEDIA_TABLES[media_type]
            table, id_col = t["table"], t["id_col"]
            vals = [request.form.get(k) or None for k in meta_cols]

            conn = get_terrain_connection(selected_db)
            cur = conn.cursor()
            try:
                if media_type == "photos":
                    cur.execute(
                        f"""INSERT INTO {table}
                            ({id_col}, {", ".join(meta_cols)},
                             mime_type, file_size, checksum_sha256,
                             shoot_datetime, gps_lat, gps_lon, gps_alt, exif_json)
                           VALUES (%s, {", ".join(['%s']*len(meta_cols))}, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [
                            pk_name,
                            *vals,
                            mime,
                            os.path.getsize(final_path),
                            checksum,
                            shoot_dt,
                            gps_lat,
                            gps_lon,
                            gps_alt,
                            Json(exif_json),
                        ],
                    )
                else:
                    cur.execute(
                        f"""INSERT INTO {table}
                            ({id_col}, {", ".join(meta_cols)},
                             mime_type, file_size, checksum_sha256)
                           VALUES (%s, {", ".join(['%s']*len(meta_cols))}, %s, %s, %s)""",
                        [pk_name, *vals, mime, os.path.getsize(final_path), checksum],
                    )

                link = LINK_TABLES_SJ[media_type]
                cur.execute(
                    f"INSERT INTO {link['table']} ({link['fk_sj']}, {link['fk_media']}) VALUES (%s, %s)",
                    (sj_id, pk_name),
                )

                conn.commit()
                ok += 1

            except Exception:
                conn.rollback()
                # cleanup FS garbage if DB fails
                try:
                    delete_media_files(final_path, thumb_path)
                except Exception:
                    pass
                raise

            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            failed.append(f"{f.filename}: {e}")
            logger.warning(f"[{selected_db}] SU media upload failed ({media_type}) file={f.filename}: {e}")

        finally:
            if tmp_path:
                try:
                    cleanup_upload(tmp_path)
                except Exception:
                    pass

    if failed:
        flash(
            f"Uploaded {ok} file(s), {len(failed)} failed: " + "; ".join(failed),
            "warning" if ok else "danger",
        )
    else:
        flash(f"Uploaded {ok} file(s).", "success")

    logger.info(
        f"[{selected_db}] su-media upload: su={sj_id} type={media_type} ok={ok} failed={len(failed)}"
    )
    return redirect(request.referrer or url_for("su.add_su"))


@su_bp.post("/su/<int:sj_id>/unlink/<media_type>/<pk_name>")
@require_selected_db
def unlink_su_media(sj_id, media_type, pk_name):
    """
    Removes only M:N relation SU ↔ media (file and tab_<type> record remain).
    """
    selected_db = session["selected_db"]

    if media_type not in LINK_TABLES_SJ:
        flash("Invalid media type.", "danger")
        return redirect(request.referrer or url_for("su.add_su"))

    link = LINK_TABLES_SJ[media_type]
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()
    try:
        cur.execute(
            f"DELETE FROM {link['table']} WHERE {link['fk_sj']}=%s AND {link['fk_media']}=%s",
            (sj_id, pk_name),
        )
        conn.commit()
        flash("Link removed.", "success" if cur.rowcount else "warning")
    except Exception as e:
        conn.rollback()
        flash(f"Unlink failed: {e}", "danger")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    return redirect(request.referrer or url_for("su.add_su"))


# -------------------------------------------------------------------
# Harris Matrix (kept as-is; you can move it to a separate blueprint later)
# -------------------------------------------------------------------
@su_bp.route("/harrismatrix", methods=["GET", "POST"])
@require_selected_db
def harrismatrix():
    selected_db = session["selected_db"]
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    try:
        cur.execute("SELECT sj_typ, COUNT(*) FROM tab_sj GROUP BY sj_typ;")
        sj_type_counts = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM tab_sj;")
        total_sj_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT ref_object) FROM tab_sj WHERE ref_object IS NOT NULL;")
        object_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*) FROM tab_sj s
            LEFT JOIN (
                SELECT ref_sj1 AS sj FROM tab_sj_stratigraphy
                UNION
                SELECT ref_sj2 AS sj FROM tab_sj_stratigraphy
            ) rel ON s.id_sj = rel.sj
            WHERE rel.sj IS NULL;
            """
        )
        sj_without_relation = cur.fetchone()[0]

    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    harris_image = session.get("harrismatrix_image")

    return render_template(
        "harrismatrix.html",
        selected_db=selected_db,
        total_sj_count=total_sj_count,
        object_count=object_count,
        sj_without_relation=sj_without_relation,
        sj_type_counts=sj_type_counts,
        harris_image=harris_image,
    )


class DSU:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # deterministic: lower ID is representative
        if ra < rb:
            self.parent[rb] = ra
        else:
            self.parent[ra] = rb


@su_bp.route("/generate-harrismatrix", methods=["POST"])
@require_selected_db
def generate_harrismatrix():
    selected_db = session.get("selected_db")
    if not selected_db:
        flash("No terrain DB selected.", "danger")
        return redirect(url_for("su.harrismatrix"))

    deposit_color = (request.form.get("deposit_color") or "#ADD8E6").strip()
    negative_color = (request.form.get("negative_color") or "#90EE90").strip()
    structure_color = (request.form.get("structure_color") or "#FFD700").strip()

    node_shape_req = (request.form.get("node_shape") or "circle").lower()
    node_shape = "o" if node_shape_req == "circle" else "s"
    draw_objects = bool(request.form.get("draw_objects"))

    conn = None
    try:
        conn = get_terrain_connection(selected_db)

        with conn.cursor() as cur:
            rels = fetch_stratigraphy_relations(conn)
            all_sj_rows = get_all_sj_with_types(conn)

        all_sj = {int(r[0]) for r in all_sj_rows}
        sj_type_map = {int(r[0]): (r[1] or "").lower() for r in all_sj_rows}

        # equality -> union-find
        dsu = DSU()
        for a, rel, b in rels:
            if rel == "=":
                dsu.union(int(a), int(b))

        # groups (supernodes) + labels
        groups = {}
        for node in all_sj.union({int(a) for a, _, _ in rels}).union({int(b) for _, _, b in rels}):
            rep = dsu.find(int(node))
            groups.setdefault(rep, set()).add(int(node))
        label_map = {rep: "=".join(map(str, sorted(members))) for rep, members in groups.items()}

        def group_type(rep):
            types = [sj_type_map.get(m, "") for m in groups[rep] if sj_type_map.get(m, "")]
            return Counter(types).most_common(1)[0][0] if types else ""

        # build DAG
        G = nx.DiGraph()
        G.add_nodes_from(groups.keys())
        for a, rel, b in rels:
            a, b = int(a), int(b)
            if rel == "=":
                continue
            u, v = dsu.find(a), dsu.find(b)
            if u == v:
                continue
            if rel == ">":
                G.add_edge(u, v)
            elif rel == "<":
                G.add_edge(v, u)

        # transitive reduction
        try:
            H = transitive_reduction(G)
        except Exception:
            H = G

        # colors by type
        node_colors = []
        for n in H.nodes():
            t = group_type(n)
            if t == "deposit":
                node_colors.append(deposit_color)
            elif t == "negativ":
                node_colors.append(negative_color)
            elif t == "structure":
                node_colors.append(structure_color)
            else:
                node_colors.append("#DDDDDD")

        pos = nx.spring_layout(H, seed=42, k=1.0)

        fig, ax = plt.subplots(figsize=(14, 10))
        ax.axis("off")

        # objects overlay (optional)
        if draw_objects:
            obj_rows = get_all_objects(conn)
            sj_obj_rows = get_sj_with_object_refs(conn)
            obj_to_reps = {}
            for sj_id, obj_id in sj_obj_rows:
                if obj_id is None:
                    continue
                rep = dsu.find(int(sj_id))
                obj_to_reps.setdefault(obj_id, set()).add(rep)

            for oid, typ, _ in obj_rows:
                reps = list(obj_to_reps.get(oid, set()))
                if not reps:
                    continue
                xs = [pos[r][0] for r in reps if r in pos]
                ys = [pos[r][1] for r in reps if r in pos]
                if not xs or not ys:
                    continue

                pad = 0.15
                x0, x1 = min(xs) - pad, max(xs) + pad
                y0, y1 = min(ys) - pad, max(ys) + pad

                rect = mpatches.FancyBboxPatch(
                    (x0, y0),
                    x1 - x0,
                    y1 - y0,
                    boxstyle="round,pad=0.02,rounding_size=0.03",
                    linewidth=1.2,
                    edgecolor="#555",
                    facecolor="none",
                    alpha=0.5,
                    zorder=0,
                )
                ax.add_patch(rect)

                label = f"Obj {oid}" + (f" ({typ})" if typ else "")
                ax.text(
                    x1 - 0.02,
                    y1 - 0.02,
                    label,
                    ha="right",
                    va="top",
                    fontsize=10,
                    color="#222",
                    zorder=3,
                    bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.75),
                )

        nx.draw(
            H,
            pos,
            with_labels=False,
            node_color=node_colors,
            node_size=1800,
            arrows=False,
            node_shape=node_shape,
            ax=ax,
        )
        nx.draw_networkx_labels(H, pos, labels={n: label_map.get(n, str(n)) for n in H.nodes()}, font_size=10, ax=ax)
        nx.draw_networkx_edges(H, pos, arrows=False, ax=ax)

        images_dir, _ = get_hmatrix_dirs(selected_db)
        os.makedirs(images_dir, exist_ok=True)
        filename = f"{selected_db}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(images_dir, filename)
        plt.savefig(filepath, format="png", bbox_inches="tight")
        plt.close()

        session["harrismatrix_image"] = filename
        flash("Harris Matrix was generated.", "success")
        return redirect(url_for("su.harrismatrix"))

    except Exception as e:
        logger.error(f"[{selected_db}] Error while generating Harris Matrix: {e}")
        flash(f"Error while generating Harris Matrix: {str(e)}", "danger")
        return redirect(url_for("su.harrismatrix"))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@su_bp.route("/harrismatrix/img/<path:filename>")
@require_selected_db
def harrismatrix_image(filename):
    selected_db = session.get("selected_db")
    images_dir, _ = get_hmatrix_dirs(selected_db)
    return send_from_directory(images_dir, filename)
