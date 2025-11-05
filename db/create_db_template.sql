-- This is basix SQL script for making database structure
--- ArcheoDB project; author dobo@dobo.sk


---
-- extensions needed
---
CREATE EXTENSION IF NOT EXISTS postgis;


---
-- BASIX ROLES AND PRIVILEGES
-- making database with owner grp_dbas creating all tables under this account

CREATE ROLE grp_dbas WITH CREATEDB INHERIT;
GRANT pg_write_all_data TO grp_dbas;
CREATE ROLE grp_analysts WITH INHERIT;
GRANT pg_read_all_data TO grp_analysts;
CREATE ROLE app_terrain_db WITH LOGIN;
ALTER ROLE app_terrain_db WITH createdb;
GRANT grp_dbas TO app_terrain_db;

-- This database is intended to be a template while assuming
-- cluster would server for more terrain DBs. After template creation You are able to create new database with 'CREATE DATABASE XYZ WITH TEMPLATE = 'terrain_db_template;''
CREATE DATABASE terrain_db_template OWNER app_terrain_db ENCODING 'UTF8' IS_TEMPLATE true;

-- Connect to the template database to configure it
\c terrain_db_template;

-- default privileges for users
ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO app_terrain_db;
ALTER DEFAULT PRIVILEGES GRANT ALL ON SEQUENCES TO app_terrain_db;
ALTER DEFAULT PRIVILEGES GRANT ALL ON FUNCTIONS TO app_terrain_db;
ALTER DEFAULT PRIVILEGES GRANT ALL ON TYPES TO app_terrain_db;
ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO app_terrain_db;

CREATE EXTENSION IF NOT EXISTS postgis;

SET ROLE app_terrain_db;



--###### TABLES definitions here #######
-- #### Glossaries as tables #####
--######################################

---
-- GLOSSARIES
---

-- gloss_docu_typ definition
CREATE TABLE gloss_docu_typ (
	docu_typ VARCHAR(60) NOT NULL,
	description VARCHAR(200) NULL,
	CONSTRAINT gloss_docu_typ_pk PRIMARY KEY (docu_typ)
);

-- gloss_object_type definition - glossary for archaeological objects
CREATE TABLE gloss_object_type (
	object_typ VARCHAR(100) NOT NULL,
	description_typ VARCHAR(200) NULL,
	CONSTRAINT gloss_object_type_pk PRIMARY KEY (object_typ)
);


-- gloss personalia definition - people 
CREATE TABLE gloss_personalia (
	mail VARCHAR(100) NOT NULL,
	"name" VARCHAR(150) NOT NULL,
	group_role VARCHAR(40) NOT NULL,
	CONSTRAINT gloss_personalia_pkey PRIMARY KEY (mail)
);


------
-- ### HERE MAIN TABLES - TERRAIN ENTITIES
------

---
-- tab_cut definition
---
CREATE TABLE tab_cut (
	id_cut int4 NOT NULL,
	description TEXT NULL,
	CONSTRAINT tab_cut_pk PRIMARY KEY (id_cut)
);

---
-- tab_geopts definition
---
CREATE TABLE tab_geopts (
  id_pts   int4    PRIMARY KEY,
  x        double precision NOT NULL,   -- more precise than numeric
  y        double precision NOT NULL,
  h        double precision NOT NULL,
  code     text,
  notes    text,
  pts_geom geometry(Point)              -- bez SRID; set_project_srid will define this
);

CREATE UNIQUE INDEX tab_geopts_id_pts_idx ON tab_geopts (id_pts);
CREATE INDEX tab_geopts_geom_gix ON tab_geopts USING GIST (pts_geom) WHERE pts_geom IS NOT NULL;


---
-- tab_object definition
---
CREATE TABLE tab_object (
	id_object int4 NOT NULL,
	object_typ VARCHAR(100) NULL,
	superior_object int4 NULL DEFAULT 0,
	notes TEXT NULL,
	CONSTRAINT tab_object_pk PRIMARY KEY (id_object)
);

---
-- tab_polygon definition
---
CREATE TABLE tab_polygons (
    id SERIAL PRIMARY KEY,
    polygon_name TEXT NOT NULL,
    geom geometry(Polygon) -- SRID is not defined; this will be overwriten during specific DB creation
);
-- this is table for storing info of what points are measured for polygon
-- can not perform referential integrity with tab_geopts (point from total station usually come at the end),
-- so integrity is done by application means
CREATE TABLE IF NOT EXISTS tab_polygon_geopts_binding (
  id          serial PRIMARY KEY,
  ref_polygon int  NOT NULL REFERENCES tab_polygons(id) ON UPDATE CASCADE ON DELETE CASCADE,
  pts_from    int  NOT NULL,
  pts_to      int  NOT NULL,
  CHECK (pts_from <= pts_to)
);
CREATE INDEX IF NOT EXISTS tab_polygon_geopts_binding_idx
  ON tab_polygon_geopts_binding(ref_polygon, pts_from, pts_to);

---
-- tab_sj_stratigraphy definition
---
CREATE TABLE tab_sj_stratigraphy (
	id_aut serial4 NOT NULL,
	ref_sj1 int4 NULL,
	relation CHAR(1) NULL,
	ref_sj2 int4 NULL,
	CONSTRAINT relation_type_check CHECK (((relation)::text = ANY ((ARRAY['<'::character, '>'::character, '='::character])::text[]))),
	CONSTRAINT tab_sj_stratigraphy_pk PRIMARY KEY (id_aut)
);


---
-- tab_sj definition
---

CREATE TABLE tab_sj (
	id_sj int4 NOT NULL,
	sj_typ VARCHAR(20) NULL,
	description TEXT NULL,
	interpretation TEXT NULL,
	author VARCHAR(100) NULL,
	recorded date NULL,
	docu_plan bool NULL,
	docu_vertical bool NULL,
	ref_object int4 NULL,
	CONSTRAINT tab_sj_pk PRIMARY KEY (id_sj)
);
CREATE UNIQUE INDEX tab_sj_id_sj_idx ON tab_sj USING btree (id_sj);
-- tab_sj foreign keys
ALTER TABLE tab_sj ADD CONSTRAINT tab_sj_fk FOREIGN KEY (author) REFERENCES gloss_personalia(mail);

