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
        legacy_sql = re.sub(r'-- BEGIN SPATIAL MODEL\n.*?-- END SPATIAL MODEL\n',
                            '-- Legacy fixture\n', (ROOT/'db/create_db_template.sql').read_text(), flags=re.DOTALL)
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
        self.assertEqual(self.psql("SELECT count(*) FROM geometry_columns WHERE f_table_name LIKE 'v_gis_%';"),'24')

    def test_01_migration_preserves_geometry_pending_refs_and_manual_removal(self):
        self.assertEqual(self.psql('SELECT ST_AsEWKT(geom_top) FROM tab_polygons;'),self.original_polygon)
        self.assertEqual(self.psql('SELECT ST_NPoints(geom),build_method FROM tab_entity_geometries WHERE ref_section=10;'),'3|legacy_line')
        self.assertEqual(self.psql('SELECT geom IS NULL,legacy_point_ranges IS NOT NULL FROM tab_entity_geometries WHERE ref_find=10;'),'t|t')
        self.psql("DELETE FROM tab_entity_geometries WHERE ref_sample=10;")
        self.psql(file=ROOT/'db/migrations/20261009_spatial_representations.sql',user='app_terrain_db')
        self.psql(file=ROOT/'db/migrations/20261023_su_gis_editing.sql',user='app_terrain_db')
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
        shutil.copy2(ROOT/'db/apply_gis_access.sh',checkout/'db/apply_gis_access.sh')
        program="""
import os
import subprocess
import sys
os.chdir(sys.argv[1])
os.chmod(sys.argv[2],0o600)
try:
    assert not os.access(os.path.join(sys.argv[1],'db','migrations','20261009_spatial_representations.sql'),os.R_OK)
    assert os.access('db/migrations/20261009_spatial_representations.sql',os.R_OK)
    for flags in (['--terrain-only','--check'], ['--terrain-only']):
        result=subprocess.run(['bash','db/apply_gis_access.sh',*flags],capture_output=True,text=True)
        assert result.returncode==0, result.stdout+'\\n'+result.stderr
finally:
    os.chmod(sys.argv[2],0o700)
"""
        self.run_command([sys.executable,'-c',program,str(checkout),str(parent)],user='app_terrain_db')

    def test_06_template_creates_the_spatial_model_from_one_file(self):
        standalone=self.directory/'standalone'
        standalone.mkdir()
        template=standalone/'create_db_template.sql'
        template.write_text((ROOT/'db/create_db_template.sql').read_text().replace(
            'terrain_db_template','terrain_db_standalone'))
        self.psql(file=template,database='postgres')
        database='terrain_db_standalone'
        self.assertEqual(self.psql("""
            SELECT count(*) FROM information_schema.tables WHERE table_schema='public'
            AND table_name IN ('tab_entity_geometries','tab_geometry_geopts',
                'tab_spatial_files','tabaid_sj_spatial_files','tabaid_geometry_files');
        """,database=database),'5')
        self.assertEqual(self.psql("SELECT count(*) FROM geometry_columns WHERE f_table_name LIKE 'v_gis_%';",
                                  database=database),'24')
        self.psql("""SELECT set_project_srid(32633);
            INSERT INTO tab_sj(id_sj,sj_typ) VALUES (1,'deposit');
            INSERT INTO v_gis_point_z(ref_sj,geom)
            VALUES (1,ST_GeomFromText('POINT Z (500000 5500000 123)',32633));""",
            database=database,user='app_terrain_db')
        self.assertEqual(self.psql('SELECT ST_SRID(geom),ST_Z(geom) FROM tab_entity_geometries;',
                                  database=database),'32633|123')
        self.psql('GRANT CONNECT ON DATABASE terrain_db_standalone TO gis_rw;',database=database)
        self.psql("""INSERT INTO v_gis_su_point_z(id_sj,sj_typ,create_su,geom)
            VALUES (2,'deposit',1,ST_GeomFromText('POINT Z (500000 5500000 124)',32633));""",
            database=database,user='editor@example.invalid')
        self.assertEqual(self.psql('SELECT id_deposit FROM tab_sj_deposit WHERE id_deposit=2;',
                                  database=database),'2')

    def test_07_su_creation_is_atomic_and_representation_edits_preserve_the_unit(self):
        before=self.psql("SELECT row_to_json(g) FROM tab_entity_geometries g ORDER BY id_geometry;")
        # Reproduce the SU views already installed before the numeric flag change.
        self.psql("""SET ROLE own_terrain_db;
            DROP VIEW v_gis_su_point_xy;
            CREATE VIEW v_gis_su_point_xy AS
            SELECT g.id_geometry,g.ref_sj AS id_sj,s.sj_typ,false AS create_su,
                g.geometry_role,g.source_method,g.source_software,g.source_software_version,g.is_proxy,g.notes,
                g.created_at,g.updated_at,g.geom::geometry(Point,32633) AS geom
            FROM tab_entity_geometries g JOIN tab_sj s ON s.id_sj=g.ref_sj
            WHERE GeometryType(g.geom)='POINT' AND ST_CoordDim(g.geom)=2;""")
        for _ in range(2):
            self.psql(file=ROOT/'db/migrations/20261023_su_gis_editing.sql')
        self.assertEqual(self.psql("SELECT row_to_json(g) FROM tab_entity_geometries g ORDER BY id_geometry;"),before)
        self.assertEqual(self.psql("""SELECT count(*) FROM information_schema.columns
            WHERE table_schema='public' AND table_name LIKE 'v_gis_su_%'
            AND column_name IN ('create_su','is_proxy') AND data_type='integer';"""),'24')
        self.psql('SELECT set_project_srid(32633);',user='app_terrain_db')
        self.assertEqual(self.psql("SELECT count(*) FROM geometry_columns WHERE f_table_name LIKE 'v_gis_su_%' AND srid=32633;"),'12')
        for number,kind,table,column in [(701,'deposit','tab_sj_deposit','id_deposit'),
                                          (702,'negativ','tab_sj_negativ','id_negativ'),
                                          (703,'structure','tab_sj_structure','id_structure')]:
            self.psql(f"""INSERT INTO v_gis_su_linestring_z(id_sj,sj_typ,create_su,geom,source_software,is_proxy)
                VALUES ({number},'{kind}',1,ST_GeomFromText('LINESTRING Z (500000 5500000 100,500010 5500010 101)',32633),'QGIS',0);""",
                user='editor@example.invalid')
            self.assertEqual(self.psql(f'SELECT {column} FROM {table} WHERE {column}={number};'),str(number))
            self.assertEqual(self.psql(f'SELECT create_su,source_method,is_proxy FROM v_gis_su_linestring_z WHERE id_sj={number};'),'0|digitized|0')
        # A second representation of the same SU must be an explicit existing-SU insert.
        self.psql("""INSERT INTO v_gis_su_point_xy(id_sj,geom) VALUES (701,ST_GeomFromText('POINT (500000 5500000)',32633));""",
                  user='editor@example.invalid')
        self.assertEqual(self.psql('SELECT count(*) FROM tab_entity_geometries WHERE ref_sj=701;'),'2')
        self.psql("UPDATE v_gis_su_linestring_z SET geom=ST_Translate(geom,0,0,5) WHERE id_sj=701;",user='editor@example.invalid')
        self.assertEqual(self.psql('SELECT source_method,ST_Z(ST_StartPoint(geom)) FROM v_gis_su_linestring_z WHERE id_sj=701;'),'manual_edit|105')
        for values in [
            "(701,'deposit',1,ST_GeomFromText('POINT (0 0)',32633))",  # Existing number is never silently reused.
            "(704,'wrong',1,ST_GeomFromText('POINT (0 0)',32633))",
            "(704,NULL,1,ST_GeomFromText('POINT (0 0)',32633))",
            "(704,'deposit',0,ST_GeomFromText('POINT (0 0)',32633))",
            "(701,'structure',0,ST_GeomFromText('POINT (0 0)',32633))",
            "(704,'deposit',1,NULL)",
            "(704,'deposit',1,ST_GeomFromText('POINT (0 0)',4326))",
            "(704,'deposit',2,ST_GeomFromText('POINT (0 0)',32633))",
            "(704,'deposit',-1,ST_GeomFromText('POINT (0 0)',32633))",
        ]:
            self.psql(f'INSERT INTO v_gis_su_point_xy(id_sj,sj_typ,create_su,geom) VALUES {values};',
                      user='editor@example.invalid',expected=3)
        # Failure after base SU and subtype creation must roll back both rows.
        self.psql("""INSERT INTO v_gis_su_polygon_xy(id_sj,sj_typ,create_su,geom)
            VALUES (704,'deposit',1,ST_GeomFromText('POLYGON ((0 0,10 10,0 10,10 0,0 0))',32633));""",
            user='editor@example.invalid',expected=3)
        self.assertEqual(self.psql('SELECT (SELECT count(*) FROM tab_sj WHERE id_sj=704),'
                                  '(SELECT count(*) FROM tab_sj_deposit WHERE id_deposit=704);'),'0|0')
        self.psql("""INSERT INTO v_gis_su_point_xy(id_sj,sj_typ,create_su,is_proxy,geom)
            VALUES (704,'deposit',1,2,ST_GeomFromText('POINT (0 0)',32633));""",
            user='editor@example.invalid',expected=3)
        self.assertEqual(self.psql('SELECT count(*) FROM tab_sj WHERE id_sj=704;'),'0')
        for assignment in ['id_sj=702','id_geometry=99999',"sj_typ='structure'",'create_su=1',
                           'create_su=2','is_proxy=2','is_proxy=-1']:
            self.psql(f'UPDATE v_gis_su_linestring_z SET {assignment} WHERE id_sj=701;',
                      user='editor@example.invalid',expected=3)
        self.psql('DELETE FROM v_gis_su_linestring_z WHERE id_sj=701;',user='reader@example.invalid',expected=3)
        self.psql("""INSERT INTO v_gis_su_point_xy(id_sj,sj_typ,create_su,geom)
            VALUES (705,'deposit',1,ST_GeomFromText('POINT (0 0)',32633));""",user='reader@example.invalid',expected=3)
        self.assertEqual(self.psql('SELECT count(*) FROM tab_sj WHERE id_sj=705;'),'0')
        self.psql('DELETE FROM v_gis_su_linestring_z WHERE id_sj=701;',user='editor@example.invalid')
        self.assertEqual(self.psql('SELECT sj_typ FROM tab_sj WHERE id_sj=701;'),'deposit')
        self.assertEqual(self.psql('SELECT id_deposit FROM tab_sj_deposit WHERE id_deposit=701;'),'701')
        self.assertEqual(self.psql('SELECT count(*) FROM tab_entity_geometries WHERE ref_sj=701;'),'1')

    def test_08_native_qgis_provider_creates_edits_and_deletes_a_representation(self):
        probe=subprocess.run(['/usr/bin/python3','-c','import qgis.core'],capture_output=True)
        if probe.returncode:
            self.skipTest('The system Python does not have PyQGIS installed')
        program='''
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from qgis.core import QgsApplication, QgsDataSourceUri, QgsVectorLayer, QgsVectorLayerUtils, QgsGeometry, QgsVectorDataProvider, Qgis
from qgis.gui import QgsAttributeForm, QgsAttributeEditorContext, QgsEditorWidgetWrapper, QgsGui
from qgis.PyQt.QtWidgets import QDialogButtonBox, QAbstractSpinBox, QLineEdit, QWidget
app=QgsApplication([],True)
app.initQgis()
QgsGui.editorWidgetRegistry().initEditors()
uri=QgsDataSourceUri()
uri.setConnection(os.environ['PGHOST'],os.environ['PGPORT'],'01_Spatial','editor@example.invalid','')
uri.setDataSource('public','v_gis_su_linestring_z','geom','','id_geometry')
layer=QgsVectorLayer(uri.uri(False),'SU lines','postgres')
assert layer.isValid(), layer.error().message()
assert layer.dataProvider().capabilities() & QgsVectorDataProvider.AddFeatures
# Use the native form with no .qml, project configuration or custom widgets.
assert layer.startEditing()
feature=QgsVectorLayerUtils.createFeature(layer,
    QgsGeometry.fromWkt('LINESTRING Z (500000 5500000 110,500010 5500010 111)'))
for key,value in dict(id_sj=801,sj_typ='deposit',source_software_version=Qgis.QGIS_VERSION).items():
    feature[key]=value
# Exercise the real digitizing form, including its required key validation.
context=QgsAttributeEditorContext()
form=QgsAttributeForm(layer,feature,context)
form.setMode(QgsAttributeEditorContext.AddFeatureMode)
app.processEvents()
wrappers={}
for widget in form.findChildren(QWidget):
    wrapper=QgsEditorWidgetWrapper.fromWidget(widget)
    if wrapper:
        wrappers[layer.fields()[wrapper.fieldIdx()].name()]=wrapper
for name in ['create_su','is_proxy']:
    widget=wrappers[name].widget()
    spinbox=widget if isinstance(widget,QAbstractSpinBox) else widget.findChild(QAbstractSpinBox)
    lineedit=widget if isinstance(widget,QLineEdit) else widget.findChild(QLineEdit)
    assert int(wrappers[name].value())==(1 if name=='is_proxy' else 0)
    value=1 if name=='create_su' else 0
    if spinbox is not None:
        assert spinbox.isEnabled() and not spinbox.isReadOnly()
        spinbox.setValue(value)
    else:
        assert lineedit is not None and lineedit.isEnabled() and not lineedit.isReadOnly(), name+' must have an editable native input'
        lineedit.setText(str(value))
        assert lineedit.hasAcceptableInput()
assert form.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).isEnabled(), 'The digitizing form requires a manually entered key'
assert 'nextval(' in layer.dataProvider().defaultValueClause(layer.fields().indexOf('id_geometry'))
assert form.save(), 'The form must save without a manually entered ID'
form.deleteLater()
assert layer.commitChanges(), layer.commitErrors()
saved=next(f for f in layer.getFeatures() if f['id_sj']==801)
geometry_id=saved['id_geometry']
assert geometry_id>0
assert not saved['create_su']
assert not saved['is_proxy']
assert layer.startEditing()
assert layer.changeGeometry(saved.id(),QgsGeometry.fromWkt('LINESTRING Z (500000 5500000 120,500010 5500010 121)'))
assert layer.commitChanges(), layer.commitErrors()
saved=next(f for f in layer.getFeatures() if f['id_sj']==801)
assert saved['id_geometry']==geometry_id
assert saved['source_method']=='manual_edit'
assert saved.geometry().constGet().pointN(0).z()==120
uri.setConnection(os.environ['PGHOST'],os.environ['PGPORT'],'01_Spatial','reader@example.invalid','')
readonly=QgsVectorLayer(uri.uri(False),'SU read only','postgres')
assert readonly.isValid()
assert not (readonly.dataProvider().capabilities() & QgsVectorDataProvider.AddFeatures)
assert layer.startEditing()
assert layer.deleteFeature(saved.id())
assert layer.commitChanges(), layer.commitErrors()
assert not any(f['id_sj']==801 for f in layer.getFeatures())
print('QGIS '+Qgis.QGIS_VERSION+': create/update/delete round trip passed')
'''
        result=self.run_command(['/usr/bin/python3','-c',program])
        self.assertIn('round trip passed',result)
        self.assertEqual(self.psql('SELECT sj_typ FROM tab_sj WHERE id_sj=801;'),'deposit')
        self.assertEqual(self.psql('SELECT id_deposit FROM tab_sj_deposit WHERE id_deposit=801;'),'801')
        self.assertEqual(self.psql('SELECT count(*) FROM tab_entity_geometries WHERE ref_sj=801;'),'0')

    def test_09_qgis_renders_saved_su_and_general_views_in_project_crs(self):
        probe=subprocess.run(['/usr/bin/python3','-c','import qgis.core'],capture_output=True)
        if probe.returncode:
            self.skipTest('The system Python does not have PyQGIS installed')
        database='02_QgisRendering'
        self.psql(f'CREATE DATABASE "{database}" TEMPLATE terrain_db_template OWNER own_terrain_db;',database='postgres')
        self.psql(f'GRANT CONNECT ON DATABASE "{database}" TO gis_ro,gis_rw;',database=database)
        self.psql("""SELECT set_project_srid(5514);
            INSERT INTO tab_sj(id_sj,sj_typ) VALUES (901,'deposit');
            INSERT INTO tab_sj_deposit(id_deposit) VALUES (901);
            SELECT nextval('tab_entity_geometries_id_geometry_seq') FROM generate_series(1,10);""",database=database)
        program='''
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from qgis.core import (QgsApplication,QgsDataSourceUri,QgsVectorLayer,QgsVectorLayerUtils,
    QgsGeometry,QgsFeatureRequest,QgsRectangle,QgsCoordinateReferenceSystem,QgsCoordinateTransform,
    QgsProject,QgsMapSettings,QgsMapRendererSequentialJob,QgsLineSymbol,Qgis)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor
app=QgsApplication([],True)
app.initQgis()
def load(view,query=False):
    uri=QgsDataSourceUri()
    uri.setConnection(os.environ['PGHOST'],os.environ['PGPORT'],'02_QgisRendering','editor@example.invalid','')
    if query:
        uri.setDataSource('',f'(SELECT * FROM "public"."{view}")','geom','','id_geometry')
    else:
        uri.setDataSource('public',view,'geom','','id_geometry')
    layer=QgsVectorLayer(uri.uri(False),view,'postgres')
    assert layer.isValid(), layer.error().message()
    assert layer.crs().authid()=='EPSG:5514'
    layer.renderer().setSymbol(QgsLineSymbol.createSimple({'line_color':'255,0,0','line_width':'1'}))
    return layer
su=load('v_gis_su_linestring_xy')
general=load('v_gis_linestring_xy')
query_su=load('v_gis_su_linestring_xy',query=True)
su.featureCount()
general.featureCount()
su.extent()
general.extent()
area=QgsRectangle(-700010,-1050010,-699970,-1049970)
def render(layer):
    features=list(layer.getFeatures(QgsFeatureRequest().setFilterRect(area)))
    assert features, layer.name()+': no geometries returned for the visible map rectangle'
    assert all(f.hasGeometry() and not f.geometry().isEmpty() for f in features)
    settings=QgsMapSettings()
    settings.setLayers([layer])
    destination=QgsCoordinateReferenceSystem('EPSG:3857')
    settings.setDestinationCrs(destination)
    settings.setExtent(QgsCoordinateTransform(layer.crs(),destination,QgsProject.instance()).transformBoundingBox(area))
    settings.setOutputSize(QSize(256,256))
    settings.setBackgroundColor(QColor('white'))
    job=QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()
    assert not job.errors(), [e.message for e in job.errors()]
    result=job.renderedImage()
    pixels=sum(1 for y in range(result.height()) for x in range(result.width())
               if result.pixelColor(x,y).red()>150 and result.pixelColor(x,y).green()<100)
    assert pixels>20, layer.name()+': saved geometries are not rendered'
    return len(features)
assert su.startEditing()
feature=QgsVectorLayerUtils.createFeature(su,QgsGeometry.fromWkt('LINESTRING (-700000 -1050000,-699980 -1049980)'))
for name,value in dict(id_sj=902,sj_typ='structure',create_su=1,is_proxy=0,source_software='QGIS').items():
    feature[name]=value
assert su.addFeature(feature)
assert render(su)==1
assert su.commitChanges(False), su.commitErrors()
assert su.isEditable()
assert render(su)==1
assert render(general)==1
assert render(query_su)==1
# Force a sequence gap: a client must use the ID returned by the database.
import psycopg2
conn=psycopg2.connect(dbname='02_QgisRendering')
with conn:
    with conn.cursor() as cur:
        cur.execute("SELECT nextval('tab_entity_geometries_id_geometry_seq') FROM generate_series(1,5)")
conn.close()
assert general.startEditing()
feature=QgsVectorLayerUtils.createFeature(general,QgsGeometry.fromWkt('LINESTRING (-700000 -1049995,-699980 -1049985)'))
for name,value in dict(ref_sj=901,geometry_role='outline',source_method='digitized',is_proxy=False).items():
    feature[name]=value
assert general.addFeature(feature)
assert render(general)==2
assert general.commitChanges(False), general.commitErrors()
assert general.isEditable()
assert render(general)==2
for layer in [su,general,query_su,load('v_gis_su_linestring_xy'),load('v_gis_linestring_xy'),
              load('v_gis_su_linestring_xy',query=True)]:
    assert render(layer)==2
    features=list(layer.getFeatures())
    assert len({f['id_geometry'] for f in features})==2
    for feature in features:
        selected=list(layer.getFeatures(QgsFeatureRequest().setFilterFid(feature.id())))
        assert len(selected)==1 and selected[0].hasGeometry()
print('QGIS '+Qgis.QGIS_VERSION+': saved XY lines render through SU/general views in EPSG:5514 and EPSG:3857')
su.rollBack()
general.rollBack()
# Release provider layers before the application tears down the rendering stack.
su=general=query_su=layer=None
import gc
gc.collect()
app.exitQgis()
'''
        result=self.run_command(['/usr/bin/python3','-c',program],database=database)
        self.assertIn('saved XY lines render',result)

    def test_10_production_refresh_is_standalone_preflights_all_and_preserves_data(self):
        # Reproduce the deployed GIS baseline before SU layers and photogram authors.
        for database in ['01_Spatial','terrain_db_template']:
            self.psql("""DO $$ DECLARE v record; BEGIN
                FOR v IN SELECT viewname FROM pg_views WHERE schemaname='public'
                    AND viewname LIKE 'v_gis_su_%' LOOP
                    EXECUTE format('DROP VIEW public.%I',v.viewname);
                END LOOP;
                END $$;
                DROP FUNCTION refresh_su_geometry_views();
                DROP FUNCTION write_su_geometry_view();
                ALTER FUNCTION refresh_geometry_views() SECURITY INVOKER;
                ALTER TABLE tab_photograms DROP COLUMN author;""",database=database)
        self.psql("""ALTER TABLE tab_sj_negativ ADD COLUMN excav_extent text;
            UPDATE tab_sj_negativ SET excav_extent='retain-the-original-source-field' WHERE id_negativ=10;
            INSERT INTO v_gis_linestring_z(ref_sj,geom,source_method,source_software,is_proxy,notes)
            VALUES (11,ST_GeomFromText('LINESTRING Z (500000 5500000 111,500010 5500010 112)',32633),
                'manual_edit','CAD',false,'Preserve this edited representation');
            INSERT INTO tab_spatial_files(file_kind,original_name,storage_key,mime_type,file_size,checksum_sha256)
            VALUES ('cad_gis_source','source.dwg','retain-source-key','application/octet-stream',3,repeat('c',64));
            INSERT INTO tabaid_sj_spatial_files(ref_sj,ref_file)
            SELECT 11,id_file FROM tab_spatial_files WHERE storage_key='retain-source-key';""")
        original_geometry=self.psql('SELECT row_to_json(g) FROM tab_entity_geometries g ORDER BY id_geometry;')
        original_auth=self.psql('SELECT row_to_json(u) FROM app_users u ORDER BY mail;',database='auth_db')
        original_password=self.psql("SELECT rolpassword FROM pg_authid WHERE rolname='legacy@example.invalid';",database='postgres')
        package=self.directory/'production-refresh'
        package.mkdir()
        wrapper=package/'apply_gis_refresh_20261025.sh'
        migration=package/'20261025_refresh_gis.sql'
        shutil.copy2(ROOT/'db/apply_gis_refresh_20261025.sh',wrapper)
        shutil.copy2(ROOT/'db/migrations/20261025_refresh_gis.sql',migration)

        def run_refresh(*flags,expected=0):
            return self.run_command(['bash',str(wrapper),*flags],database='postgres',expected=expected)

        def author_count(database='01_Spatial'):
            return self.psql("""SELECT count(*) FROM information_schema.columns
                WHERE table_schema='public' AND table_name='tab_photograms' AND column_name='author';""",database=database)

        # A later bad target must prevent changes to the earlier, valid target.
        self.psql('CREATE DATABASE "99_NotArcheo";',database='postgres')
        run_refresh(expected=3)
        self.assertEqual(author_count(),'0')
        self.assertEqual(author_count('terrain_db_template'),'0')
        self.assertEqual(self.psql("SELECT count(*) FROM pg_views WHERE viewname LIKE 'v_gis_su_%';"),'0')
        self.psql('ALTER DATABASE "99_NotArcheo" ALLOW_CONNECTIONS false;',database='postgres')
        run_refresh('--check')
        self.assertEqual(author_count(),'0')

        # Exercise the preservation guard with deliberate corruption in a temporary SQL copy.
        clean_sql=migration.read_text()
        migration.write_text(clean_sql.replace('-- Refuse to commit if any existing record',
            "UPDATE public.tab_entity_geometries SET notes='unexpected corruption';\n-- Refuse to commit if any existing record"))
        failed=subprocess.run(['bash',str(wrapper),'--database','01_Spatial'],
                              text=True,capture_output=True,env=self.env)
        self.assertEqual(failed.returncode,3,failed.stdout+failed.stderr)
        self.assertIn('Existing data changed during refresh',failed.stderr)
        self.assertEqual(author_count(),'0')
        self.assertEqual(self.psql('SELECT row_to_json(g) FROM tab_entity_geometries g ORDER BY id_geometry;'),original_geometry)
        migration.write_text(clean_sql)

        run_refresh()
        self.assertEqual(author_count(),'1')
        self.assertEqual(author_count('terrain_db_template'),'1')
        self.assertEqual(self.psql('SELECT row_to_json(g) FROM tab_entity_geometries g ORDER BY id_geometry;'),original_geometry)
        self.assertEqual(self.psql("SELECT excav_extent FROM tab_sj_negativ WHERE id_negativ=10;"),'retain-the-original-source-field')
        self.assertEqual(self.psql("SELECT storage_key FROM tab_spatial_files WHERE original_name='source.dwg';"),'retain-source-key')
        self.assertEqual(self.psql("""SELECT count(*) FROM information_schema.columns WHERE table_name LIKE 'v_gis_su_%'
            AND column_name IN ('create_su','is_proxy') AND data_type='integer';"""),'24')
        self.assertEqual(self.psql("SELECT prosecdef FROM pg_proc WHERE oid='refresh_geometry_views()'::regprocedure;"),'t')
        self.assertEqual(self.psql("SELECT notes,author IS NULL FROM tab_photograms WHERE id_photogram='1_test.jpg';"),'|t')

        # Reapplying must also preserve an author assigned after the first refresh.
        self.psql("""INSERT INTO gloss_personalia(mail,name,group_role)
            VALUES ('author@example.invalid','Author','archeolog');
            UPDATE tab_photograms SET author='author@example.invalid' WHERE id_photogram='1_test.jpg';""")
        run_refresh()
        self.assertEqual(self.psql("SELECT author FROM tab_photograms WHERE id_photogram='1_test.jpg';"),'author@example.invalid')
        self.assertEqual(self.psql('SELECT row_to_json(u) FROM app_users u ORDER BY mail;',database='auth_db'),original_auth)
        self.assertEqual(self.psql("SELECT rolpassword FROM pg_authid WHERE rolname='legacy@example.invalid';",database='postgres'),original_password)
        self.psql("""INSERT INTO v_gis_su_point_z(id_sj,sj_typ,create_su,is_proxy,geom)
            VALUES (906,'negativ',1,0,ST_GeomFromText('POINT Z (500000 5500000 123)',32633));""",
            user='editor@example.invalid')
        self.assertEqual(self.psql('SELECT id_negativ FROM tab_sj_negativ WHERE id_negativ=906;'),'906')
        self.assertEqual(self.psql('SELECT is_proxy,ST_Z(geom) FROM tab_entity_geometries WHERE ref_sj=906;'),'f|123')


if __name__=='__main__':
    unittest.main(verbosity=2)
