# app/routes/hmatrix.py

from flask import Blueprint, render_template, request, redirect, flash, session, url_for
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db
from app.queries.hmatrix import (
    count_sj_by_type_all,
    count_total_sj,
    count_objects,
    count_sj_without_relation,
    fetch_stratigraphy_relations
)
from config import Config
import networkx as nx
import matplotlib.pyplot as plt
from datetime import datetime
import os

hmatrix_bp = Blueprint('hmatrix', __name__)


@hmatrix_bp.route('/harrismatrix', methods=['GET', 'POST'])
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
        cur.close()
        conn.close()

    harris_image = session.get('harrismatrix_image')

    return render_template('harrismatrix.html',
                           selected_db=selected_db,
                           total_sj_count=total_sj_count,
                           object_count=object_count,
                           sj_without_relation=sj_without_relation,
                           sj_type_counts=sj_type_counts,
                           harris_image=harris_image)


@su_bp.route('/generate-harrismatrix', methods=['POST'])
@require_selected_db
def generate_harrismatrix():
    selected_db = session.get('selected_db')
    if not selected_db:
        flash('No terrain DB selected.', 'danger')
        return redirect(url_for('su.harrismatrix'))

    # --- 1) načtení barev z formuláře (fallback na rozumné defaulty) ---
    deposit_color   = (request.form.get('deposit_color')   or '#90EE90').strip()
    negative_color  = (request.form.get('negative_color')  or '#FFA07A').strip()
    structure_color = (request.form.get('structure_color') or '#87CEFA').strip()

    conn = None
    try:
        conn = get_terrain_connection(selected_db)

        # 2) načti vztahy a typy SU
        with conn.cursor() as cur:
            cur.execute("SELECT ref_sj1, relation, ref_sj2 FROM tab_sj_stratigraphy;")
            rels = cur.fetchall()

            cur.execute("SELECT id_sj, sj_typ FROM tab_sj;")
            all_sj_rows = cur.fetchall()

        all_sj = {int(r[0]) for r in all_sj_rows}
        sj_type_map = {int(r[0]): (r[1] or '').lower() for r in all_sj_rows}

        # 3) union-find pro '='
        dsu = DSU()
        for a, rel, b in rels:
            if rel == '=':
                dsu.union(int(a), int(b))

        # skupiny (superuzly) + popisky
        groups = {}
        for node in all_sj.union({int(a) for a, _, _ in rels}).union({int(b) for _, _, b in rels}):
            rep = dsu.find(int(node))
            groups.setdefault(rep, set()).add(int(node))

        label_map = {rep: "=".join(map(str, sorted(members)))
                     for rep, members in groups.items()}

        # pomocná funkce pro typ skupiny (nejčastější typ ve skupině)
        from collections import Counter
        def group_type(rep):
            members = groups[rep]
            types = [sj_type_map.get(m, '') for m in members if sj_type_map.get(m, '')]
            return Counter(types).most_common(1)[0][0] if types else ''

        # 4) DAG mezi superuzly (POZOR: správné směrování!)
        #    a > b = a je NAD b  → hrana a -> b (směr shora dolů)
        #    a < b = a je POD b  → hrana b -> a (opět shora dolů)
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
                G.add_edge(u, v)   # a nad b → a→b
            elif rel == '<':
                G.add_edge(v, u)   # a pod b → b→a

        # 5) acykličnost
        if not nx.is_directed_acyclic_graph(G):
            try:
                cycles = list(nx.find_cycle(G, orientation='original'))
            except Exception:
                cycles = []
            logger.warning(f"[{selected_db}] Cycle detected in relations: {cycles}")
            flash('A cycle was found in relations! Harris Matrix was not generated.', 'danger')
            return redirect(url_for('su.harrismatrix'))

        # 6) Hasse (transitive reduction)
        H = nx.algorithms.dag.transitive_reduction(G)

        # 7) layout – explicitně vynutíme top→down
        try:
            pos = nx.drawing.nx_pydot.graphviz_layout(H, prog='dot', args='-Grankdir=TB')
        except Exception as e:
            logger.error(f"[{selected_db}] graphviz_layout failed: {e}")
            flash('Graphviz is missing or failed. Install "graphviz" and "pydot".', 'danger')
            return redirect(url_for('su.harrismatrix'))

        # 8) barvy uzlů dle typu (včetně tolerance 'negativ'/'negative')
        color_map = {
            'deposit':   deposit_color,
            'negativ':   negative_color,   # DB používá "negativ"
            'negative':  negative_color,   # pro jistotu obě varianty
            'structure': structure_color
        }
        node_colors = []
        for node in H.nodes():
            t = group_type(node)
            node_colors.append(color_map.get(t, '#D3D3D3'))  # default gray

        # 9) kreslení
        plt.figure(figsize=(12, 10))
        nx.draw(
            H, pos,
            with_labels=False,
            node_color=node_colors,
            node_size=2000,
            font_size=10,
            font_color='black',
            arrows=False
        )
        nx.draw_networkx_labels(
            H, pos,
            labels={n: label_map.get(n, str(n)) for n in H.nodes()},
            font_size=11
        )

        # 10) uložení do per-DB složky
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

