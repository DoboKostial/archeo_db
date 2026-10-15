"""Shared geometry editor, overview map and spatial attachments."""
from io import BytesIO
import os
from pathlib import Path
import uuid
import zipfile

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, abort, g, jsonify, render_template, request, send_file, session

from app import queries as q
from app.database import get_terrain_connection
from app.logger import logger
from app.utils.decorators import require_selected_db
from app.utils import storage
from app.utils.spatial import SOURCE_EXTENSIONS, WORLD_EXTENSIONS, shapefile_zip, validate_world_file
from app.utils.validators import sha256_file
from config import Config


spatial_bp = Blueprint('spatial', __name__, url_prefix='/spatial')
TYPES = {'Point','MultiPoint','LineString','MultiLineString','Polygon','MultiPolygon'}
ROLES = {'location','outline','top','bottom','extent','section_trace','other'}


@spatial_bp.before_request
@require_selected_db
def prepare_spatial_request():
    if request.method != 'GET' and getattr(g,'user_role','') not in {'archeolog','documentator'}:
        return jsonify(error='Geometry editing requires archeolog or documentator access.'),403
    g.spatial_conn = get_terrain_connection(session['selected_db'])
    with g.spatial_conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(q.spatial_ready_sql())
        if not cur.fetchone()['ready']:
            return jsonify(error='Apply the spatial representations migration to this terrain database first.'),503


@spatial_bp.teardown_request
def close_spatial_request(_error):
    conn = getattr(g,'spatial_conn',None)
    if conn is not None:
        conn.close()


@spatial_bp.errorhandler(ValueError)
def invalid_spatial_request(error):
    return jsonify(error=str(error)),400


@spatial_bp.errorhandler(psycopg2.Error)
def failed_spatial_request(error):
    logger.error('Spatial operation failed in %s: %s',session.get('selected_db'),error)
    return jsonify(error=error.diag.message_primary or 'Database operation failed.'),409


def cursor():
    return g.spatial_conn.cursor(cursor_factory=RealDictCursor)


def check_kind(kind):
    if kind not in q.SPATIAL_ENTITIES:
        abort(404)
    return kind


def lock_entity(cur,kind,key):
    check_kind(kind)
    cur.execute(q.spatial_entity_sql(kind),(key,))
    if not cur.fetchone():
        abort(404)


def lock_geometry(cur,kind,key,geometry_id):
    cur.execute(q.spatial_lock_sql(check_kind(kind)),(geometry_id,key))
    row = cur.fetchone()
    if not row:
        abort(404)
    return row


def selected_ids():
    ids = request.args.getlist('id')
    return ids or None


def json_payload():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload,dict):
        raise ValueError('The request body must be a JSON object.')
    return payload


@spatial_bp.get('/summary/<kind>')
def summary(kind):
    with cursor() as cur:
        cur.execute(q.spatial_summary_sql(check_kind(kind)))
        return jsonify(rows=cur.fetchall())


@spatial_bp.get('/points')
def points():
    term = '%'+request.args.get('q','').strip()+'%'
    code = request.args.get('code','').strip()
    with cursor() as cur:
        cur.execute(q.spatial_points_sql(),(term,term,code,code))
        return jsonify(rows=cur.fetchall())


@spatial_bp.get('/entities/<kind>/<path:key>')
def entity(kind,key):
    with cursor() as cur:
        lock_entity(cur,kind,key)
        cur.execute(q.spatial_geometries_sql(kind),(key,))
        geometries = cur.fetchall()
        for row in geometries:
            row.pop('geom',None)
            cur.execute(q.spatial_files_sql(kind,True),(row['id_geometry'],))
            row['files'] = cur.fetchall()
        files = []
        if kind in ('su','photogram'):
            cur.execute(q.spatial_files_sql(kind),(key,))
            files = cur.fetchall()
        return jsonify(geometries=geometries,files=files)


