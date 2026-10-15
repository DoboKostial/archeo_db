"""Opt-in integration tests in a disposable PostgreSQL cluster, never the live DB."""
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
BIN = Path('/usr/lib/postgresql/14/bin')


@unittest.skipUnless(os.environ.get('ARCHEODB_TEST_POSTGRES')=='1', 'Set ARCHEODB_TEST_POSTGRES=1 for disposable PostGIS tests')
class SpatialIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='archeodb-spatial-')
        cls.directory = Path(cls.tmp.name)
        cls.env = {**os.environ,'PGHOST':cls.tmp.name,'PGPORT':'55447','PGUSER':'postgres','PGDATABASE':'postgres'}
        for name in ('PGSERVICE','PGSERVICEFILE','PGPASSWORD'):
            cls.env.pop(name,None)
        cls.run_command([str(BIN/'initdb'),'-D',str(cls.directory/'cluster'),'-U','postgres',
                         '--auth-local=trust','--auth-host=scram-sha-256','--no-locale','-E','UTF8'])
        cls.run_command([str(BIN/'pg_ctl'),'-D',str(cls.directory/'cluster'),'-l',str(cls.directory/'log'),
                         '-o',f"-h '' -k {cls.tmp.name} -p 55447",'-w','start'])
        cls.addClassCleanup(cls.cleanup_cluster)
        cls.psql(file=ROOT/'db/create_auth_db.sql',database='postgres')
        # Recreate the pre-GIS auth state, including its wider email column.
        cls.psql("""
            DROP ROLE gis_role_manager, gis_ro, gis_rw;
            DROP VIEW public.v_app_login_users;
            ALTER TABLE public.app_users DROP COLUMN gis_enabled;
            ALTER TABLE public.app_users DROP CONSTRAINT app_users_mail_bytes_check;
            ALTER TABLE public.app_users ALTER COLUMN mail TYPE varchar(100);
            CREATE VIEW public.v_app_login_users AS
                SELECT mail,name,password_hash,group_role,last_login,enabled FROM public.app_users;
            ALTER VIEW public.v_app_login_users OWNER TO own_auth_db;
            GRANT SELECT ON public.v_app_login_users TO grp_app_auth_ro,grp_app_auth_rw,app_mobile_db;
            INSERT INTO public.app_users(mail,name,password_hash,group_role)
                VALUES ('legacy@example.invalid','Legacy','preserve-app-password-hash','archeolog');
        """,database='auth_db')
        # Provision the old terrain model and exercise all retained upgrades.
        legacy = cls.directory/'legacy.sql'
        legacy_sql = (ROOT/'db/create_db_template.sql').read_text().replace('\\ir spatial_model.sql','-- Legacy fixture')
        legacy_sql = re.sub(r'^GRANT .* TO gis_(?:ro|rw).*\n','',legacy_sql,flags=re.MULTILINE)
        legacy_sql = re.sub(r"^\s*'(FI|PR)',.*\n",'',legacy_sql,flags=re.MULTILINE)
        legacy.write_text(legacy_sql)
        cls.psql(file=legacy,database='postgres')
        cls.psql("""
            ALTER TABLE tab_sj DROP COLUMN excav_extent;
            ALTER TABLE tab_sj_negativ ADD COLUMN excav_extent text;
            ALTER TABLE tab_photograms DROP COLUMN datum;
            ALTER TABLE tab_finds ALTER COLUMN count SET NOT NULL;
            ALTER TABLE tab_finds ALTER COLUMN box SET NOT NULL;
        """,database='terrain_db_template')
        cls.psql('CREATE DATABASE "01_Spatial" TEMPLATE terrain_db_template OWNER own_terrain_db;',database='postgres')
        cls.psql("""
            SELECT set_project_srid(32633);
            INSERT INTO tab_sj(id_sj) VALUES (10),(11),(12);
            INSERT INTO tab_sj_negativ(id_negativ,excav_extent) VALUES (10,'whole');
            INSERT INTO tab_geopts(id_pts,x,y,h,code) VALUES
              (1,500000,5500000,100,'SU'),(2,500010,5500000,101,'SU'),
              (3,500010,5500010,102,'SU'),(4,500000,5500010,103,'SU'),
              (5,500002,5500002,100,'SU'),(6,500002,5500004,100,'SU'),
              (7,500004,5500004,100,'SU'),(8,500004,5500002,100,'SU');
            INSERT INTO tab_polygons(polygon_name,allocation_reason,geom_top)
              VALUES ('legacy','other',ST_GeomFromText('POLYGON Z ((500000 5500000 100,500010 5500000 101,500010 5500010 102,500000 5500000 100))',32633));
            INSERT INTO tab_polygon_geopts_binding_top(ref_polygon,pts_from,pts_to) VALUES ('legacy',1,4);
            INSERT INTO tab_section(id_section,section_type) VALUES (10,'standard');
            INSERT INTO tab_section_geopts_binding(ref_section,pts_from,pts_to) VALUES (10,1,3);
            INSERT INTO gloss_find_type(type_code) VALUES ('test');
            INSERT INTO gloss_sample_type(type_code) VALUES ('test');
            INSERT INTO tab_finds(id_find,ref_find_type,ref_sj,ref_geopt,count,box) VALUES (10,'test',10,99,2,3);
            INSERT INTO tab_samples(id_sample,ref_sample_type,ref_sj,ref_geopt) VALUES (10,'test',10,1);
            INSERT INTO tab_photograms(id_photogram,photogram_typ,mime_type,file_size,checksum_sha256)
              VALUES ('1_test.jpg','other','image/jpeg',3,repeat('a',64));
        """)
        cls.original_polygon = cls.psql('SELECT ST_AsEWKT(geom_top) FROM tab_polygons;')
        cls.psql("INSERT INTO app_users(mail,name,password_hash,group_role) VALUES ('"+'ž'*30+"@example.invalid','Too long','hash','analyst');",database='auth_db')
        cls.upgrade('--include-legacy','--check',expected=1)
        assert cls.psql("SELECT count(*) FROM pg_roles WHERE rolname='gis_rw';",database='postgres')=='0'
        cls.psql("DELETE FROM app_users WHERE name='Too long';",database='auth_db')
        cls.upgrade('--include-legacy','--check')
        assert cls.psql("SELECT count(*) FROM pg_roles WHERE rolname='gis_rw';",database='postgres')=='0'
        cls.upgrade('--include-legacy')
        cls.psql("UPDATE app_users SET gis_enabled=true WHERE mail='legacy@example.invalid'; SELECT gis_admin.set_password('legacy@example.invalid','IntegrationGis123');",database='auth_db',user='app_terrain_db')
        cls.original_gis_password=cls.psql("SELECT rolpassword FROM pg_authid WHERE rolname='legacy@example.invalid';",database='postgres')
        cls.upgrade('--terrain-only','--check',user='app_terrain_db')
        cls.upgrade('--terrain-only',user='app_terrain_db')
        cls.psql('CREATE ROLE "editor@example.invalid" LOGIN; GRANT gis_rw TO "editor@example.invalid"; '
                 'CREATE ROLE "reader@example.invalid" LOGIN; GRANT gis_ro TO "reader@example.invalid";',database='postgres')
        cls.psql('GRANT CONNECT ON DATABASE "01_Spatial" TO gis_rw,gis_ro;')
        cls.psql(file=ROOT/'db/migrations/20261009_gis_write_access.sql')
        cls.psql(file=ROOT/'db/migrations/20261004_gis_access.sql')

    @classmethod
    def upgrade(cls,*flags,user='postgres',expected=0):
        return cls.run_command(['bash',str(ROOT/'db/apply_gis_access.sh'),*flags],
                               database='auth_db',user=user,expected=expected)

    @classmethod
    def cleanup_cluster(cls):
        cls.run_command([str(BIN/'pg_ctl'),'-D',str(cls.directory/'cluster'),'-m','fast','-w','stop'])
        cls.tmp.cleanup()

    @classmethod
    def run_command(cls,args,sql=None,database='01_Spatial',user='postgres',expected=0):
        result = subprocess.run(args,input=sql,text=True,capture_output=True,
                                env={**cls.env,'PGDATABASE':database,'PGUSER':user})
        if result.returncode != expected:
            raise AssertionError(f'{args}: {result.returncode}\n{result.stdout}\n{result.stderr}')
        return result.stdout.strip()

    @classmethod
    def psql(cls,sql=None,file=None,database='01_Spatial',user='postgres',expected=0):
        args = [str(BIN/'psql'),'-X','-w','-Atq','-v','ON_ERROR_STOP=1']
        if file:
            args += ['-f',str(file)]
        return cls.run_command(args,sql,database,user,expected)

    def test_00_full_upgrade_is_repeatable_and_preserves_accounts_and_legacy_data(self):
        self.upgrade('--include-legacy')
        self.assertEqual(self.psql("SELECT password_hash,gis_enabled FROM app_users WHERE mail='legacy@example.invalid';",database='auth_db'),'preserve-app-password-hash|t')
        self.assertEqual(self.psql("SELECT rolpassword FROM pg_authid WHERE rolname='legacy@example.invalid';",database='postgres'),self.original_gis_password)
        self.assertEqual(self.psql("SELECT pg_has_role('legacy@example.invalid','gis_rw','member'),has_database_privilege('legacy@example.invalid','01_Spatial','CONNECT'),has_database_privilege('legacy@example.invalid','auth_db','CONNECT'),has_database_privilege('legacy@example.invalid','terrain_db_template','CONNECT');"),'t|t|f|f')
        self.assertEqual(self.psql("SELECT rolcreaterole FROM pg_roles WHERE rolname='app_terrain_db';"),'f')
        self.assertEqual(self.psql('SELECT excav_extent FROM tab_sj WHERE id_sj=10;'),'100')
        self.assertEqual(self.psql("SELECT datum=CURRENT_DATE,file_size FROM tab_photograms WHERE id_photogram='1_test.jpg';"),'t|3')
        self.assertEqual(self.psql("SELECT count,box FROM tab_finds WHERE id_find=10;"),'2|3')
        self.assertEqual(self.psql("SELECT string_agg(is_nullable,',' ORDER BY column_name) FROM information_schema.columns WHERE table_name='tab_finds' AND column_name IN ('count','box');"),'YES,YES')
        self.assertEqual(self.psql("SELECT 'FI'::geopt_code,'PR'::geopt_code;"),'FI|PR')
        self.assertEqual(self.psql('SELECT count(*) FROM tab_entity_geometries;',database='terrain_db_template'),'0')
        self.assertEqual(self.psql("SELECT count(*) FROM geometry_columns WHERE f_table_name LIKE 'v_gis_%';"),'12')

    def test_01_migration_preserves_geometry_pending_refs_and_manual_removal(self):
        self.assertEqual(self.psql('SELECT ST_AsEWKT(geom_top) FROM tab_polygons;'),self.original_polygon)
        self.assertEqual(self.psql('SELECT ST_NPoints(geom),build_method FROM tab_entity_geometries WHERE ref_section=10;'),'3|legacy_line')
        self.assertEqual(self.psql('SELECT geom IS NULL,legacy_point_ranges IS NOT NULL FROM tab_entity_geometries WHERE ref_find=10;'),'t|t')
        self.psql("DELETE FROM tab_entity_geometries WHERE ref_sample=10;")
        self.psql(file=ROOT/'db/migrations/20261009_spatial_representations.sql',user='app_terrain_db')
        self.assertEqual(self.psql('SELECT count(*) FROM tab_entity_geometries WHERE ref_sample=10;'),'0')
        self.assertEqual(self.psql('SELECT ST_AsEWKT(geom_top) FROM tab_polygons;'),self.original_polygon)
        self.psql("INSERT INTO tab_geopts(id_pts,x,y,h,code) VALUES (99,500005,5500005,105,'FI');")
        self.psql('SELECT build_entity_geometry(id_geometry) FROM tab_entity_geometries WHERE ref_find=10;',user='editor@example.invalid')
        self.assertEqual(self.psql('SELECT ST_Z(geom),source_method FROM tab_entity_geometries WHERE ref_find=10;'),'105|survey_points')

    def test_02_ordered_polygon_holes_native_edit_and_rebuild_protection(self):
        self.psql("""INSERT INTO tab_entity_geometries(id_geometry,ref_sj,geometry_role,build_method,build_geometry_type)
          VALUES(100,10,'outline','ordered_polygon','Polygon');
          INSERT INTO tab_geometry_geopts(ref_geometry,part_no,ring_no,point_order,ref_geopt)
          SELECT 100,1,0,n,n FROM generate_series(1,4) n UNION ALL
          SELECT 100,1,1,n-4,n FROM generate_series(5,8) n;
          SELECT build_entity_geometry(100);""",user='editor@example.invalid')
        self.assertEqual(self.psql('SELECT ST_NumInteriorRings(geom),ST_Z(ST_PointN(ST_ExteriorRing(geom),2)) FROM tab_entity_geometries WHERE id_geometry=100;'),'1|101')
        self.psql("UPDATE v_gis_polygon_z SET geom=ST_Translate(geom,0,0,5),source_software='QGIS',source_software_version='test' WHERE id_geometry=100;",user='editor@example.invalid')
        before=self.psql('SELECT ST_AsEWKT(geom) FROM tab_entity_geometries WHERE id_geometry=100;')
        self.assertEqual(self.psql('SELECT source_method FROM tab_entity_geometries WHERE id_geometry=100;'),'manual_edit')
        self.psql('SELECT build_entity_geometry(100);',user='editor@example.invalid',expected=3)
        self.assertEqual(self.psql('SELECT ST_AsEWKT(geom) FROM tab_entity_geometries WHERE id_geometry=100;'),before)
        self.psql('SELECT build_entity_geometry(100,true);',user='editor@example.invalid')
        self.assertEqual(self.psql('SELECT source_method,source_software,ST_Z(ST_PointN(ST_ExteriorRing(geom),2)) FROM tab_entity_geometries WHERE id_geometry=100;'),'survey_points|ArcheoDB|101')
        # Invalid point order must leave the saved geometry unchanged.
        self.psql('BEGIN; UPDATE tab_geometry_geopts SET ref_geopt=1 WHERE ref_geometry=100 AND ring_no=0; SELECT build_entity_geometry(100,true); COMMIT;',expected=3)
        self.assertEqual(self.psql('SELECT ST_NumInteriorRings(geom) FROM tab_entity_geometries WHERE id_geometry=100;'),'1')

    def test_03_typed_view_creation_multigeometry_and_constraints(self):
        self.psql("INSERT INTO v_gis_point_xy(ref_sj,geom,source_software) VALUES (11,ST_SetSRID(ST_MakePoint(500001,5500001),32633),'CAD');",user='editor@example.invalid')
        self.assertEqual(self.psql('SELECT ST_CoordDim(geom),source_method FROM tab_entity_geometries WHERE ref_sj=11;'),'2|digitized')
        self.psql("""INSERT INTO tab_entity_geometries(id_geometry,ref_sj,build_method,build_geometry_type)
          VALUES(101,12,'ordered_line','MultiLineString');
          INSERT INTO tab_geometry_geopts(ref_geometry,part_no,ring_no,point_order,ref_geopt)
          VALUES(101,1,0,1,1),(101,1,0,2,2),(101,2,0,1,3),(101,2,0,2,4);
          SELECT build_entity_geometry(101);""",user='editor@example.invalid')
        self.assertEqual(self.psql('SELECT GeometryType(geom),ST_NumGeometries(geom),ST_CoordDim(geom) FROM tab_entity_geometries WHERE id_geometry=101;'),'MULTILINESTRING|2|3')
        for sql in [
            "INSERT INTO tab_entity_geometries(ref_find,geometry_role,geom) VALUES (10,'location',ST_SetSRID(ST_MakePoint(1,2),32633));",
            "INSERT INTO tab_entity_geometries(ref_sample,geometry_role,geom) VALUES (10,'location',ST_GeomFromText('LINESTRING (0 0,1 1)',32633));",
            "INSERT INTO tab_entity_geometries(ref_sj,geom) VALUES (11,ST_SetSRID(ST_MakePoint(1,2),4326));",
            "INSERT INTO tab_entity_geometries(ref_sj,ref_find) VALUES (11,10);",
            "DELETE FROM tab_geopts WHERE id_pts=1;",
            "UPDATE v_gis_point_xy SET id_geometry=9999 WHERE ref_sj=11;",
        ]:
            self.psql(sql,user='editor@example.invalid',expected=3)
        self.psql('DELETE FROM v_gis_point_xy WHERE ref_sj=11;',user='reader@example.invalid',expected=3)
        self.psql('SELECT set_project_srid(32633);')
        self.assertEqual(self.psql('SELECT ST_CoordDim(geom) FROM v_gis_point_xy WHERE ref_sj=11;'),'2')
        # Existing mobile clients still build new polygon entities from ranges.
        self.psql("""INSERT INTO tab_polygons(polygon_name,allocation_reason) VALUES ('mobile','other');
          INSERT INTO tab_polygon_geopts_binding_top(ref_polygon,pts_from,pts_to) VALUES ('mobile',1,4);
          SELECT rebuild_polygon_geoms_from_geopts('mobile');""",user='app_terrain_db')
        self.assertEqual(self.psql("SELECT source_method FROM tab_entity_geometries WHERE ref_polygon='mobile';"),'survey_points')

    def test_04_web_workflow_exports_files_and_access(self):
        # Run with web_app/venv/bin/python so Flask and psycopg2 are available.
        sys.path.insert(0,str(ROOT/'web_app'))
        import psycopg2
        import app as app_package
        from app import create_app
        from app.routes import spatial as routes
        from app.utils.tokens import create_session_token
        from config import Config
        app=create_app()
        app.config.update(TESTING=True,WTF_CSRF_ENABLED=False)
        client=app.test_client()
        client.set_cookie('token',create_session_token('editor@example.invalid','Editor','archeolog',lifetime_minutes=5))
        with client.session_transaction() as state:
            state['selected_db']='01_Spatial'
        class Auth:
            def close(self): pass
        def connection(_name):
            return psycopg2.connect(dbname='01_Spatial',user='app_terrain_db',host=self.tmp.name,port=55447)
        with patch.object(app_package,'get_auth_connection',return_value=Auth()), \
             patch.object(app_package,'get_user_access_state',return_value=('Editor','archeolog',True)), \
             patch.object(routes,'get_terrain_connection',side_effect=connection), \
             patch.object(Config,'DATA_DIR',str(self.directory/'media')), \
             patch.object(Config,'UPLOAD_FOLDER',str(self.directory/'uploads')):
            response=client.get('/spatial/geojson')
            self.assertEqual(response.status_code,200,response.data)
            self.assertTrue(response.json['features'])
            response=client.post('/spatial/entities/su/11',json={'geometry_type':'MultiPoint','geometry_role':'location',
                'build_method':'point','is_proxy':False,'points':[{'ref_geopt':1},{'ref_geopt':2,'part_no':2}]})
            self.assertEqual(response.status_code,200,response.data)
            geometry_id=response.json['id_geometry']
            response=client.post(f'/spatial/entities/su/11/geometries/{geometry_id}/rebuild',json={'replace_manual':True})
            self.assertEqual(response.status_code,200,response.data)
            self.assertEqual(client.post('/spatial/entities/su/11',json=['invalid']).status_code,400)
            response=client.get('/spatial/entities/su/11')
            self.assertEqual(response.status_code,200,response.data)
            self.assertEqual(len(response.json['geometries']),2)
            response=client.get('/spatial/summary/su')
            self.assertEqual(response.status_code,200,response.data)
            self.assertEqual(next(r['count'] for r in response.json['rows'] if r['entity_id']=='11'),2)
            response=client.get('/spatial/export?kind=su')
            self.assertEqual(response.status_code,200,response.data)
            archive=zipfile.ZipFile(io.BytesIO(response.data))
            self.assertTrue(any(n.endswith('_z_32633.shp') for n in archive.namelist()))
            response=client.post('/spatial/entities/su/11/files',data={'id_geometry':str(geometry_id),
                'source_software':'AutoCAD','source_software_version':'2026','file':(io.BytesIO(b'CAD source'),'original.dwg')})
            self.assertEqual(response.status_code,200,response.data)
            source_id=response.json['id_file']
            with client.get(f'/spatial/files/{source_id}') as downloaded:
                self.assertEqual(downloaded.data,b'CAD source')
            response=client.post('/spatial/entities/su/10/files',json={'id_file':source_id})
            self.assertEqual(response.status_code,200,response.data)
            response=client.post('/spatial/entities/photogram/1_test.jpg/files',data={'file':(io.BytesIO(b'NaN\n0\n0\n1\n0\n0'),'test.jgw')})
            self.assertEqual(response.status_code,400,response.data)
            world=b'1\n0\n0\n-1\n500000\n5500000\n'
            response=client.post('/spatial/entities/photogram/1_test.jpg/files',data={'file':(io.BytesIO(world),'test.jgw')})
            self.assertEqual(response.status_code,200,response.data)
            self.assertEqual(self.psql("SELECT has_world_file FROM tab_photograms WHERE id_photogram='1_test.jpg';"),'t')
            raster=self.directory/'media'/'01_Spatial'/Config.MEDIA_DIRS['photograms']/'1_test.jpg'
            raster.parent.mkdir(parents=True,exist_ok=True);raster.write_bytes(b'JPG')
            response=client.get('/spatial/photograms/1_test.jpg/pair')
            self.assertEqual(response.status_code,200,response.data)
            pair=zipfile.ZipFile(io.BytesIO(response.data))
            self.assertEqual(pair.read('1_test.jgw'),world)
            self.assertEqual(pair.read('1_test.jpg'),b'JPG')
            response=client.post('/spatial/rebuild/su',json={})
            self.assertEqual(response.status_code,400)
            response=client.post('/spatial/rebuild/su',json={'confirmed':True})
            self.assertEqual(response.status_code,200,response.data)
            self.assertEqual(response.json['skipped'],1)
            response=client.delete('/spatial/entities/photogram/1_test.jpg/files',json={})
            self.assertEqual(response.status_code,200,response.data)
            self.assertEqual(self.psql("SELECT has_world_file FROM tab_photograms WHERE id_photogram='1_test.jpg';"),'f')
            response=client.delete(f'/spatial/entities/su/11/geometries/{geometry_id}')
            self.assertEqual(response.status_code,200,response.data)
            for path in ['/spatial/map','/spatial/points?q=1&code=SU']:
                self.assertEqual(client.get(path).status_code,200,path)
            with patch.object(app_package,'get_user_access_state',return_value=('Reader','analyst',True)):
                self.assertEqual(client.post('/spatial/entities/su/10',json={}).status_code,403)
                self.assertEqual(client.get('/spatial/geojson').status_code,200)
            with client.session_transaction() as state:
                state.pop('selected_db')
            self.assertEqual(client.get('/spatial/geojson').status_code,302)

    def test_05_relative_migration_paths_work_without_access_to_parent_directory(self):
        # Reproduce sudo inheriting a cwd below a home directory it cannot traverse.
        parent=self.directory/'restricted-parent'
        checkout=parent/'checkout'
        checkout.mkdir(parents=True)
        shutil.copytree(ROOT/'db/migrations',checkout/'db/migrations')
        for name in ('apply_gis_access.sh','spatial_model.sql'):
            shutil.copy2(ROOT/'db'/name,checkout/'db'/name)
        program="""
import os
import subprocess
import sys
os.chdir(sys.argv[1])
os.chmod(sys.argv[2],0o600)
try:
    assert not os.access(os.path.join(sys.argv[1],'db','spatial_model.sql'),os.R_OK)
    assert os.access('db/spatial_model.sql',os.R_OK)
    for flags in (['--terrain-only','--check'], ['--terrain-only']):
        result=subprocess.run(['bash','db/apply_gis_access.sh',*flags],capture_output=True,text=True)
        assert result.returncode==0, result.stdout+'\\n'+result.stderr
finally:
    os.chmod(sys.argv[2],0o700)
"""
        self.run_command([sys.executable,'-c',program,str(checkout),str(parent)],user='app_terrain_db')


if __name__=='__main__':
    unittest.main(verbosity=2)