---
-- tab_sj_deposit definition
---
CREATE TABLE tab_sj_deposit (
	id_deposit int4 NOT NULL,
	deposit_typ VARCHAR(20) NULL,
	color VARCHAR(50) NULL,
	boundary_visibility VARCHAR(50) NULL,
	"structure" VARCHAR(80) NULL,
	compactness VARCHAR(50) NULL,
	deposit_removed VARCHAR(50) NULL,
	CONSTRAINT tab_sj_deposit_pk PRIMARY KEY (id_deposit),
	CONSTRAINT tab_sj_deposit_fk FOREIGN KEY (id_deposit) REFERENCES tab_sj(id_sj)
);
CREATE UNIQUE INDEX tab_sj_deposit_id_deposit_idx ON tab_sj_deposit USING btree (id_deposit);

---
-- tab_sj_negativ definition
---
CREATE TABLE tab_sj_negativ (
	id_negativ int4 NOT NULL,
	negativ_typ VARCHAR(40) NULL,
	excav_extent VARCHAR(40) NULL,
	ident_niveau_cut bool NULL,
	shape_plan VARCHAR(50) NULL,
	shape_sides VARCHAR(50) NULL,
	shape_bottom VARCHAR(50) NULL,
	CONSTRAINT tab_sj_negativ_pk PRIMARY KEY (id_negativ),
	CONSTRAINT tab_sj_negativ_fk FOREIGN KEY (id_negativ) REFERENCES tab_sj(id_sj)
);
CREATE UNIQUE INDEX tab_sj_negativ_id_negativ_idx ON tab_sj_negativ USING btree (id_negativ);

---
-- tab_sj_structure definition
---
CREATE TABLE tab_sj_structure (
	id_structure int4 NOT NULL,
	structure_typ VARCHAR(80) NULL,
	construction_typ VARCHAR(100) NULL,
	binder VARCHAR(60) NULL,
	basic_material VARCHAR(60) NULL,
	length_m float8 NULL,
	width_m float8 NULL,
	height_m float8 NULL,
	CONSTRAINT tab_sj_structure_pk PRIMARY KEY (id_structure),
	CONSTRAINT tab_sj_structure_fk FOREIGN KEY (id_structure) REFERENCES tab_sj(id_sj)
);
CREATE UNIQUE INDEX tab_sj_structure_id_structure_idx ON tab_sj_structure USING btree (id_structure);


--========================================
-- ### HERE MAIN TABLES - DOCU ENTITIES
--========================================

---
-- tab_photos definition
---
CREATE TABLE tab_photos (
  id_photo        varchar(150) PRIMARY KEY,
  photo_typ       varchar(60)  NOT NULL,
  datum           date         NOT NULL,
  author          varchar(100) NOT NULL REFERENCES gloss_personalia(mail),
  notes           text,
  mime_type       text         NOT NULL,
  file_size       bigint       NOT NULL CHECK (file_size >= 0),
  checksum_sha256 text         NOT NULL,
  shoot_datetime  timestamptz,
  gps_lat         double precision,
  gps_lon         double precision,
  gps_alt         double precision,
  exif_json        jsonb        DEFAULT '{}'::jsonb,
  photo_centroid  geometry(Point)   -- SRID not defined ("empty"); after creating new DB will be changed by update_geometry_srid()
  -- Validation PK and MIME:
  CONSTRAINT tab_photos_id_format_chk CHECK (id_photo ~ '^[0-9]+_[A-Za-z0-9._-]+\.[a-z0-9]+$'),
  CONSTRAINT tab_photos_mime_chk CHECK (mime_type IN ('image/jpg','image/jpeg','image/png','image/tiff','image/svg+xml','application/pdf'))
);
CREATE INDEX tab_photos_author_idx ON tab_photos (author);
CREATE INDEX tab_photos_datum_idx ON tab_photos (datum);
CREATE INDEX tab_photos_checksum_idx ON tab_photos (checksum_sha256);
CREATE INDEX tab_photos_shoot_dt_idx ON tab_photos (shoot_datetime);
-- index only for not null geometries
CREATE INDEX tab_photos_centroid_gix ON tab_photos USING GIST (photo_centroid) WHERE photo_centroid IS NOT NULL;



---
-- tab_sketches definition
---
CREATE TABLE tab_sketches (
  id_sketch        VARCHAR(120) PRIMARY KEY,                      
  sketch_typ       VARCHAR(80)  NOT NULL,
  author           VARCHAR(100) NOT NULL REFERENCES gloss_personalia(mail),
  datum            date,
  notes            text,
  mime_type        text         NOT NULL,
  file_size        bigint       NOT NULL CHECK (file_size >= 0),
  checksum_sha256  text         NOT NULL,

  -- PK a MIME validation:
  CONSTRAINT tab_sketches_id_format_chk
    CHECK (id_sketch ~ '^[0-9]+_[A-Za-z0-9._-]+\.[a-z0-9]+$'),
  CONSTRAINT tab_sketches_mime_chk
    CHECK (mime_type IN ('image/jpeg','image/png','image/tiff','image/svg+xml','application/pdf'))
);
-- indexes
CREATE INDEX tab_sketches_author_idx     ON tab_sketches (author);
CREATE INDEX tab_sketches_datum_idx      ON tab_sketches (datum);
CREATE INDEX tab_sketches_checksum_idx   ON tab_sketches (checksum_sha256);

---
-- tab_drawings definition
---

