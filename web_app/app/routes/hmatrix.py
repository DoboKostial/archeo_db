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


@hmatrix_bp.route('/generate-harrismatrix', methods=['POST'])
@require_selected_db
def generate_harrismatrix():
    selected_db = session.get('selected_db')
    if not selected_db:
        flash('No terrain database selected.', 'danger')
        return redirect(url_for('hmatrix.harrismatrix'))

    conn = None
    try:
        conn = get_terrain_connection(selected_db)
        relations = fetch_stratigraphy_relations(conn)

        G = nx.DiGraph()

        # Grouping equal (=) relations
        equals_groups = []
        processed_equals = set()

        for ref_sj1, relation, ref_sj2 in relations:
            if relation == '=':
                if ref_sj1 not in processed_equals and ref_sj2 not in processed_equals:
                    equals_groups.append({ref_sj1, ref_sj2})
                else:
                    for group in equals_groups:
                        if ref_sj1 in group or ref_sj2 in group:
                            group.update([ref_sj1, ref_sj2])
                            break
                processed_equals.update([ref_sj1, ref_sj2])

        node_mapping = {}
        for group in equals_groups:
            representative = min(group)
            for node in group:
                node_mapping[node] = representative

        # Add directed edges
        for ref_sj1, relation, ref_sj2 in relations:
            if relation in ('<', '>'):
                source = node_mapping.get(ref_sj1, ref_sj1)
                target = node_mapping.get(ref_sj2, ref_sj2)
                if relation == '<':
                    G.add_edge(source, target)
                elif relation == '>':
                    G.add_edge(target, source)

        # Cycle detection
        try:
            cycles = list(nx.find_cycle(G, orientation='original'))
            if cycles:
                flash('Cycle detected in relations! Matrix not generated.', 'danger')
                return redirect(url_for('hmatrix.harrismatrix'))
        except nx.NetworkXNoCycle:
            pass  # No cycle

        # Graph layout with inverted Y axis
        pos = nx.drawing.nx_pydot.graphviz_layout(G, prog='dot')
        for node in pos:
            x, y = pos[node]
            pos[node] = (x, -y)

        # Load stratigraphic unit types
        types_dict = {}
        with conn.cursor() as cur:
            cur.execute("SELECT id_sj, sj_typ FROM tab_sj")
            for id_sj, sj_typ in cur.fetchall():
                types_dict[id_sj] = sj_typ.lower()

        # Color mapping by type
        color_map = {
            'deposit': '#90EE90',
            'negative': '#FFA07A',
            'structure': '#87CEFA'
        }

        node_colors = []
        for node in G.nodes():
            node_type = types_dict.get(node, 'unknown')
            color = color_map.get(node_type, '#D3D3D3')
            node_colors.append(color)

        plt.figure(figsize=(12, 10))
        nx.draw(
            G, pos,
            with_labels=True,
            node_color=node_colors,
            node_size=2000,
            font_size=10,
            font_color='black',
            arrows=False
        )

        os.makedirs(Config.HARRISMATRIX_IMGS, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{selected_db}_{timestamp}.png"
        filepath = os.path.join(Config.HARRISMATRIX_IMGS, filename)

        plt.savefig(filepath, format="png", bbox_inches='tight')
        plt.close()

        session['harrismatrix_image'] = filename
        flash('Harris matrix generated successfully.', 'success')
        return redirect(url_for('hmatrix.harrismatrix'))

    except Exception as e:
        flash(f'Error while generating Harris Matrix: {str(e)}', 'danger')
        return redirect(url_for('hmatrix.harrismatrix'))

    finally:
        if conn:
            conn.close()
