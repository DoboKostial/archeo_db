# web_app/app/routes/su.py
import os
from datetime import datetime

import jwt
import networkx as nx
import matplotlib
matplotlib.use('Agg')  # <- backend without GUI (no Tk)
import matplotlib.pyplot as plt

from flask import (
    Blueprint, request, render_template, redirect, url_for, flash, session, send_from_directory
)

from config import Config
from app.logger import logger
from app.database import get_terrain_connection
from app.utils import require_selected_db, float_or_none, get_hmatrix_dirs
from app.queries import (
    count_sj_by_type,            # returns (sql, params)
    count_sj_by_type_all,        # returns SQL string
    count_total_sj,              # returns SQL string
    count_objects,               # returns SQL string
    count_sj_without_relation,   # returns SQL string
    fetch_stratigraphy_relations # executes & returns rows
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


@su_bp.route('/generate-harrismatrix', methods=['POST'])
@require_selected_db
def generate_harrismatrix():
    selected_db = session.get('selected_db')
    if not selected_db:
        flash('No database selected.', 'danger')
        return redirect(url_for('su.harrismatrix'))

    conn = None
    try:
        conn = get_terrain_connection(selected_db)

        # Load stratigraphic relations
        relations = fetch_stratigraphy_relations(conn)

        # Build graph
        G = nx.DiGraph()

        # Handle equality groups (=)
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

        # Map nodes to representatives
        node_mapping = {}
        for group in equals_groups:
            representative = min(group)
            for node in group:
                node_mapping[node] = representative

        # Add edges for < and >
        for ref_sj1, relation, ref_sj2 in relations:
            if relation in ('<', '>'):
                source = node_mapping.get(ref_sj1, ref_sj1)
                target = node_mapping.get(ref_sj2, ref_sj2)
                if relation == '<':
                    G.add_edge(source, target)
                elif relation == '>':
                    G.add_edge(target, source)

        # Detect cycles
        try:
            cycles = list(nx.find_cycle(G, orientation='original'))
            if cycles:
                flash('A cycle was detected in the relations! Matrix was not generated.', 'danger')
                return redirect(url_for('su.harrismatrix'))
        except nx.exception.NetworkXNoCycle:
            pass  # no cycle → OK

        # Layout (Y axis inverted)
        pos = nx.drawing.nx_pydot.graphviz_layout(G, prog='dot')
        for node in pos:
            x, y = pos[node]
            pos[node] = (x, -y)

        # Load SU types
        types_dict = {}
        with conn.cursor() as cur:
            cur.execute("SELECT id_sj, sj_typ FROM tab_sj")
            for id_sj, sj_typ in cur.fetchall():
                types_dict[id_sj] = sj_typ.lower()

        # Colors by type (support both 'negativ' and 'negative')
        color_map = {
            'deposit':   '#90EE90',
            'negativ':   '#FFA07A',
            'negative':  '#FFA07A',
            'structure': '#87CEFA',
        }

        node_colors = []
        for node in G.nodes():
            node_type = types_dict.get(node, 'unknown')
            node_colors.append(color_map.get(node_type, '#D3D3D3'))

        # Render graph
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

        # Target directory: under DATA_DIR/<db>/harrismatrix
        images_dir, _ = get_hmatrix_dirs(selected_db)
        os.makedirs(images_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{selected_db}_{timestamp}.png"
        filepath = os.path.join(images_dir, filename)

        plt.savefig(filepath, format="png", bbox_inches='tight')
        plt.close()

        # keep filename in session (if template needs it)
        session['harrismatrix_image'] = filename

        flash('Harris Matrix has been generated.', 'success')
        return redirect(url_for('su.harrismatrix'))

    except Exception as e:
        flash(f'Error while generating Harris Matrix: {str(e)}', 'danger')
        return redirect(url_for('su.harrismatrix'))
    finally:
        if conn:
            try: conn.close()
            except Exception: pass



@su_bp.route('/harrismatrix/img/<path:filename>')
@require_selected_db
def harrismatrix_image(filename):
    selected_db = session.get('selected_db')
    images_dir, _ = get_hmatrix_dirs(selected_db)
    return send_from_directory(images_dir, filename)