CREATE TABLE tab_drawings (
  id_drawing       VARCHAR(120) PRIMARY KEY,                       
  author           VARCHAR(100) NOT NULL REFERENCES gloss_personalia(mail),
  datum            date         NOT NULL,
  notes            text,
  mime_type        text         NOT NULL,
  file_size        bigint       NOT NULL CHECK (file_size >= 0),
  checksum_sha256  text         NOT NULL,
  -- mime and PK validation:
  CONSTRAINT tab_drawings_id_format_chk CHECK (id_drawing ~ '^[0-9]+_[A-Za-z0-9._-]+\.[a-z0-9]+$'),
  CONSTRAINT tab_drawings_mime_chk CHECK (mime_type IN ('image/jpeg','image/png','image/tiff','image/svg+xml','application/pdf'))
);
-- indexes:
CREATE INDEX tab_drawings_author_idx     ON tab_drawings (author);
CREATE INDEX tab_drawings_datum_idx      ON tab_drawings (datum);
CREATE INDEX tab_drawings_checksum_idx   ON tab_drawings (checksum_sha256);


CREATE TABLE tab_photograms (
  id_photogram     VARCHAR(120) PRIMARY KEY,                       
  photogram_typ    VARCHAR(60)  NOT NULL,
  ref_sketch       VARCHAR(120) NULL REFERENCES tab_sketches(id_sketch)
                                 ON UPDATE CASCADE ON DELETE SET NULL,
  notes            text,
  mime_type        text         NOT NULL,
  file_size        bigint       NOT NULL CHECK (file_size >= 0),
  checksum_sha256  text         NOT NULL,
  -- mime and PK validation:
  CONSTRAINT tab_photograms_id_format_chk
    CHECK (id_photogram ~ '^[0-9]+_[A-Za-z0-9._-]+\.[a-z0-9]+$'),
  CONSTRAINT tab_photograms_mime_chk
    CHECK (mime_type IN ('image/jpeg','image/png','image/tiff','image/svg+xml','application/pdf'))
);
-- indexes:
CREATE INDEX tab_photograms_ref_sketch_idx ON tab_photograms (ref_sketch);
CREATE INDEX tab_photograms_checksum_idx   ON tab_photograms (checksum_sha256);


-- tab_sack definition
-- sacks are containers for finds

CREATE TABLE tab_sack (
	id_sack int4 NOT NULL,
	ref_sj int4 NULL,
	"content" TEXT NULL,
	description TEXT NULL,
	"number" int4 NULL,
	CONSTRAINT tab_sack_pk PRIMARY KEY (id_sack),
	CONSTRAINT tab_sack_fk FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj)
);


--==========================================================
-- TABAIDS - table helpers for M:N relations between tables
--==========================================================

-- tabaid_photo_sj definition
-- this table connects photos and SUs (stratigraphic units)
CREATE TABLE tabaid_photo_sj (
	id_aut serial4 NOT NULL,
	ref_photo VARCHAR(120) NOT NULL,
	ref_sj int4 NOT NULL,
	CONSTRAINT tabaid_photo_sj_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_photo_sj_fk_photo FOREIGN KEY (ref_photo) REFERENCES tab_photos(id_photo) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tabaid_photo_sj_fk_sj FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE
    );