@spatial_bp.post('/entities/<kind>/<path:key>')
def define(kind,key):
    payload = json_payload()
    geom_type = payload.get('geometry_type')
    method = payload.get('build_method')
    allowed = {'Point':{'point'},'MultiPoint':{'point'},'LineString':{'ordered_line'},
               'MultiLineString':{'ordered_line'},'Polygon':{'ordered_polygon','convex_hull'},
               'MultiPolygon':{'ordered_polygon','convex_hull'}}
    if not isinstance(geom_type,str) or geom_type not in TYPES or not isinstance(method,str) or method not in allowed[geom_type]:
        raise ValueError('Select a supported geometry type and construction method.')
    role = payload.get('geometry_role')
    if not isinstance(role,str) or role not in ROLES or not isinstance(payload.get('is_proxy'),bool):
        raise ValueError('Select a geometry meaning and specify whether it is approximate.')
    sources = payload.get('points',[])
    if not isinstance(sources,list) or not 1 <= len(sources) <= 10000:
        raise ValueError('Select between 1 and 10000 source points.')
    geometry_id = payload.get('id_geometry')
    with cursor() as cur:
        lock_entity(cur,kind,key)
        values = (role,payload['is_proxy'],payload.get('notes') or None,method,geom_type)
        if geometry_id:
            lock_geometry(cur,kind,key,geometry_id)
            cur.execute(q.spatial_update_recipe_sql(),(*values,geometry_id))
            cur.execute(q.spatial_delete_points_sql(),(geometry_id,))
        else:
            cur.execute(q.spatial_insert_sql(kind),(key,*values))
            geometry_id = cur.fetchone()['id_geometry']
        orders = {}
        for point in sources:
            try:
                part,ring,point_id = int(point.get('part_no',1)),int(point.get('ring_no',0)),int(point['ref_geopt'])
            except (TypeError,ValueError,KeyError,AttributeError):
                raise ValueError('Invalid point selection.') from None
            orders[(part,ring)] = orders.get((part,ring),0)+1
            cur.execute(q.spatial_insert_point_sql(),(geometry_id,part,ring,orders[(part,ring)],point_id))
        cur.execute(q.spatial_build_sql(),(geometry_id,payload.get('replace_manual') is True))
    g.spatial_conn.commit()
    return jsonify(id_geometry=geometry_id)


@spatial_bp.post('/entities/<kind>/<path:key>/geometries/<int:geometry_id>/rebuild')
def rebuild(kind,key,geometry_id):
    payload = json_payload()
    with cursor() as cur:
        lock_geometry(cur,kind,key,geometry_id)
        cur.execute(q.spatial_build_sql(),(geometry_id,payload.get('replace_manual') is True))
    g.spatial_conn.commit()
    return jsonify(ok=True)


@spatial_bp.delete('/entities/<kind>/<path:key>/geometries/<int:geometry_id>')
def remove_geometry(kind,key,geometry_id):
    with cursor() as cur:
        lock_geometry(cur,kind,key,geometry_id)
        cur.execute(q.spatial_delete_sql(),(geometry_id,))
    g.spatial_conn.commit()
    return jsonify(ok=True)


@spatial_bp.route('/rebuild/<kind>',methods=['GET','POST'])
def rebuild_all(kind):
    check_kind(kind)
    payload = json_payload()
    ids = payload.get('ids') if request.method=='POST' else selected_ids()
    if ids is not None and (not isinstance(ids,list) or any(not isinstance(i,str) for i in ids)):
        raise ValueError('Invalid entity selection.')
    with cursor() as cur:
        cur.execute(q.spatial_bulk_sql(kind),(ids,ids))
        rows = cur.fetchall()
        if request.method=='GET':
            return jsonify(total=len(rows),buildable=sum(bool(r['build_method']) for r in rows),
                           manual=sum(r['has_geometry'] and r['source_method']!='survey_points' for r in rows))
        if payload.get('confirmed') is not True:
            raise ValueError('Confirm rebuilding the selected geometries.')
        built,skipped,errors = 0,0,[]
        for row in rows:
            if not row['build_method']:
                skipped += 1
                continue
            cur.execute(q.spatial_savepoint_sql('start'))
            try:
                cur.execute(q.spatial_build_sql(),(row['id_geometry'],True))
                built += 1
            except psycopg2.Error as error:
                cur.execute(q.spatial_savepoint_sql('rollback'))
                errors.append({'id':row['id_geometry'],'entity_id':row['entity_id'],'error':error.diag.message_primary})
            finally:
                cur.execute(q.spatial_savepoint_sql('release'))
    g.spatial_conn.commit()
    return jsonify(built=built,skipped=skipped,errors=errors)


@spatial_bp.get('/map')
def map_view():
    kind = request.args.get('kind') or None
    if kind:
        check_kind(kind)
    return render_template('spatial_map.html',kind=kind,selected_db=session['selected_db'])


@spatial_bp.get('/geojson')
def geojson():
    kind = request.args.get('kind') or None
    if kind:
        check_kind(kind)
    ids = selected_ids()
    with cursor() as cur:
        cur.execute(q.spatial_features_sql(kind),(ids,ids))
        rows = cur.fetchall()
        if not kind and not ids:
            cur.execute(q.spatial_measured_features_sql())
            rows.extend(cur.fetchall())
    return jsonify(type='FeatureCollection',features=[{'type':'Feature','geometry':r.pop('geometry'),'properties':r} for r in rows])


@spatial_bp.get('/export')
def export():
    kind = request.args.get('kind') or None
    if kind:
        check_kind(kind)
    ids = selected_ids()
    with cursor() as cur:
        cur.execute(q.spatial_features_sql(kind,False),(ids,ids))
        rows = cur.fetchall()
        projections = {}
        for srid in {r['srid'] for r in rows}:
            cur.execute(q.spatial_prj_sql(),(srid,))
            row = cur.fetchone()
            projections[srid] = row['srtext'] if row else None
    if not rows:
        raise ValueError('No geometry to export in this selection.')
    return send_file(shapefile_zip(rows,projections),mimetype='application/zip',as_attachment=True,
                     download_name=f"{session['selected_db']}_{kind or 'map'}.zip")


