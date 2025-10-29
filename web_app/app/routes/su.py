# web_app/app/routes/su.py
import os
from datetime import datetime

import jwt
import networkx as nx
from networkx.algorithms.dag import transitive_reduction
import matplotlib
matplotlib.use('Agg')  # <- backend without GUI (no Tk)
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict, Counter

from flask import (
    Blueprint, request, render_template, redirect, url_for, flash, session, send_from_directory
)

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db, float_or_none
from app.utils.admin import get_hmatrix_dirs
from app.queries import (
    count_sj_by_type,            # returns (sql, params)
    count_sj_by_type_all,        # returns SQL string
    count_total_sj,              # returns SQL string
    count_objects,               # returns SQL string
    count_sj_without_relation,   # returns SQL string
    fetch_stratigraphy_relations, # executes & returns rows
    get_all_sj_with_types,
    get_all_objects,
    get_sj_with_object_refs,
)


su_bp = Blueprint('su', __name__)

# --- Add Stratigraphic Unit (SU) ---
# alias paths kept for backward compatibility
@su_bp.route('/add-su', methods=['GET', 'POST'])
@su_bp.route('/add-sj', methods=['GET', 'POST'])
@require_selected_db
def add_su():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    try:
        # Suggested new SU id
        cur.execute("SELECT COALESCE(MAX(id_sj), 0) + 1 FROM tab_sj;")
        suggested_id = cur.fetchone()[0]

        # Authors list
        cur.execute("SELECT mail FROM gloss_personalia ORDER BY mail;")
        authors = [row[0] for row in cur.fetchall()]

        form_data = {}

        # Overview: totals
        cur.execute(count_total_sj())
        sj_count_total = cur.fetchone()[0]

        # SU counts by type
        cur.execute(*count_sj_by_type('deposit'))
        sj_count_deposit = cur.fetchone()[0]

        cur.execute(*count_sj_by_type('negativ'))  # DB stores 'negativ'
        sj_count_negative = cur.fetchone()[0]

        cur.execute(*count_sj_by_type('structure'))
        sj_count_structure = cur.fetchone()[0]

        if request.method == 'POST':
            try:
                id_sj = int(request.form.get('id_sj'))
                # uniqueness
                cur.execute("SELECT 1 FROM tab_sj WHERE id_sj = %s;", (id_sj,))
                if cur.fetchone():
                    flash(f"ID of stratigraphic unit #{id_sj} already exists. Please provide another ID.", "warning")
                    form_data = request.form.to_dict(flat=True)
                    return render_template(
                        'add_su.html',
                        suggested_id=suggested_id,
                        authors=authors,
                        selected_db=selected_db,
                        form_data=form_data,
                        sj_count_total=sj_count_total,
                        sj_count_deposit=sj_count_deposit,
                        sj_count_negativ=sj_count_negative,
                        sj_count_structure=sj_count_structure
                    )

                sj_typ = request.form.get('sj_typ')
                description = request.form.get('description')
                interpretation = request.form.get('interpretation')
                author = request.form.get('author')
                recorded = datetime.now()
                docu_plan = 'docu_plan' in request.form
                docu_vertical = 'docu_vertical' in request.form

                # Insert to tab_sj (SUs)
                cur.execute("""
                    INSERT INTO tab_sj (id_sj, sj_typ, description, interpretation, author, recorded, docu_plan, docu_vertical)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (id_sj, sj_typ, description, interpretation, author, recorded, docu_plan, docu_vertical))

                # Insert into type-specific tables
                if sj_typ == 'deposit':
                    cur.execute("""
                        INSERT INTO tab_sj_deposit (id_deposit, deposit_typ, color, boundary_visibility, "structure", compactness, deposit_removed)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        id_sj,
                        request.form.get('deposit_typ'),
                        request.form.get('color'),
                        request.form.get('boundary_visibility'),
                        request.form.get('structure'),
                        request.form.get('compactness'),
                        request.form.get('deposit_removed')
                    ))
                elif sj_typ == 'negativ':
                    cur.execute("""
                        INSERT INTO tab_sj_negativ (id_negativ, negativ_typ, excav_extent, ident_niveau_cut, shape_plan, shape_sides, shape_bottom)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        id_sj,
                        request.form.get('negativ_typ'),
                        request.form.get('excav_extent'),
                        'ident_niveau_cut' in request.form,
                        request.form.get('shape_plan'),
                        request.form.get('shape_sides'),
                        request.form.get('shape_bottom')
                    ))
                elif sj_typ == 'structure':
                    cur.execute("""
                        INSERT INTO tab_sj_structure (id_structure, structure_typ, construction_typ, binder, basic_material, length_m, width_m, height_m)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        id_sj,
                        request.form.get('structure_typ'),
                        request.form.get('construction_typ'),
                        request.form.get('binder'),
                        request.form.get('basic_material'),
                        float_or_none(request.form.get('length_m')),
                        float_or_none(request.form.get('width_m')),
                        float_or_none(request.form.get('height_m'))
                    ))
                else:
                    flash("Invalid type of stratigraphic unit.", "danger")
                    form_data = request.form.to_dict(flat=True)
                    return render_template(
                        'add_su.html',
                        suggested_id=suggested_id,
                        authors=authors,
                        selected_db=selected_db,
                        form_data=form_data,
                        sj_count_total=sj_count_total,
                        sj_count_deposit=sj_count_deposit,
                        sj_count_negativ=sj_count_negative,
                        sj_count_structure=sj_count_structure
                    )

                # Stratigraphic relations
                relation_inputs = {
                    '>': [request.form.get('above_1'), request.form.get('above_2')],
                    '<': [request.form.get('below_1'), request.form.get('below_2')],
                    '=': [request.form.get('equal')],
                }

                for relation, sj_list in relation_inputs.items():
                    for sj_str in sj_list:
                        if sj_str:
                            try:
                                related_sj = int(sj_str)
                                if relation == '>':
                                    # related_sj > id_sj  -> store as (id_sj, '<', related_sj)
                                    cur.execute("""
                                        INSERT INTO tab_sj_stratigraphy (ref_sj1, relation, ref_sj2)
                                        VALUES (%s, %s, %s)
                                    """, (id_sj, '<', related_sj))
                                elif relation == '<':
                                    # id_sj < related_sj -> store as (id_sj, '<', related_sj)
                                    cur.execute("""
                                        INSERT INTO tab_sj_stratigraphy (ref_sj1, relation, ref_sj2)
                                        VALUES (%s, %s, %s)
                                    """, (id_sj, '<', related_sj))
                                elif relation == '=':
                                    cur.execute("""
                                        INSERT INTO tab_sj_stratigraphy (ref_sj1, relation, ref_sj2)
                                        VALUES (%s, %s, %s)
                                    """, (id_sj, '=', related_sj))
                            except ValueError:
                                flash(f"Invalid stratigraphic unit ID '{sj_str}' for relation '{relation}' — record not saved.", "warning")

            except Exception as e:
                flash(f"Error while saving SU: {e}", "danger")
                conn.rollback()
                form_data = request.form.to_dict(flat=True)
            else:
                conn.commit()
                flash(f"SU #{id_sj} has been saved.", "success")

        return render_template(
            'add_su.html',             # template name kept as-is
            suggested_id=suggested_id,
            authors=authors,
            selected_db=selected_db,
            form_data=form_data,
            sj_count_total=sj_count_total,
            sj_count_deposit=sj_count_deposit,
            sj_count_negativ=sj_count_negative,
            sj_count_structure=sj_count_structure
        )

    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass


