# web_app/app/routes/archeo_objects.py
import io
from flask import (
    Blueprint, request, render_template, redirect, url_for,
    flash, session, jsonify, make_response
)
from weasyprint import HTML

from app.logger import logger
from app.database import get_terrain_connection
from app.utils.decorators import require_selected_db
#from config import Config  # (nepoužito nyní, ale nevadí mít)

archeo_objects_bp = Blueprint('archeo_objects', __name__)


@archeo_objects_bp.route('/objects', methods=['GET', 'POST'])
@require_selected_db
def objects():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    try:
        # Next suggested object id
        cur.execute("SELECT COALESCE(MAX(id_object), 0) + 1 FROM tab_object;")
        suggested_id = cur.fetchone()[0]

        # Object types for dropdown
        cur.execute("SELECT object_typ FROM gloss_object_type ORDER BY object_typ;")
        object_types = [row[0] for row in cur.fetchall()]

        form_data = {}

        if request.method == 'POST':
            try:
                # Read & validate form inputs
                id_object = int(request.form.get('id_object'))
                object_typ = request.form.get('object_typ')
                superior_object = request.form.get('superior_object') or None
                notes = request.form.get('notes')
                sj_ids_raw = request.form.getlist('sj_ids[]')  # list of SUs

                # Must be unique
                cur.execute("SELECT 1 FROM tab_object WHERE id_object = %s;", (id_object,))
                if cur.fetchone():
                    flash(f"Object #{id_object} already exists.", "warning")
                    raise ValueError("Duplicate object id.")

                # At least two SUs per object
                if len(sj_ids_raw) < 2:
                    flash("Object must contain at least two stratigraphic units (SUs).", "warning")
                    raise ValueError("Insufficient number of SUs.")

                # Validate SUs exist
                sj_ids = []
                for sj_id_str in sj_ids_raw:
                    try:
                        sj_id = int(sj_id_str)
                        cur.execute("SELECT 1 FROM tab_sj WHERE id_sj = %s;", (sj_id,))
                        if not cur.fetchone():
                            flash(f"SU #{sj_id} does not exist.", "danger")
                            raise ValueError(f"Nonexistent SU {sj_id}.")
                        sj_ids.append(sj_id)
                    except ValueError:
                        flash(f"Invalid SU number: {sj_id_str}", "danger")
                        raise

                # Insert object
                cur.execute("""
                    INSERT INTO tab_object (id_object, object_typ, superior_object, notes)
                    VALUES (%s, %s, %s, %s)
                """, (id_object, object_typ, superior_object, notes))

                # Update SUs to reference this object
                for sj_id in sj_ids:
                    cur.execute(
                        "UPDATE tab_sj SET ref_object = %s WHERE id_sj = %s",
                        (id_object, sj_id)
                    )

                conn.commit()
                logger.info(f"Object #{id_object} created in DB '{selected_db}'.")
                flash(f"Object #{id_object} has been created.", "success")
                return redirect(url_for('archeo_objects.objects'))

            except Exception as e:
                conn.rollback()
                logger.error(f"Error while saving object in DB '{selected_db}': {e}")
                form_data = request.form.to_dict(flat=True)

        return render_template(
            "objects.html",
            suggested_id=suggested_id,
            object_types=object_types,
            selected_db=selected_db,
            form_data=form_data
        )

    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass


@archeo_objects_bp.route('/define-object-type', methods=['POST'])
@require_selected_db
def define_object_type():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    data = request.get_json() or {}
    new_type = (data.get('object_typ') or '').strip()
    description = (data.get('description_typ') or '').strip()

    if not new_type:
        logger.warning(f"Attempt to create empty object type in DB '{selected_db}'.")
        return jsonify({'error': 'Object type name is missing.'}), 400

    try:
        cur.execute(
            "INSERT INTO gloss_object_type (object_typ, description_typ) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
            (new_type, description)
        )
        conn.commit()
        logger.info(f"Added new object type '{new_type}' (desc: '{description}') into DB '{selected_db}'.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error while saving object type '{new_type}' into DB '{selected_db}': {e}")
        return jsonify({'error': f'Error while saving: {str(e)}'}), 500
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass

    return jsonify({'message': f"Type '{new_type}' has been saved."}), 200


@archeo_objects_bp.route('/list-objects')
@require_selected_db
def list_objects():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT o.id_object, o.object_typ, o.superior_object, o.notes,
                   ARRAY_AGG(s.id_sj ORDER BY s.id_sj) AS sj_ids
            FROM tab_object o
            LEFT JOIN tab_sj s ON s.ref_object = o.id_object
            GROUP BY o.id_object
            ORDER BY o.id_object;
        """)
        objects = cur.fetchall()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error loading objects from DB '{selected_db}': {e}")
        flash(f"Error while loading objects: {e}", "danger")
        objects = []
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass

    return render_template('list_objects.html', objects=objects)


@archeo_objects_bp.route('/generate-objects-pdf', methods=['POST'])
@require_selected_db
def generate_objects_pdf():
    selected_db = session['selected_db']
    conn = get_terrain_connection(selected_db)
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT o.id_object, o.object_typ, o.superior_object, o.notes,
                   ARRAY(SELECT s.id_sj FROM tab_sj s WHERE s.ref_object = o.id_object ORDER BY s.id_sj)
            FROM tab_object o
            ORDER BY o.id_object;
        """)
        objects = cur.fetchall()
    except Exception as e:
        logger.error(f"Error while generating PDF from DB '{selected_db}': {e}")
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        flash(f"Error while generating PDF: {e}", "danger")
        return redirect(url_for('archeo_objects.objects'))
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass

    # Render HTML for PDF
    rendered = render_template('pdf_objects.html', objects=objects)
    pdf_io = io.BytesIO()
    HTML(string=rendered).write_pdf(pdf_io)
    pdf_io.seek(0)

    # Return PDF
    response = make_response(pdf_io.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=objects.pdf'
    return response