def attachment_path(storage_key):
    return storage.safe_join(Config.DATA_DIR,session['selected_db'],'spatial_files',storage_key)


@spatial_bp.route('/entities/<kind>/<path:key>/files',methods=['POST','DELETE'])
def attach_file(kind,key):
    """Attach uploaded or existing source files to a representation or an SU."""
    payload = request.form if request.method=='POST' and not request.is_json else json_payload()
    geometry_id = payload.get('id_geometry') or None
    is_world = kind=='photogram' and not geometry_id
    created_path = None
    with cursor() as cur:
        lock_entity(cur,kind,key)
        if geometry_id:
            lock_geometry(cur,kind,key,geometry_id)
        elif kind not in ('su','photogram'):
            raise ValueError('Select a representation before attaching a source file.')
        if request.method=='DELETE':
            if is_world:
                cur.execute(q.spatial_world_update_sql(),(None,key))
            else:
                cur.execute(q.spatial_file_link_sql(bool(geometry_id),True),(geometry_id or key,payload.get('id_file')))
            g.spatial_conn.commit()
            return jsonify(ok=True)
        file_id = payload.get('id_file')
        try:
            if file_id:
                cur.execute(q.spatial_file_sql(),(file_id,))
                row = cur.fetchone()
                if not row or row['file_kind'] != ('world_file' if is_world else 'cad_gis_source'):
                    raise ValueError('The selected attachment has the wrong file kind.')
            else:
                upload = request.files.get('file')
                if upload is None or not upload.filename:
                    raise ValueError('Select a file to upload.')
                original = os.path.basename(upload.filename.replace('\\','/'))
                extension = Path(original).suffix.lower()
                if extension not in (WORLD_EXTENSIONS if is_world else SOURCE_EXTENSIONS):
                    raise ValueError('Unsupported attachment extension. Upload Shapefile components together in a ZIP.')
                if is_world:
                    validate_world_file(storage.read_upload_bytes(upload,64*1024))
                temp,size = storage.save_to_uploads(Config.UPLOAD_FOLDER,upload)
                try:
                    checksum = sha256_file(temp)
                    storage_key = uuid.uuid4().hex+extension
                    created_path = attachment_path(storage_key)
                    storage.move_into_place(temp,created_path)
                finally:
                    storage.cleanup_upload(temp)
                cur.execute(q.spatial_file_insert_sql(),('world_file' if is_world else 'cad_gis_source',
                    original,storage_key,'text/plain' if is_world else 'application/octet-stream',size,checksum,
                    payload.get('source_software') or None,payload.get('source_software_version') or None,payload.get('notes') or None))
                file_id = cur.fetchone()['id_file']
            if is_world:
                cur.execute(q.spatial_world_update_sql(),(file_id,key))
            else:
                cur.execute(q.spatial_file_link_sql(bool(geometry_id)),(geometry_id or key,file_id))
            g.spatial_conn.commit()
        except Exception:
            if created_path:
                storage.cleanup_upload(created_path)
            raise
    return jsonify(id_file=file_id)


@spatial_bp.get('/files/<int:file_id>')
def download_file(file_id):
    with cursor() as cur:
        cur.execute(q.spatial_file_sql(),(file_id,))
        row = cur.fetchone()
    if not row or not os.path.isfile(attachment_path(row['storage_key'])):
        abort(404)
    return send_file(attachment_path(row['storage_key']),as_attachment=True,download_name=row['original_name'],
                     mimetype='application/octet-stream')


@spatial_bp.get('/photograms/<path:key>/pair')
def photogram_pair(key):
    with cursor() as cur:
        lock_entity(cur,'photogram',key)
        cur.execute(q.spatial_files_sql('photogram'),(key,))
        world = cur.fetchone()
    if not world:
        raise ValueError('This photogram has no world file.')
    storage.validate_pk(key)
    image,_ = storage.final_paths(Config.DATA_DIR,session['selected_db'],Config.MEDIA_DIRS['photograms'],key)
    world_path = attachment_path(world['storage_key'])
    if not os.path.isfile(image) or not os.path.isfile(world_path):
        abort(404)
    extension = {'.jpg':'.jgw','.jpeg':'.jgw','.png':'.pgw','.tif':'.tfw','.tiff':'.tfw'}.get(Path(key).suffix.lower(),'.wld')
    result = BytesIO()
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(image,key)
        archive.write(world_path,str(Path(key).with_suffix(extension)))
    result.seek(0)
    return send_file(result,as_attachment=True,download_name=Path(key).stem+'_world.zip',mimetype='application/zip')