# --- Harris Matrix (summary + generator) ---
@su_bp.route('/harrismatrix', methods=['GET', 'POST'])
@require_selected_db
def harrismatrix():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    try:
        cur.execute(count_sj_by_type_all())
        sj_type_counts = cur.fetchall()

        cur.execute(count_total_sj())
        total_sj_count = cur.fetchone()[0]

        cur.execute(count_objects())
        object_count = cur.fetchone()[0]

        cur.execute(count_sj_without_relation())
        sj_without_relation = cur.fetchone()[0]

    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass

    harris_image = session.get('harrismatrix_image')

    return render_template(
        'harrismatrix.html',
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


def _edge_str(u, v, label_map):
    """Vypíše hranu ve formátu A > B (podpora superuzlů '4=5')."""
    a = label_map.get(u, str(u))
    b = label_map.get(v, str(v))
    return f"{a} > {b}"


@su_bp.route('/generate-harrismatrix', methods=['POST'])
@require_selected_db
def generate_harrismatrix():
    selected_db = session.get('selected_db')
    if not selected_db:
        flash('No terrain DB selected.', 'danger')
        return redirect(url_for('su.harrismatrix'))

    # --- barvy + tvary z formuláře ---
    deposit_color   = (request.form.get('deposit_color')   or '#ADD8E6').strip()
    negative_color  = (request.form.get('negative_color')  or '#90EE90').strip()
    structure_color = (request.form.get('structure_color') or '#FFD700').strip()
    node_shape_req  = (request.form.get('node_shape') or 'circle').lower()
    node_shape      = 'o' if node_shape_req == 'circle' else 's'   # 'o' = circle, 's' = square
    draw_objects    = bool(request.form.get('draw_objects'))

    conn = None
    try:
        conn = get_terrain_connection(selected_db)

        with conn.cursor() as cur:
            rels = fetch_stratigraphy_relations(conn)                  # [(ref_sj1, relation, ref_sj2), ...]
        
            all_sj_rows = get_all_sj_with_types(conn)                  # [(id_sj, sj_typ), ...]
            
        all_sj = {int(r[0]) for r in all_sj_rows}
        sj_type_map = {int(r[0]): (r[1] or '').lower() for r in all_sj_rows}

        # --- rovnosti -> union-find ---
        dsu = DSU()
        for a, rel, b in rels:
            if rel == '=':
                dsu.union(int(a), int(b))

        # superuzly a popisky
        groups = {}
        for node in all_sj.union({int(a) for a,_,_ in rels}).union({int(b) for _,_,b in rels}):
            rep = dsu.find(int(node))
            groups.setdefault(rep, set()).add(int(node))
        label_map = {rep: "=".join(map(str, sorted(members))) for rep, members in groups.items()}

        def group_type(rep):
            types = [sj_type_map.get(m, '') for m in groups[rep] if sj_type_map.get(m, '')]
            return Counter(types).most_common(1)[0][0] if types else ''

        # --- DAG (správný směr) ---
        # a > b  = a nad b → hrana a->b (shora dolů)
        # a < b  = a pod b → hrana b->a
        G = nx.DiGraph()
        G.add_nodes_from(groups.keys())
        for a, rel, b in rels:
            a, b = int(a), int(b)
            if rel == '=':
                continue
            u, v = dsu.find(a), dsu.find(b)
            if u == v:
                continue
            if rel == '>':
                G.add_edge(u, v)
            elif rel == '<':
                G.add_edge(v, u)

        # acykličnost
        if not nx.is_directed_acyclic_graph(G):
            try:
                # vezmeme první detekovaný cyklus a přepíšeme na „>“ výpis
                cyc = list(nx.find_cycle(G, orientation='original'))
                cyc_nodes = [u for (u, _, _) in cyc] + [cyc[0][0]]
                msg = " → ".join(label_map.get(n, str(n)) for n in cyc_nodes)
            except Exception:
                msg = "Unknown cycle"
            logger.warning(f"[{selected_db}] Cycle detected in relations: {msg}")
            flash(f"A cycle was found in relations: {msg}. Harris Matrix was not generated.", "danger")
            return redirect(url_for('su.harrismatrix'))

        # --- Hasse: transitive reduction ---
        H = nx.algorithms.dag.transitive_reduction(G)
        
        # --- VALIDÁTOR: redundantní hrany (takové, které TR odstraní) ---
        redundant = sorted(set(G.edges()) - set(H.edges()))
        if redundant:
            # převeďme na čitelný výpis A > B, ukážeme max 10 ks, zbytek do logu
            rd_labels = [_edge_str(u, v, label_map) for (u, v) in redundant]
            shown = rd_labels[:10]
            more = len(rd_labels) - len(shown)
            if more > 0:
                flash(f"Redundant relations (first 10 of {len(rd_labels)}): " + ", ".join(shown) + f", … (+{more} more).", "warning")
            else:
                flash("Redundant relations: " + ", ".join(shown), "warning")
            logger.info(f"[{selected_db}] Redundant relations removed by Hasse reduction: {', '.join(rd_labels)}")
        else:
            logger.info(f"[{selected_db}] No redundant relations.")


        # --- layout (dot) + auto-orientace top-down ---
        try:
            pos = nx.drawing.nx_pydot.graphviz_layout(H, prog='dot')
        except Exception as e:
            logger.error(f"[{selected_db}] graphviz_layout failed: {e}")
            flash('Graphviz layout failed. Ensure "graphviz" and "pydot" are installed.', 'danger')
            return redirect(url_for('su.harrismatrix'))

        tops    = [n for n in H.nodes() if H.in_degree(n) == 0]
        bottoms = [n for n in H.nodes() if H.out_degree(n) == 0]
        if tops and bottoms:
            top_mean_y = sum(pos[n][1] for n in tops) / len(tops)
            bottom_mean_y = sum(pos[n][1] for n in bottoms) / len(bottoms)
            # chceme top nahoře → pokud je níže, převrátíme svisle
            if top_mean_y < bottom_mean_y:
                ymin = min(y for (_, y) in pos.values())
                ymax = max(y for (_, y) in pos.values())
                for n, (x, y) in list(pos.items()):
                    pos[n] = (x, (ymax + ymin) - y)

        # --- barvy uzlů podle typu ---
        color_map = {
            'deposit':   deposit_color,
            'negativ':   negative_color,   # DB má "negativ"
            'negative':  negative_color,
            'structure': structure_color,
        }
        node_colors = [color_map.get(group_type(n), '#D3D3D3') for n in H.nodes()]

        plt.figure(figsize=(12, 10))
        ax = plt.gca()

        # --- (volitelně) kreslení obálek objektů ---
        if draw_objects:
            try:
                with conn.cursor() as cur:
                    obj_rows = get_all_objects(conn)                           # [(id_object, object_typ, superior_object), ...]
                    obj_rows = [(int(i), t, (int(s) if s not in (None, 0) else None)) for i, t, s in obj_rows]

                    sj_obj_rows = get_sj_with_object_refs(conn)                # [(id_sj, ref_object), ...]
                    sj_obj_rows = [(int(sj), int(obj)) for sj, obj in sj_obj_rows]
            except Exception as e:
                logger.error(f"[{selected_db}] Loading objects failed: {e}")
                obj_rows, sj_obj_rows = [], []

            # SU → objekt → superuzly (po sloučení '=')
            obj_to_reps = defaultdict(set)
            for sj, obj in sj_obj_rows:
                rep = dsu.find(sj)
                if rep in H.nodes:  # jen uzly, které se kreslí
                    obj_to_reps[obj].add(rep)

            # hierarchie objektů (rodič absorbující potomky)
            children = defaultdict(list)
            for oid, typ, sup in obj_rows:
                if sup is not None:
                    children[sup].append(oid)

            visited = set()
            def accumulate(oid):
                if oid in visited:
                    return obj_to_reps.get(oid, set())
                reps = set(obj_to_reps.get(oid, set()))
                for ch in children.get(oid, []):
                    reps |= accumulate(ch)
                obj_to_reps[oid] = reps
                visited.add(oid)
                return reps

            for oid, _, _ in obj_rows:
                accumulate(oid)

            # kreslení obdélníkových obálek (za graf, poloprůhledně)
            for oid, typ, _ in obj_rows:
                reps = list(obj_to_reps.get(oid, set()))
                if not reps:
                    continue
                xs = [pos[r][0] for r in reps if r in pos]
                ys = [pos[r][1] for r in reps if r in pos]
                if not xs or not ys:
                    continue

                pad = 40.0
                x0, x1 = min(xs) - pad, max(xs) + pad
                y0, y1 = min(ys) - pad, max(ys) + pad

                rect = mpatches.FancyBboxPatch(
                    (x0, y0), x1 - x0, y1 - y0,
                    boxstyle="round,pad=0.02,rounding_size=8",
                    linewidth=1.3, edgecolor="#555", facecolor="none",
                    alpha=0.5, zorder=0
                )
                ax.add_patch(rect)
                # popisek objektu nad rámem
                # POPISEK: dovnitř do pravého horního rohu, větší a čitelný
                label = f"Obj {oid}" + (f" ({typ})" if typ else "")
                ax.text(
                    x1 - 8.0, y1 - 8.0, label,
                    ha='right', va='top',
                    fontsize=13, color="#222", zorder=3,
                    bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.75)
                )
        # --- hrany + uzly + popisky (uzly jako circle/square podle volby) ---
        nx.draw(
            H, pos,
            with_labels=False,
            node_color=node_colors,
            node_size=2000,
            arrows=False,
            node_shape=node_shape,
            ax=ax
        )
        nx.draw_networkx_labels(H, pos,
                                labels={n: label_map.get(n, str(n)) for n in H.nodes()},
                                font_size=11, ax=ax)

        # --- uložení ---
        images_dir, _ = get_hmatrix_dirs(selected_db)
        os.makedirs(images_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{selected_db}_{timestamp}.png"
        filepath = os.path.join(images_dir, filename)
        plt.savefig(filepath, format="png", bbox_inches='tight')
        plt.close()

        session['harrismatrix_image'] = filename
        flash('Harris Matrix was generated.', 'success')
        return redirect(url_for('su.harrismatrix'))

    except Exception as e:
        logger.error(f"[{selected_db}] Error while generating Harris Matrix: {e}")
        flash(f'Error while generating Harris Matrix: {str(e)}', 'danger')
        return redirect(url_for('su.harrismatrix'))
    finally:
        if conn:
            conn.close()


@su_bp.route('/harrismatrix/img/<path:filename>')
@require_selected_db
def harrismatrix_image(filename):
    selected_db = session.get('selected_db')
    images_dir, _ = get_hmatrix_dirs(selected_db)
    return send_from_directory(images_dir, filename)
