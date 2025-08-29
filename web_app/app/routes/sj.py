# app/routes/sj.py

from flask import Blueprint, render_template, request, session, flash
from datetime import datetime
from app.utils.decorators import require_selected_db
from app.database import get_terrain_connection
from app.queries.sj import (
    get_next_sj_id, get_authors, count_sj_total,
    count_sj_by_type, insert_sj_basic, insert_sj_deposit,
    insert_sj_negativ, insert_sj_structure, insert_sj_stratigraphy
)
from app.utils.helpers import float_or_none
import logging

sj_bp = Blueprint('sj_bp', __name__)
logger = logging.getLogger(__name__)

@sj_bp.route('/add-sj', methods=['GET', 'POST'])
@require_selected_db
def add_sj():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    # Get next available SJ ID
    cur.execute(get_next_sj_id())
    suggested_id = cur.fetchone()[0]

    # Get authors
    cur.execute(get_authors())
    authors = [row[0] for row in cur.fetchall()]

    # Overview stats
    cur.execute(count_sj_total())
    sj_count_total = cur.fetchone()[0]

    cur.execute(*count_sj_by_type('deposit'))
    sj_count_deposit = cur.fetchone()[0]

    cur.execute(*count_sj_by_type('negativ'))
    sj_count_negativ = cur.fetchone()[0]

    cur.execute(*count_sj_by_type('structure'))
    sj_count_structure = cur.fetchone()[0]

    form_data = {}

    if request.method == 'POST':
        try:
            id_sj = int(request.form.get('id_sj'))
            cur.execute("SELECT 1 FROM tab_sj WHERE id_sj = %s;", (id_sj,))
            if cur.fetchone():
                flash(f"ID of strat. unit #{id_sj} already exists. Provide another ID.", "warning")
                form_data = request.form.to_dict(flat=True)
                return render_template('sj/add_sj.html', **locals())

            # Basic info
            sj_typ = request.form.get('sj_typ')
            description = request.form.get('description')
            interpretation = request.form.get('interpretation')
            author = request.form.get('author')
            recorded = datetime.now()
            docu_plan = 'docu_plan' in request.form
            docu_vertical = 'docu_vertical' in request.form

            cur.execute(insert_sj_basic(), (id_sj, sj_typ, description, interpretation, author, recorded, docu_plan, docu_vertical))

            # Insert into type-specific table
            if sj_typ == 'deposit':
                cur.execute(insert_sj_deposit(), (
                    id_sj,
                    request.form.get('deposit_typ'),
                    request.form.get('color'),
                    request.form.get('boundary_visibility'),
                    request.form.get('structure'),
                    request.form.get('compactness'),
                    'deposit_removed' in request.form
                ))
            elif sj_typ == 'negativ':
                cur.execute(insert_sj_negativ(), (
                    id_sj,
                    request.form.get('negativ_typ'),
                    request.form.get('excav_extent'),
                    'ident_niveau_cut' in request.form,
                    request.form.get('shape_plan'),
                    request.form.get('shape_sides'),
                    request.form.get('shape_bottom')
                ))
            elif sj_typ == 'structure':
                cur.execute(insert_sj_structure(), (
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
                flash("Nonvalid type of strat. unit.", "danger")
                form_data = request.form.to_dict(flat=True)
                return render_template('sj/add_sj.html', **locals())

            # Stratigraphic relations
            relations = {
                '>': [request.form.get('above_1'), request.form.get('above_2')],
                '<': [request.form.get('below_1'), request.form.get('below_2')],
                '=': [request.form.get('equal')],
            }

            for rel, lst in relations.items():
                for val in lst:
                    if val:
                        try:
                            target = int(val)
                            cur.execute(insert_sj_stratigraphy(), (id_sj, rel, target) if rel != '>' else (target, '<', id_sj))
                        except ValueError:
                            flash(f"Invalid SJ ID '{val}' for relation '{rel}' – not saved.", "warning")

        except Exception as e:
            conn.rollback()
            flash(f"Error while saving SJ: {e}", "danger")
            form_data = request.form.to_dict(flat=True)
        else:
            conn.commit()
            flash(f"Stratigraphic unit #{id_sj} successfully saved.", "success")

    cur.close()
    conn.close()

    return render_template('sj/add_sj.html', **locals())