CREATE UNIQUE INDEX tabaid_photo_sj_unique_idx ON tabaid_photo_sj(ref_sj, ref_photo);
CREATE INDEX tabaid_photo_sj_ref_photo_idx ON tabaid_photo_sj(ref_photo);

   
-- tabaid_sj_drawings definition
-- this table connects drawings and SUs (stratigraphic units)
CREATE TABLE tabaid_sj_drawings (
	id_aut serial4 NOT NULL,
	ref_drawing VARCHAR(120) NOT NULL,
	ref_sj int4 NOT NULL,
	CONSTRAINT tabaid_sj_drawings_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_sj_drawings_fk_drawing FOREIGN KEY (ref_drawing) REFERENCES tab_drawings(id_drawing) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tabaid_sj_drawings_fk_sj FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX tabaid_sj_drawings_unique_idx ON tabaid_sj_drawings(ref_sj, ref_drawing);
CREATE INDEX tabaid_sj_drawings_ref_drawing_idx ON tabaid_sj_drawings(ref_drawing);


-- tabaid_cut_photogram definition
-- this table connects cuts and photograms (m:n)
CREATE TABLE tabaid_cut_photogram (
	id_aut serial4 NOT NULL,
	ref_cut int4 NOT NULL,
	ref_photogram VARCHAR(100) NOT NULL,
	CONSTRAINT tabaid_cut_photogram_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_cut_photogram_fk_photogram FOREIGN KEY (ref_photogram) REFERENCES tab_photograms(id_photogram) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tabaid_cut_photogram_fk_cut FOREIGN KEY (ref_cut) REFERENCES tab_cut(id_cut) ON DELETE CASCADE ON UPDATE CASCADE
);

-- tabaid_photogram_photo definition
-- this table connects photograms and photos (m:n)
CREATE TABLE tabaid_photogram_photo (
	id_aut serial4 NOT NULL,
	ref_photogram VARCHAR(100) NOT NULL,
	ref_photo VARCHAR(100) NOT NULL,
	CONSTRAINT tabaid_photogram_photo_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_photogram_photo_fk_photogram FOREIGN KEY (ref_photogram) REFERENCES tab_photograms(id_photogram) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tabaid_photogram_photo_fk_photo FOREIGN KEY (ref_photo) REFERENCES tab_photos(id_photo) ON DELETE CASCADE ON UPDATE CASCADE
 );


-- tabaid_photogram_sj definition
-- this table is clue between SJs and photograms (m:n)
CREATE TABLE tabaid_photogram_sj (
	id_aut serial4 NOT NULL,
	ref_photogram VARCHAR(100) NOT NULL,
	ref_sj int4 NOT NULL,
	CONSTRAINT tabaid_photogram_sj_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_photogram_sj_fk_photogram FOREIGN KEY (ref_photogram) REFERENCES tab_photograms(id_photogram) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tabaid_photogram_sj_fk_sj FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE
);

-- tabaid_sj_cut definition
-- this table is clue between SJs and CUTs (m:n)
CREATE TABLE tabaid_sj_cut (
	id_aut serial4 NOT NULL,
	ref_sj int4 NOT NULL,
	ref_cut int4 NOT NULL,
	CONSTRAINT tabaid_sj_cut_pk PRIMARY KEY (id_aut),
    CONSTRAINT tabaid_sj_cut_fk_sj FOREIGN KEY (ref_cut) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT tabaid_sj_cut_fk_cut FOREIGN KEY (ref_sj) REFERENCES tab_cut(id_cut) ON DELETE CASCADE ON UPDATE CASCADE
);
    

-- tabaid_sj_sketch definition
-- this tabaid clues SJs and Sketches (m:n)
CREATE TABLE tabaid_sj_sketch (
	id_aut serial4 NOT NULL,
	ref_sj int4 NOT NULL,
	ref_sketch varchar NOT NULL,
	CONSTRAINT tabaid_sj_sketch_pk PRIMARY KEY (id_aut),
    CONSTRAINT tabaid_sj_sketch_fk_sketch FOREIGN KEY (ref_sketch) REFERENCES tab_sketches(id_sketch) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT tabaid_sj_sketch_fk_sj FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX tabaid_sj_sketch_unique ON tabaid_sj_sketch(ref_sj, ref_sketch);
CREATE INDEX tabaid_sj_sketch_ref_sketch_idx ON tabaid_sj_sketch(ref_sketch);


-- tabaid_sj_polygon definition
-- this clues SJs and polygons (m:n)
CREATE TABLE tabaid_sj_polygon (
 	id_aut serial4 NOT NULL,
	ref_sj int4 NOT NULL,
	ref_polygon int4 NOT NULL,
	CONSTRAINT tabaid_sj_polygon_pk PRIMARY KEY (id_aut)
);


-- POLYGONS <-> PHOTOS
CREATE TABLE IF NOT EXISTS tabaid_polygon_photos (
  id_aut      serial PRIMARY KEY,
  ref_polygon int    NOT NULL REFERENCES tab_polygons(id) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_photo   varchar(120) NOT NULL REFERENCES tab_photos(id_photo) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS tabaid_polygon_photos_idx ON tabaid_polygon_photos(ref_polygon, ref_photo);

-- POLYGONS <-> SKETCHES
CREATE TABLE IF NOT EXISTS tabaid_polygon_sketches (
  id_aut      serial PRIMARY KEY,
  ref_polygon int    NOT NULL REFERENCES tab_polygons(id) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_sketch  varchar(120) NOT NULL REFERENCES tab_sketches(id_sketch) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS tabaid_polygon_sketches_idx ON tabaid_polygon_sketches(ref_polygon, ref_sketch);

-- POLYGONS <-> PHOTOGRAMS
CREATE TABLE IF NOT EXISTS tabaid_polygon_photograms (
  id_aut        serial PRIMARY KEY,
  ref_polygon   int    NOT NULL REFERENCES tab_polygons(id) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_photogram varchar(120) NOT NULL REFERENCES tab_photograms(id_photogram) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS tabaid_polygon_photograms_idx ON tabaid_polygon_photograms(ref_polygon, ref_photogram);


-- CUTS <-> PHOTOS
CREATE TABLE IF NOT EXISTS tabaid_cut_photos (
  id_aut   serial PRIMARY KEY,
  ref_cut  int NOT NULL REFERENCES tab_cut(id_cut) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_photo varchar(120) NOT NULL REFERENCES tab_photos(id_photo) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS tabaid_cut_photos_idx ON tabaid_cut_photos(ref_cut, ref_photo);

-- CUTS <-> SKETCHES
CREATE TABLE IF NOT EXISTS tabaid_cut_sketches (
  id_aut   serial PRIMARY KEY,
  ref_cut  int NOT NULL REFERENCES tab_cut(id_cut) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_sketch varchar(120) NOT NULL REFERENCES tab_sketches(id_sketch) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS tabaid_cut_sketches_idx ON tabaid_cut_sketches(ref_cut, ref_sketch);

-- CUTS <-> PHOTOGRAMS
CREATE TABLE IF NOT EXISTS tabaid_cut_photograms (
  id_aut   serial PRIMARY KEY,
  ref_cut  int NOT NULL REFERENCES tab_cut(id_cut) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_photogram varchar(120) NOT NULL REFERENCES tab_photograms(id_photogram) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS tabaid_cut_photograms_idx ON tabaid_cut_photograms(ref_cut, ref_photogram);

-- CUTS <-> DRAWINGS
CREATE TABLE IF NOT EXISTS tabaid_cut_drawings (
  id_aut    serial PRIMARY KEY,
  ref_cut   int NOT NULL REFERENCES tab_cut(id_cut) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_drawing varchar(120) NOT NULL REFERENCES tab_drawings(id_drawing) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS tabaid_cut_drawings_idx ON tabaid_cut_drawings(ref_cut, ref_drawing);



-- #################################
-- #### FUNCTIONS ###
-- there are 3 types of functions:
-- 1. General functions (overwrite SRID in whole DB etc...)
-- 2. check functions - checking the logical consistency of data - 'fnc_check...'
-- 3. getions - retrieving data from database (main purpose of database) - 'fnc_get...'
-- #################################


-- #################################
-- GENERAL SYSTEM FUNCTIONS
-- #################################

-- This function (inhibited by trigger) overwrites all SRIDs to all geometry columns in schema (default: current_schema()).
-- geography columns ignored (geography is „always 4326“).
CREATE OR REPLACE FUNCTION set_project_srid(target_srid integer, in_schema text DEFAULT current_schema())
RETURNS void
LANGUAGE plpgsql AS
$$
DECLARE
  r record;
  cur_srid int;
BEGIN
  IF target_srid IS NULL OR target_srid <= 0 THEN
    RAISE EXCEPTION 'Invalid target_srid: %', target_srid;
  END IF;

  FOR r IN
    SELECT
      f_table_schema  AS sch,
      f_table_name    AS tbl,
      f_geometry_column AS col
    FROM geometry_columns
    WHERE f_table_schema = in_schema
  LOOP
    -- zkus přečíst aktuální SRID (může vrátit 0/NULL u špatně typovaných sloupců)
    BEGIN
      cur_srid := Find_SRID(r.sch::text, r.tbl::text, r.col::text);
    EXCEPTION WHEN OTHERS THEN
      cur_srid := NULL;
    END;

    -- pokud už sedí, přeskoč
    IF cur_srid = target_srid THEN
      CONTINUE;
    END IF;

    -- Přepni SRID sloupce i metadat (bez dotyku dat)
    BEGIN
      PERFORM UpdateGeometrySRID(r.sch::text, r.tbl::text, r.col::text, target_srid);
      RAISE NOTICE 'SRID updated: %.%.% → EPSG %', r.sch, r.tbl, r.col, target_srid;
    EXCEPTION WHEN OTHERS THEN
      -- nechceme shodit celou akci; jen zaloguj
      RAISE NOTICE 'SRID update failed for %.%.%: %', r.sch, r.tbl, r.col, SQLERRM;
    END;
  END LOOP;
END
$$;


-- This PL/PGSQL function is for excavation polygons and namely constructs polygon from geomesuring points:
-- - collects points from tab_geopts in range
-- - sorts by id_pts
-- - closes line (adds startpoint to end)
-- - unifies SRID to project
-- - creates POLYGON and saves to tab_polygons.geom.
CREATE OR REPLACE FUNCTION rebuild_polygon_geom_from_geopts(p_polygon int)
RETURNS void
LANGUAGE plpgsql AS
$$
DECLARE
  v_schema  text := current_schema();
  v_epsg    int;
  v_line    geometry;
  v_poly    geometry;
  v_count   int;
BEGIN
  -- target SRID
  v_epsg := Find_SRID(v_schema::text, 'tab_polygons'::text, 'geom'::text);
  IF v_epsg IS NULL OR v_epsg <= 0 THEN
    RAISE EXCEPTION 'Cannot resolve SRID for %.tab_polygons.geom', v_schema;
  END IF;

  -- poskládej JEDNU linii ze všech dávek (globálně podle id_pts)
  WITH ranges AS (
    SELECT pts_from, pts_to
    FROM tab_polygon_geopts_binding
    WHERE ref_polygon = p_polygon
  ),
  pts AS (
    SELECT DISTINCT ON (g.id_pts) g.id_pts, g.pts_geom
    FROM ranges r
    JOIN tab_geopts g
      ON g.id_pts BETWEEN r.pts_from AND r.pts_to
    WHERE g.pts_geom IS NOT NULL
    ORDER BY g.id_pts
  )
  SELECT
    CASE
      WHEN COUNT(*) >= 2 THEN
        ST_MakeLine(ARRAY_AGG(pts_geom ORDER BY id_pts))
      ELSE NULL
    END
  INTO v_line
  FROM pts;

  IF v_line IS NULL THEN
    UPDATE tab_polygons SET geom = NULL WHERE id = p_polygon;
    RAISE NOTICE 'Not enough points to build line (polygon %).', p_polygon;
    RETURN;
  END IF;

  -- na cílový SRID (pro jistotu)
  IF ST_SRID(v_line) IS DISTINCT FROM v_epsg THEN
    v_line := ST_Transform(v_line, v_epsg);
  END IF;

  -- uzavři + očisti
  IF NOT ST_Equals(ST_StartPoint(v_line), ST_EndPoint(v_line)) THEN
    v_line := ST_AddPoint(v_line, ST_StartPoint(v_line));
  END IF;
  v_line := ST_RemoveRepeatedPoints(v_line, 0.0000001);

  -- polygon
  v_poly := ST_MakeValid(ST_MakePolygon(v_line));

  IF ST_IsEmpty(v_poly) OR GeometryType(v_poly) <> 'ST_Polygon' THEN
    -- držíme tvé pravidlo: žádný multipolygon ani díry – když to nevyjde, necháme NULL
    UPDATE tab_polygons SET geom = NULL WHERE id = p_polygon;
    RAISE NOTICE 'Built geometry not a single Polygon or empty (polygon %).', p_polygon;
  ELSE
    UPDATE tab_polygons SET geom = v_poly WHERE id = p_polygon;
  END IF;
END
$$;


-- This function is optional - rebuilds the geometry of all polygons 
CREATE OR REPLACE FUNCTION rebuild_all_polygons_from_geopts()
RETURNS void
LANGUAGE plpgsql AS
$$
DECLARE r record;
BEGIN
  FOR r IN SELECT DISTINCT ref_polygon FROM tab_polygon_geopts_binding LOOP
    PERFORM rebuild_polygon_geom_from_geopts(r.ref_polygon);
  END LOOP;
END
$$;



-- #################################
-- TRIGGERS
-- #################################


-- This trigger updates tab_photos - calculates geometry coords for column photo_centroid
-- according SRID defined dynamically
CREATE OR REPLACE FUNCTION tab_photos_set_centroid()
RETURNS trigger
LANGUAGE plpgsql AS
$$
DECLARE
  v_epsg int;
BEGIN
  -- If without GPS → centroid NULL
  IF NEW.gps_lat IS NULL OR NEW.gps_lon IS NULL THEN
    NEW.photo_centroid := NULL;
    RETURN NEW;
  END IF;

  -- Check for values, if more than WGS limits → NULL
  IF NEW.gps_lat < -90 OR NEW.gps_lat > 90
     OR NEW.gps_lon < -180 OR NEW.gps_lon > 180 THEN
    NEW.photo_centroid := NULL;
    RETURN NEW;
  END IF;

  -- SRID target: retype to text
  v_epsg := Find_SRID(TG_TABLE_SCHEMA::text, TG_TABLE_NAME::text, 'photo_centroid'::text);

 
  IF v_epsg IS NULL OR v_epsg <= 0 THEN
    NEW.photo_centroid := NULL;
    RETURN NEW;
  END IF;

  NEW.photo_centroid :=
    ST_Transform(
      ST_SetSRID(ST_MakePoint(NEW.gps_lon, NEW.gps_lat), 4326),
      v_epsg
    );

  RETURN NEW;

EXCEPTION
  WHEN OTHERS THEN
    NEW.photo_centroid := NULL;
    RETURN NEW;
END
$$;
-- ensure there is only one trigger
DROP TRIGGER IF EXISTS trg_tab_photos_set_centroid ON tab_photos;
CREATE TRIGGER trg_tab_photos_set_centroid
BEFORE INSERT OR UPDATE OF gps_lat, gps_lon
ON tab_photos
FOR EACH ROW
EXECUTE FUNCTION tab_photos_set_centroid();



-- This trigger updates tab_geopts - calculates geometry coords for columns X,Y,h
-- according SRID defined dynamically
CREATE OR REPLACE FUNCTION tab_geopts_set_geom()
RETURNS trigger
LANGUAGE plpgsql AS
$$
DECLARE
  v_epsg int;
BEGIN
  IF NEW.x IS NULL OR NEW.y IS NULL THEN
    NEW.pts_geom := NULL;
    RETURN NEW;
  END IF;

  v_epsg := Find_SRID(TG_TABLE_SCHEMA::text, TG_TABLE_NAME::text, 'pts_geom'::text);
  IF v_epsg IS NULL OR v_epsg <= 0 THEN
    NEW.pts_geom := NULL;
    RETURN NEW;
  END IF;

  NEW.pts_geom :=
    ST_SetSRID(ST_MakePoint(NEW.x, NEW.y), v_epsg);

  RETURN NEW;

EXCEPTION
  WHEN OTHERS THEN
    NEW.pts_geom := NULL;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_tab_geopts_set_geom ON tab_geopts;
CREATE TRIGGER trg_tab_geopts_set_geom
BEFORE INSERT OR UPDATE OF x, y
ON tab_geopts
FOR EACH ROW
EXECUTE FUNCTION tab_geopts_set_geom();




--###################
--GET FUNCTIONS
--###################

-- this fnc loops over all SJs and returns related photos
CREATE OR REPLACE FUNCTION fnc_get_all_sjs_and_related_photo()
 RETURNS TABLE(sj_id INTEGER, photo_id CHARACTER VARYING, photo_typ CHARACTER VARYING, photo_datum date)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tf.id_photo,
            tf.photo_typ,
            tf.datum AS photo_datum
        FROM
            tab_sj sj
        INNER JOIN
            tabaid_photo_sj tafs ON sj.id_sj = tafs.ref_sj
        INNER JOIN
            tab_photos tf ON tafs.ref_photo = tf.id_photo
    );
END;
$function$
;


-- 
-- this fnc loops over all SJs and returns related photograms
CREATE OR REPLACE FUNCTION fnc_get_all_sjs_and_related_photogram()
 RETURNS TABLE(sj_id INTEGER, id_photogram CHARACTER VARYING, photogram_typ CHARACTER VARYING)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tf.id_photogram,
            tf.photogram_typ
        FROM
            tab_sj sj
        INNER JOIN
            tabaid_photogram_sj tafs ON sj.id_sj = tafs.ref_sj
        INNER JOIN
            tab_photograms tf ON tafs.ref_photogram = tf.id_photogram
    );
END;
$function$
;

--
-- this fnc loops over all SJs and returns related sketches
CREATE OR REPLACE FUNCTION fnc_get_all_sjs_and_related_sketch()
 RETURNS TABLE(sj_id INTEGER, id_sketch CHARACTER VARYING, sketch_typ CHARACTER VARYING, datum date)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            ts.id_sketch,
            ts.sketch_typ,
            ts.datum AS sketch_datum
        FROM
            tab_sj sj
        INNER JOIN
            tabaid_sj_sketch tass ON sj.id_sj = tass.ref_sj
        INNER JOIN
            tab_sketches ts ON tass.ref_sketch = ts.id_sketch
    );
END;
$function$
;

-- this function requires the ID of cut and lists all SJs cut by this cut
CREATE OR REPLACE FUNCTION fnc_get_cut_and_related_sjs(choose_cut INTEGER)
 RETURNS TABLE(id_cut INTEGER, id_sj INTEGER, docu_plan BOOLEAN, docu_vertical BOOLEAN)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            tc.id_cut,
            tsj.id_sj,
            tsj.docu_plan,
	    tsj.docu_vertical
        FROM
            tab_cut tc
        INNER JOIN
            tabaid_sj_cut tasc ON tc.id_cut = tasc.ref_cut
        INNER JOIN
            tab_sj tsj ON tasc.ref_sj = tsj.id_sj
	WHERE tc.id_cut = choose_cut
    );
END;
$function$
;

-- this function takes ID of SJ and list all cuts cutting this SJ 
CREATE OR REPLACE FUNCTION fnc_get_sj_and_related_cuts(choose_sj INTEGER)
 RETURNS TABLE(sj_id INTEGER, id_cut INTEGER, description CHARACTER VARYING)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tc.id_cut,
            tc.description
        FROM
            tab_sj sj
        INNER JOIN
            tabaid_sj_cut tasc ON sj.id_sj = tasc.ref_sj
        INNER JOIN
            tab_cut tc ON tasc.ref_cut = tc.id_cut
	WHERE sj.id_sj = choose_sj
    );
END;
$function$
;

-- this function takes SJ id and returns list of all related photos
CREATE OR REPLACE FUNCTION fnc_get_sj_and_related_photo(choose_sj INTEGER)
 RETURNS TABLE(sj_id INTEGER, photo_id CHARACTER VARYING, photo_typ CHARACTER VARYING, photo_datum DATE)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tf.id_photo,
            tf.photo_typ,
            tf.datum AS photo_datum
        FROM
            tab_sj sj
        INNER JOIN
            tabaid_photo_sj tafs ON sj.id_sj = tafs.ref_sj
        INNER JOIN
            tab_photos tf ON tafs.ref_photo = tf.id_photo
	WHERE sj.id_sj = choose_sj
    );
END;
$function$
;

-- this function requires SJ id and returns list of referenced photograms
CREATE OR REPLACE FUNCTION fnc_get_sj_and_related_photogram(strat_j INTEGER)
 RETURNS TABLE(sj_id INTEGER, id_photogram CHARACTER VARYING, photogram_typ CHARACTER VARYING)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tf.id_photogram,
            tf.photogram_typ
        FROM
            tab_sj sj
        INNER JOIN
            tabaid_photogram_sj tafs ON sj.id_sj = tafs.ref_sj
        INNER JOIN
            tab_photograms tf ON tafs.ref_photogram = tf.id_photogram
	WHERE sj.id_sj = strat_j
    );
END;
$function$
;

-- this function use SJ is as an argument and prints all sketches associated with
CREATE OR REPLACE FUNCTION fnc_get_sj_and_related_sketch(strat_j INTEGER)
 RETURNS TABLE(sj_id INTEGER, id_sketch CHARACTER VARYING, sketch_typ CHARACTER VARYING, datum DATE)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            ts.id_sketch,
            ts.sketch_typ,
            ts.datum AS sketch_datum
        FROM
            tab_sj sj
        INNER JOIN
            tabaid_sj_sketch tass ON sj.id_sj = tass.ref_sj
        INNER JOIN
            tab_sketches ts ON tass.ref_sketch = ts.id_sketch
	WHERE sj.id_sj = strat_j
    );
END;
$function$
;


-- similar as 1st function but this uses loop
CREATE OR REPLACE FUNCTION fnc_get_all_sjs_and_associated_photos()
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    sj_record record;
    photo_info text;
BEGIN
    FOR sj_record IN (
        SELECT id_sj
        FROM tab_sj
    ) LOOP
        FOR photo_info IN (
            SELECT tf.id_photo || ' (' || tf.photo_typ || ')' AS photo_description
            FROM tabaid_photo_sj tafs
            JOIN tab_photos tf ON tafs.ref_photo = tf.id_photo
            WHERE tafs.ref_sj = sj_record.id_sj
        ) LOOP
            RAISE NOTICE 'For SJ %, Associated Photo: %', sj_record.id_sj, photo_info;
        END LOOP;
    END LOOP;
END;
$function$
;

-- this function lists all objects/features and prints associated sjs
CREATE OR REPLACE FUNCTION fnc_get_all_objects_sjs()
 RETURNS TABLE(objekt INTEGER, typ_objektu CHARACTER VARYING, strat_j INTEGER, interpretace CHARACTER VARYING)
 LANGUAGE plpgsql
AS $function$
BEGIN
        RETURN QUERY SELECT
        id_object, object_typ, id_sj, interpretation
        FROM tab_object INNER JOIN tab_sj ON id_object = ref_object
        ORDER BY id_object ASC;
END;
$function$
;

-- this function takes foto ID and prints all photograms associated
CREATE OR REPLACE FUNCTION fnc_get_photograms_by_photo(fotopattern CHARACTER VARYING)
 RETURNS TABLE(id_photogram CHARACTER VARYING, photogram_typ CHARACTER VARYING, ref_sketch CHARACTER VARYING)
 LANGUAGE plpgsql
AS $function$
	BEGIN
		RETURN QUERY
		SELECT fg.id_photogram, fg.photogram_typ, fg.ref_sketch
		FROM tab_photograms fg
		INNER JOIN tabaid_photogram_photo tff ON fg.id_photogram = tff.ref_photogram
		INNER JOIN tab_photos fo ON tff.ref_photo = fo.id_photo
		WHERE fo.id_photo ILIKE fotopattern;

	END;
   $function$
;

-- this func takes photogram ID and lists all photos associated
CREATE OR REPLACE FUNCTION fnc_get_photos_by_photogram(fotogramm CHARACTER VARYING)
 RETURNS TABLE(id_photo CHARACTER VARYING, photo_typ CHARACTER VARYING, notes text)
 LANGUAGE plpgsql
AS $function$
	BEGIN
		RETURN QUERY
		SELECT fo.id_photo, fo.typ, fo.notes
		FROM tab_photos fo
		INNER JOIN tabaid_photogram_photo tff ON fo.id_photo = tff.ref_photo
		INNER JOIN tab_photograms tf ON tff.ref_photogram = tf.id_photogram
		WHERE tf.id_photogram ILIKE fotogramm;

	END;
   $function$
;

-- this function takes object/feature as argument and prints all SJs it consists of
CREATE OR REPLACE FUNCTION fnc_get_sj_by_object(objekt INTEGER)
 RETURNS TABLE(strat_j_id INTEGER, interpretace CHARACTER VARYING)
 LANGUAGE plpgsql
AS $function$
BEGIN
        RETURN QUERY SELECT
                id_sj,
                interpretation
        FROM tab_object
        INNER JOIN tab_sj on id_object = ref_object
        WHERE id_object = objekt;
END;
$function$
;

-- ATTENTION!!! SUPERFUNCTION
-- this function loops over all SJs and prints all
-- graphical documentation related to it. It uses
-- 3 functions defined above
CREATE OR REPLACE FUNCTION superfnc_get_all_sjs_and_related_docu_entities()
 RETURNS TABLE(output_text text)
 LANGUAGE plpgsql
AS $function$
DECLARE
    sj_id INTEGER;
    record_row record;
    loop_sj_id INTEGER; -- Separate variable for sj_id
BEGIN
    FOR sj_id IN (SELECT DISTINCT id_sj FROM tab_sj) LOOP
        loop_sj_id := sj_id; -- Assign sj_id to a separate variable

        -- Initialize the output text for this sj_id
        output_text := 'For SJ ID=' || loop_sj_id || ' we have following items:';

        -- Call the function to retrieve fotos
        FOR record_row IN
            SELECT * FROM fnc_get_all_sjs_and_related_photo() AS f WHERE f.sj_id = loop_sj_id LOOP
            output_text := output_text || CHR(10) || '- Photos: ' || record_row.photo_id || ', ' || record_row.photo_typ || ', ' || record_row.photo_datum;
        END LOOP;

        -- Call the function to retrieve photograms
        FOR record_row IN
            SELECT * FROM fnc_get_all_sjs_and_related_photogram() AS fg WHERE fg.sj_id = loop_sj_id LOOP
            output_text := output_text || CHR(10) || '- Photograms: ' || record_row.id_photogram || ', ' || record_row.photogram_typ;
        END LOOP;

        -- Call the function to retrieve sketches
        FOR record_row IN
            SELECT * FROM fnc_get_all_sjs_and_related_sketch() AS s WHERE s.sj_id = loop_sj_id LOOP
            output_text := output_text || CHR(10) || '- Sketches: ' || record_row.id_sketch || ', ' || record_row.sketch_typ || ', ' || record_row.datum;
        END LOOP;

        -- Return the output for this sj_id
        RETURN QUERY SELECT output_text;
    END LOOP;
END;
$function$
;

-- another SUPERFUNCTION
-- this superfunction works same as previous but not for all SJs
-- but only for one particular (as an argument)
CREATE OR REPLACE FUNCTION superfnc_get_sj_and_related_docu_entities(target_sj_id INTEGER)
 RETURNS TABLE(output_text text)
 LANGUAGE plpgsql
AS $function$
DECLARE
    loop_sj_id INTEGER; -- Separate variable for sj_id
    record_row record;
BEGIN
    -- Initialize the output text for the specified sj_id
    output_text := 'For SJ ID=' || target_sj_id || ' we have following items:';

    loop_sj_id := target_sj_id; -- Assign the specified sj_id to a separate variable

    -- Call the function to retrieve fotos
    FOR record_row IN
        SELECT * FROM fnc_get_all_sjs_and_related_photo() AS f WHERE f.sj_id = loop_sj_id LOOP
        output_text := output_text || CHR(10) || '- Photos: ' || record_row.photo_id || ', ' || record_row.photo_typ || ', ' || record_row.photo_datum;
    END LOOP;

    -- Call the function to retrieve photograms
    FOR record_row IN
        SELECT * FROM fnc_get_all_sjs_and_related_photogram() AS fg WHERE fg.sj_id = loop_sj_id LOOP
        output_text := output_text || CHR(10) || '- Photograms: ' || record_row.id_photogram || ', ' || record_row.photogram_typ;
    END LOOP;

    -- Call the function to retrieve sketches
    FOR record_row IN
        SELECT * FROM fnc_get_all_sjs_and_related_sketch() AS s WHERE s.sj_id = loop_sj_id LOOP
        output_text := output_text || CHR(10) || '- Sketches: ' || record_row.id_sketch || ', ' || record_row.sketch_typ || ', ' || record_row.datum;
    END LOOP;

    -- Return the output for the specified sj_id
    RETURN QUERY SELECT output_text;
END;
$function$
;


--------------
--------------
-- CHECK FUNCTIONS - REVIEWING DATA IF ACCORDING  DATA MODEL
--------------
--------------


-- this function checks if all objects are created by SJs (has reference)
CREATE OR REPLACE FUNCTION fnc_check_objects_have_sj()
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    object_count INTEGER;
    missing_objects TEXT;  -- String to store the IDs of missing objects
BEGIN
    -- Get the total count of objects
    SELECT COUNT(*) INTO object_count FROM tab_object;

    -- Collect the IDs of objects without corresponding sj_id in tab_sj
    SELECT string_agg(tab_object.id_object::TEXT, E'\n') INTO missing_objects
    FROM tab_object
    LEFT JOIN tab_sj ON tab_object.id_object = tab_sj.ref_object
    WHERE tab_sj.id_sj IS NULL;

    -- Check if all objects have corresponding sj_id values
    IF missing_objects IS NULL THEN
        RAISE NOTICE 'All objects are fine, having SJs';
    ELSE
        RAISE NOTICE 'Objects with missing SJs:%', E'\n' || missing_objects;
    END IF;
END;
$function$
;


-- this function checks if all SJs have at least one photo
CREATE OR REPLACE FUNCTION fnc_check_all_sjs_has_photo()
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    sj_id INT;
BEGIN
    -- Check if there are SU records without corresponding photo records
    IF EXISTS (
        SELECT 1
        FROM tab_sj sj
        WHERE NOT EXISTS (
            SELECT 1
            FROM tabaid_photo_sj foto
            WHERE foto.ref_sj = sj.id_sj
        )
    ) THEN
        -- Print SJ records without foto records
        RAISE NOTICE 'Following SJs have no foto entry:';
        FOR sj_id IN (SELECT id_sj FROM tab_sj sj WHERE NOT EXISTS (
            SELECT 1 FROM tabaid_photo_sj foto WHERE foto.ref_sj = sj.id_sj
        )) LOOP
            RAISE NOTICE '%', sj_id;
        END LOOP;
    ELSE
        -- All SJ records have corresponding foto records
        RAISE NOTICE 'Check OK, all SUs have appropriate fotorecord';
    END IF;
END;
$function$
;

-- this function checks if SJs have or not sketches
CREATE OR REPLACE FUNCTION fnc_check_all_sjs_has_sketch()
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    sj_id INT;
BEGIN
    -- Check if there are SJ records without corresponding sketch records
    IF EXISTS (
        SELECT 1
        FROM tab_sj
        WHERE NOT EXISTS (
            SELECT 1
            FROM tabaid_sj_sketch
            WHERE tabaid_sj_sketch.ref_sj = tab_sj.id_sj
        )
    ) THEN
        -- Print SJ records without sketch records
        RAISE NOTICE 'Following SJs have no sketch entry:';
        FOR sj_id IN (SELECT id_sj FROM tab_sj WHERE NOT EXISTS (
            SELECT 1 FROM tabaid_sj_sketch WHERE tabaid_sj_sketch.ref_sj = tab_sj.id_sj
        )) LOOP
            RAISE NOTICE '%', sj_id;
        END LOOP;
    ELSE
        -- All SJ records have corresponding foto records
        RAISE NOTICE 'Check OK, all SJs have appropriate sketch:';
    END IF;
END;
$function$
;
