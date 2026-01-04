-- This is basix SQL script for making database structure
--- ArcheoDB project; author dobo@dobo.sk


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

-- -------------------------
-- Finds: glossary of find types
-- -------------------------
CREATE TABLE IF NOT EXISTS gloss_find_type (
  type_code  text PRIMARY KEY,          -- snake_case, e.g. 'human_bones'
  is_active  boolean NOT NULL DEFAULT true,
  sort_order int NOT NULL DEFAULT 100
);

-- seed (defaults)
INSERT INTO gloss_find_type (type_code, sort_order) VALUES
  ('ceramics',         10),
  ('human_bones',      20),
  ('animal_bones',     30),
  ('chipped_industry', 40),
  ('stones',           50),
  ('wood',             60),
  ('iron',             70),
  ('copper',           80),
  ('bronze',           90)
ON CONFLICT (type_code) DO NOTHING;


-- -------------------------
-- Samples: glossary of sample types
-- -------------------------
CREATE TABLE IF NOT EXISTS gloss_sample_type (
  type_code  text PRIMARY KEY,          -- snake_case, e.g. 'archeobotany'
  is_active  boolean NOT NULL DEFAULT true,
  sort_order int NOT NULL DEFAULT 100
);

-- seed (defaults)
INSERT INTO gloss_sample_type (type_code, sort_order) VALUES
  ('archaeobotany',   10),
  ('geoarchaeology', 20),
  ('malacology',     30),
  ('palynology',     40),
  ('osteology',      50)
ON CONFLICT (type_code) DO NOTHING;



------
-- ### HERE MAIN TABLES - TERRAIN ENTITIES
------

---
-- tab_section definition
---i

CREATE TYPE section_type AS ENUM (
  'standard',      -- standard section from above to bottom by removing the part of stratigraphy
  'cumulative',    -- cumulative section according Ph. Barker
  'synthetic',     -- synthetic section is post-excav modeling, synthesis of more profiles
  'other'          -- other (define in notes)
);

CREATE TABLE tab_section (
	id_section int4 NOT NULL,
  section_type section_type NOT NULL,
	description text NULL,
	CONSTRAINT tab_section_pk PRIMARY KEY (id_section)
);

---
-- tab_geopts definition
---
CREATE TYPE geopt_code AS ENUM (
      'SU', -- tracking boundaries of stratigraphic unit
      'FX', -- fix (e.g. nail)
      'EP', -- excavation polygon
      'FO', -- photogrammetric point
      'NI', -- nielation for making surfaces
      'PF', -- point field for total station stationing
      'SP'  -- special meaning (free)
);

CREATE TABLE IF NOT EXISTS tab_geopts (
  id_pts   int4    PRIMARY KEY,
  x        double precision NOT NULL,   -- more precise than numeric
  y        double precision NOT NULL,
  h        double precision NOT NULL,
  code     geopt_code,  -- see enum above
  notes    text,
  pts_geom geometry(PointZ)             -- SRID set by set_project_srid later
);
CREATE UNIQUE INDEX IF NOT EXISTS tab_geopts_id_pts_idx ON tab_geopts (id_pts);
-- Spatial index for bbox queries etc.
CREATE INDEX IF NOT EXISTS tab_geopts_geom_gix ON tab_geopts USING GIST (pts_geom) WHERE pts_geom IS NOT NULL;


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

CREATE TYPE allocation_reason AS ENUM (
  'physical_separation',      -- polygons are physically divided
  'research_phase',           -- polygons are reason of phases/temporary flow of excavation
  'horizontal_stratigraphy',  -- horizontal stratigraphy forces to divide to polygons
  'other'                     -- other (define in notes)
);

-- Polygons of excavation definition (3D surfaces)
CREATE TABLE IF NOT EXISTS tab_polygons (
  polygon_name      text PRIMARY KEY,
  parent_name       text NULL REFERENCES tab_polygons(polygon_name) ON DELETE RESTRICT,
  allocation_reason allocation_reason NOT NULL,
  geom_top          geometry(PolygonZ),   -- top edge polygon (3D polygon)
  geom_bottom       geometry(PolygonZ),   -- bottom edge polygon (3D polygon)
  notes             text
);
ALTER TABLE tab_polygons ADD CONSTRAINT tab_polygons_parent_not_self CHECK (parent_name IS NULL OR parent_name <> polygon_name);
CREATE INDEX IF NOT EXISTS tab_polygons_geom_top_gix ON tab_polygons USING GIST (geom_top);
CREATE INDEX IF NOT EXISTS tab_polygons_geom_bottom_gix ON tab_polygons USING GIST (geom_bottom);


-- this is table for storing info of what points are measured for polygon
-- can not perform referential integrity with tab_geopts (point from total station usually come at the end of excavation),
-- so integrity is done by application means
-- here upper/top polygon points
CREATE TABLE tab_polygon_geopts_binding_top (
  id           serial PRIMARY KEY,
  ref_polygon  text NOT NULL
                 REFERENCES tab_polygons(polygon_name)
                 ON UPDATE CASCADE ON DELETE CASCADE,
  pts_from     int  NOT NULL,
  pts_to       int  NOT NULL,
  CHECK (pts_from <= pts_to), 
  -- to avoid 2x the same
  UNIQUE (ref_polygon, pts_from, pts_to)
);
CREATE INDEX tab_polygon_geopts_binding_top_idx ON tab_polygon_geopts_binding_top(ref_polygon, pts_from, pts_to);

-- here bottom/lower polygon points
CREATE TABLE tab_polygon_geopts_binding_bottom (
  id           serial PRIMARY KEY,
  ref_polygon  text NOT NULL
                 REFERENCES tab_polygons(polygon_name)
                 ON UPDATE CASCADE ON DELETE CASCADE,
  pts_from     int  NOT NULL,
  pts_to       int  NOT NULL,
  CHECK (pts_from <= pts_to),
  -- to avoid 2x the same
  UNIQUE (ref_polygon, pts_from, pts_to)
);
CREATE INDEX tab_polygon_geopts_binding_bottom_idx ON tab_polygon_geopts_binding_bottom(ref_polygon, pts_from, pts_to);


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
-- tab_photos (template/fresh install)
CREATE TABLE IF NOT EXISTS tab_photos (
  id_photo        varchar(150)  NOT NULL,
  photo_typ       varchar(60)   NOT NULL,
  datum           date          NOT NULL,
  author          varchar(100)  NOT NULL,
  notes           text          NULL,
  mime_type       text          NOT NULL,
  file_size       int8          NOT NULL,
  checksum_sha256 text          NOT NULL,
  shoot_datetime  timestamptz   NULL,
  gps_lat         float8        NULL,
  gps_lon         float8        NULL,
  gps_alt         float8        NULL,
  exif_json       jsonb         NULL DEFAULT '{}'::jsonb,
  photo_centroid  geometry(PointZ) NULL,  -- SRID set dynamically per-project by set_project_srids
  CONSTRAINT tab_photos_pkey PRIMARY KEY (id_photo),
  CONSTRAINT tab_photos_file_size_check CHECK (file_size >= 0),
  CONSTRAINT tab_photos_id_format_chk CHECK ((id_photo)::text ~ '^[0-9]+_[A-Za-z0-9._-]+[.][a-z0-9]+$'::text),
  CONSTRAINT tab_photos_mime_chk CHECK (
    mime_type = ANY (ARRAY[
      'image/jpg'::text, 'image/jpeg'::text, 'image/png'::text,
      'image/tiff'::text, 'image/svg+xml'::text, 'application/pdf'::text
    ])
  )
);

CREATE INDEX IF NOT EXISTS tab_photos_author_idx      ON tab_photos (author);
CREATE INDEX IF NOT EXISTS tab_photos_checksum_idx    ON tab_photos (checksum_sha256);
CREATE INDEX IF NOT EXISTS tab_photos_datum_idx       ON tab_photos (datum);
CREATE INDEX IF NOT EXISTS tab_photos_shoot_dt_idx    ON tab_photos (shoot_datetime);
CREATE INDEX IF NOT EXISTS tab_photos_centroid_gix ON tab_photos USING GIST (photo_centroid) WHERE photo_centroid IS NOT NULL;
ALTER TABLE tab_photos ADD CONSTRAINT tab_photos_author_fkey FOREIGN KEY (author) REFERENCES gloss_personalia(mail);



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
	id_photogram TEXT NOT NULL,
	photogram_typ TEXT NOT NULL,
	ref_sketch VARCHAR(120) NULL,
	notes TEXT NULL,
	mime_type TEXT NOT NULL,
	file_size int8 NOT NULL,
	checksum_sha256 TEXT NOT NULL,
	ref_photo_from VARCHAR(150) NULL,
	ref_photo_to VARCHAR(150) NULL,
	CONSTRAINT tab_photograms_file_size_check CHECK ((file_size >= 0)),
	CONSTRAINT tab_photograms_id_format_chk CHECK (((id_photogram)::text ~ '^[0-9]+_[A-Za-z0-9._-]+\.[a-z0-9]+$'::text)),
	CONSTRAINT tab_photograms_mime_chk CHECK ((mime_type = ANY (ARRAY['image/jpeg'::text, 'image/png'::text, 'image/tiff'::text, 'image/svg+xml'::text, 'application/pdf'::text]))),
	CONSTRAINT tab_photograms_pkey PRIMARY KEY (id_photogram),
	CONSTRAINT tab_photograms_photo_from_fk FOREIGN KEY (ref_photo_from) REFERENCES tab_photos(id_photo) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tab_photograms_photo_to_fk FOREIGN KEY (ref_photo_to) REFERENCES tab_photos(id_photo) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tab_photograms_ref_sketch_fkey FOREIGN KEY (ref_sketch) REFERENCES tab_sketches(id_sketch) ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE INDEX tab_photograms_checksum_idx ON public.tab_photograms USING btree (checksum_sha256);
CREATE INDEX tab_photograms_ref_sketch_idx ON public.tab_photograms USING btree (ref_sketch);


-- tab_finds definition
-- mostly is it sack/bag as primary identificator - container for finds
-- -------------------------
-- Finds (one record = one bag of a given type from one SJ)
-- -------------------------
CREATE TABLE IF NOT EXISTS tab_finds (
  id_find        int4  NOT NULL,                 -- manual ID (entered by user)
  ref_find_type  text  NOT NULL,                 -- FK -> gloss_find_type(type_code)
  description    text  NULL,
  count          int2  NOT NULL,                 -- number of pieces in the bag
  ref_sj         int4  NOT NULL,                 -- mandatory: comes from one stratigraphic unit
  ref_geopt      int4  NULL,                     -- optional: NO FK (geopts may be imported later)
  ref_polygon    text  NULL,                     -- optional: FK to tab_polygons
  box            int2  NOT NULL,                 -- box for storing sacks/bags
  CONSTRAINT tab_finds_pk PRIMARY KEY (id_find), CONSTRAINT tab_finds_sj_fk FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tab_finds_polygon_fk FOREIGN KEY (ref_polygon) REFERENCES tab_polygons(polygon_name) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT tab_finds_find_type_fk FOREIGN KEY (ref_find_type) REFERENCES gloss_find_type(type_code) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT tab_finds_count_check CHECK (count > 0),
  CONSTRAINT tab_finds_box_check CHECK (box > 0)
);
CREATE INDEX IF NOT EXISTS tab_finds_ref_sj_idx      ON tab_finds(ref_sj);
CREATE INDEX IF NOT EXISTS tab_finds_ref_polygon_idx ON tab_finds(ref_polygon) WHERE ref_polygon IS NOT NULL;
CREATE INDEX IF NOT EXISTS tab_finds_ref_geopt_idx   ON tab_finds(ref_geopt) WHERE ref_geopt IS NOT NULL;
CREATE INDEX IF NOT EXISTS tab_finds_type_idx        ON tab_finds(ref_find_type);



-- terrain samples
---
CREATE TABLE IF NOT EXISTS tab_samples (
  id_sample        int4 NOT NULL,               -- manual ID (entered by user)
  ref_sample_type  text NOT NULL,               -- FK -> gloss_sample_type(type_code)
  description      text NULL,
  ref_sj           int4 NOT NULL,               -- mandatory
  ref_geopt        int4 NULL,                   -- optional: NO FK
  ref_polygon      text NULL,                   -- optional: FK to tab_polygons
  CONSTRAINT tab_samples_pk PRIMARY KEY (id_sample), CONSTRAINT tab_samples_sj_fk FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tab_samples_polygon_fk FOREIGN KEY (ref_polygon) REFERENCES tab_polygons(polygon_name) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT tab_samples_type_fk FOREIGN KEY (ref_sample_type) REFERENCES gloss_sample_type(type_code) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS tab_samples_ref_sj_idx      ON tab_samples(ref_sj);
CREATE INDEX IF NOT EXISTS tab_samples_ref_polygon_idx ON tab_samples(ref_polygon) WHERE ref_polygon IS NOT NULL;
CREATE INDEX IF NOT EXISTS tab_samples_ref_geopt_idx   ON tab_samples(ref_geopt) WHERE ref_geopt IS NOT NULL;
CREATE INDEX IF NOT EXISTS tab_samples_type_idx        ON tab_samples(ref_sample_type);


--==========================================================
-- TABAIDS - table helpers for M:N relations between tables
--==========================================================
-- tabaid between finds and photos
-- -------------------------
-- Finds ↔ Photos
-- -------------------------
CREATE TABLE IF NOT EXISTS tabaid_finds_photos (
  id_aut   serial4 NOT NULL,
  ref_find int4    NOT NULL,
  ref_photo varchar(150) NOT NULL,
  CONSTRAINT tabaid_finds_photos_pk PRIMARY KEY (id_aut), CONSTRAINT tabaid_finds_photos_find_fk FOREIGN KEY (ref_find) REFERENCES tab_finds(id_find) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tabaid_finds_photos_photo_fk FOREIGN KEY (ref_photo) REFERENCES tab_photos(id_photo) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tabaid_finds_photos_uniq UNIQUE (ref_find, ref_photo)
);
CREATE INDEX IF NOT EXISTS tabaid_finds_photos_find_idx  ON tabaid_finds_photos(ref_find);
CREATE INDEX IF NOT EXISTS tabaid_finds_photos_photo_idx ON tabaid_finds_photos(ref_photo);


-- -------------------------
-- Finds ↔ Sketches
-- -------------------------
CREATE TABLE IF NOT EXISTS tabaid_finds_sketches (
  id_aut    serial4 NOT NULL,
  ref_find  int4    NOT NULL,
  ref_sketch text   NOT NULL,
  CONSTRAINT tabaid_finds_sketches_pk PRIMARY KEY (id_aut), CONSTRAINT tabaid_finds_sketches_find_fk FOREIGN KEY (ref_find) REFERENCES tab_finds(id_find) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tabaid_finds_sketches_sketch_fk FOREIGN KEY (ref_sketch) REFERENCES tab_sketches(id_sketch) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tabaid_finds_sketches_uniq UNIQUE (ref_find, ref_sketch)
);
CREATE INDEX IF NOT EXISTS tabaid_finds_sketches_find_idx   ON tabaid_finds_sketches(ref_find);
CREATE INDEX IF NOT EXISTS tabaid_finds_sketches_sketch_idx ON tabaid_finds_sketches(ref_sketch);


-- -------------------------
-- Samples ↔ Photos
-- -------------------------
CREATE TABLE IF NOT EXISTS tabaid_samples_photos (
  id_aut     serial4 NOT NULL,
  ref_sample int4    NOT NULL,
  ref_photo  varchar(150) NOT NULL,
  CONSTRAINT tabaid_samples_photos_pk PRIMARY KEY (id_aut),
  CONSTRAINT tabaid_samples_photos_sample_fk FOREIGN KEY (ref_sample) REFERENCES tab_samples(id_sample) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tabaid_samples_photos_photo_fk FOREIGN KEY (ref_photo) REFERENCES tab_photos(id_photo) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tabaid_samples_photos_uniq UNIQUE (ref_sample, ref_photo)
);
CREATE INDEX IF NOT EXISTS tabaid_samples_photos_sample_idx ON tabaid_samples_photos(ref_sample);
CREATE INDEX IF NOT EXISTS tabaid_samples_photos_photo_idx  ON tabaid_samples_photos(ref_photo);


-- -------------------------
-- Samples ↔ Sketches
-- -------------------------
CREATE TABLE IF NOT EXISTS tabaid_samples_sketches (
  id_aut     serial4 NOT NULL,
  ref_sample int4    NOT NULL,
  ref_sketch text    NOT NULL,
  CONSTRAINT tabaid_samples_sketches_pk PRIMARY KEY (id_aut),
  CONSTRAINT tabaid_samples_sketches_sample_fk FOREIGN KEY (ref_sample) REFERENCES tab_samples(id_sample) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tabaid_samples_sketches_sketch_fk FOREIGN KEY (ref_sketch) REFERENCES tab_sketches(id_sketch) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tabaid_samples_sketches_uniq UNIQUE (ref_sample, ref_sketch)
);
CREATE INDEX IF NOT EXISTS tabaid_samples_sketches_sample_idx ON tabaid_samples_sketches(ref_sample);
CREATE INDEX IF NOT EXISTS tabaid_samples_sketches_sketch_idx ON tabaid_samples_sketches(ref_sketch);



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


-- tabaid_sj_section_definition
-- this table connects SUs and sections (m:n)
CREATE TABLE IF NOT EXISTS tabaid_sj_section (
  id_aut      serial4 PRIMARY KEY,
  ref_sj      int4 NOT NULL,
  ref_section int4 NOT NULL,
  CONSTRAINT tabaid_sj_section_fk_sj FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tabaid_sj_section_fk_section FOREIGN KEY (ref_section) REFERENCES tab_section(id_section) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tabaid_sj_section_uq UNIQUE (ref_sj, ref_section)
);
CREATE INDEX IF NOT EXISTS tabaid_sj_section_idx ON tabaid_sj_section(ref_section, ref_sj);


-- tabaid_photogram_sj definition
-- this table is clue between SJs and photograms (m:n)
CREATE TABLE tabaid_photogram_sj (
	id_aut serial4 NOT NULL,
	ref_photogram TEXT NOT NULL,
	ref_sj int4 NOT NULL,
	CONSTRAINT tabaid_photogram_sj_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_photogram_sj_fk_photogram FOREIGN KEY (ref_photogram) REFERENCES tab_photograms(id_photogram) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tabaid_photogram_sj_fk_sj FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE
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
  ref_sj       int  NOT NULL REFERENCES tab_sj(id_sj) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_polygon  text NOT NULL REFERENCES tab_polygons(polygon_name) ON UPDATE CASCADE ON DELETE CASCADE,
  PRIMARY KEY (ref_sj, ref_polygon)
);
-- pomocný index pro jednostranné dotazy
CREATE INDEX tabaid_sj_polygon_polygon_idx ON tabaid_sj_polygon(ref_polygon);

-----------------------------------------------------------------------

-- 3) M:N POLYGONS <-> PHOTOS
CREATE TABLE tabaid_polygon_photos (
  ref_polygon  text NOT NULL REFERENCES tab_polygons(polygon_name) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_photo    varchar(120) NOT NULL REFERENCES tab_photos(id_photo) ON UPDATE CASCADE ON DELETE CASCADE,
  PRIMARY KEY (ref_polygon, ref_photo)
);
-- (volitelně) reverzní index pro dotazy z fotky na polygony
CREATE INDEX tabaid_polygon_photos_photo_idx ON tabaid_polygon_photos(ref_photo);

-----------------------------------------------------------------------

-- 4) M:N POLYGONS <-> SKETCHES
CREATE TABLE tabaid_polygon_sketches (
  ref_polygon  text NOT NULL REFERENCES tab_polygons(polygon_name) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_sketch   varchar(120) NOT NULL REFERENCES tab_sketches(id_sketch) ON UPDATE CASCADE ON DELETE CASCADE,
  PRIMARY KEY (ref_polygon, ref_sketch)
);
CREATE INDEX tabaid_polygon_sketches_sketch_idx ON tabaid_polygon_sketches(ref_sketch);

-----------------------------------------------------------------------

-- 5) M:N POLYGONS <-> PHOTOGRAMS
CREATE TABLE tabaid_polygon_photograms (
	ref_polygon TEXT NOT NULL,
	ref_photogram TEXT NOT NULL,
	CONSTRAINT tabaid_polygon_photograms_pkey PRIMARY KEY (ref_polygon, ref_photogram),
	CONSTRAINT tabaid_polygon_photograms_ref_photogram_fk FOREIGN KEY (ref_photogram) REFERENCES tab_photograms(id_photogram) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tabaid_polygon_photograms_ref_polygon_fk FOREIGN KEY (ref_polygon) REFERENCES tab_polygons(polygon_name) ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX tabaid_polygon_photograms_photogram_idx ON public.tabaid_polygon_photograms USING btree (ref_photogram);


-- M:N between sections and geodetic points
CREATE TABLE IF NOT EXISTS tab_section_geopts_binding (
  id          serial4 PRIMARY KEY,
  ref_section int4 NOT NULL,
  pts_from    int4 NOT NULL,
  pts_to      int4 NOT NULL,
  CONSTRAINT tab_section_geopts_binding_check CHECK (pts_from <= pts_to), CONSTRAINT tab_section_geopts_binding_pts_from_pts_to_key UNIQUE (ref_section, pts_from, pts_to),
  CONSTRAINT tab_section_geopts_binding_ref_section_fkey FOREIGN KEY (ref_section) REFERENCES tab_section(id_section) ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS tab_section_geopts_binding_idx ON tab_section_geopts_binding(ref_section, pts_from, pts_to);


-- 6) M:N SECTIONS and DOCU entities
-- SECTIONS <-> PHOTOS
CREATE TABLE IF NOT EXISTS tabaid_section_photos (
  id_aut   serial PRIMARY KEY,
  ref_section int4 NOT NULL REFERENCES tab_section(id_section) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_photo varchar(120) NOT NULL REFERENCES tab_photos(id_photo) ON UPDATE CASCADE ON DELETE CASCADE,
  UNIQUE (ref_section, ref_photo)
);
CREATE INDEX IF NOT EXISTS tabaid_section_photos_idx ON tabaid_section_photos(ref_section, ref_photo);

-- SECTIONS <-> SKETCHES
CREATE TABLE IF NOT EXISTS tabaid_section_sketches (
  id_aut   serial PRIMARY KEY,
  ref_section  int4 NOT NULL REFERENCES tab_section(id_section) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_sketch varchar(120) NOT NULL REFERENCES tab_sketches(id_sketch) ON UPDATE CASCADE ON DELETE CASCADE,
  UNIQUE (ref_section, ref_sketch)
);
CREATE INDEX IF NOT EXISTS tabaid_section_sketches_idx ON tabaid_section_sketches(ref_section, ref_sketch);

-- SECTIONS <-> PHOTOGRAMS
CREATE TABLE IF NOT EXISTS tabaid_section_photograms (
	id_aut serial4 NOT NULL,
	ref_section int4 NOT NULL,
	ref_photogram TEXT NOT NULL,
	CONSTRAINT tabaid_section_photogram_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_section_photogram_fk_photogram FOREIGN KEY (ref_photogram) REFERENCES tab_photograms(id_photogram) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tabaid_section_photogram_fk_section FOREIGN KEY (ref_section) REFERENCES tab_section(id_section) ON DELETE CASCADE ON UPDATE CASCADE,
  UNIQUE (ref_section, ref_photogram)
);
CREATE INDEX IF NOT EXISTS tabaid_section_photograms_idx ON tabaid_section_photograms(ref_section, ref_photogram);

-- SECTIONS <-> DRAWINGS
CREATE TABLE IF NOT EXISTS tabaid_section_drawings (
  id_aut    serial PRIMARY KEY,
  ref_section   int NOT NULL REFERENCES tab_section(id_section) ON UPDATE CASCADE ON DELETE CASCADE,
  ref_drawing varchar(120) NOT NULL REFERENCES tab_drawings(id_drawing) ON UPDATE CASCADE ON DELETE CASCADE,
  UNIQUE (ref_section, ref_drawing)
);
CREATE INDEX IF NOT EXISTS tabaid_section_drawings_idx ON tabaid_section_drawings(ref_section, ref_drawing);

-- this connects photograms to geopts ranges
-- there is no FK from geopts to tab_geopts (based on user integrity)
CREATE TABLE tabaid_photogram_geopts (
	ref_photogram text NOT NULL,
	ref_geopt_from int4 NOT NULL,
	ref_geopt_to int4 NOT NULL,
	CONSTRAINT tabaid_photogram_geopts_pk PRIMARY KEY (ref_photogram, ref_geopt_from, ref_geopt_to),
	CONSTRAINT tabaid_photogram_geopts_fk FOREIGN KEY (ref_photogram) REFERENCES tab_photograms(id_photogram) ON DELETE CASCADE ON UPDATE CASCADE
);


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

-- This function overwrites SRID typmod for all geometry columns in a schema
-- (default: current_schema()) by retyping the column and applying ST_SetSRID()
-- to existing values. It does NOT transform coordinates, it only assigns SRID.
-- Geography columns are ignored (geography is always 4326).
CREATE OR REPLACE FUNCTION set_project_srid(
  target_srid integer,
  in_schema text DEFAULT current_schema()
)
RETURNS void
LANGUAGE plpgsql AS
$$
DECLARE
  r record;
  q text;
  type_name text;
  suffix text;
  failed text[] := ARRAY[]::text[];
BEGIN
  IF target_srid IS NULL OR target_srid <= 0 THEN
    RAISE EXCEPTION 'Invalid target_srid: %', target_srid;
  END IF;

  FOR r IN
    SELECT
      n.nspname                                AS sch,
      c.relname                                AS tbl,
      a.attname                                AS col,
      postgis_typmod_type(a.atttypmod)         AS base_type,
      postgis_typmod_dims(a.atttypmod)         AS dims,
      postgis_typmod_srid(a.atttypmod)         AS cur_srid
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid
    JOIN pg_type t ON t.oid = a.atttypid
    WHERE n.nspname = in_schema
      AND c.relkind IN ('r','p')               -- i partitioned tables
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND t.typname = 'geometry'
  LOOP
    IF r.cur_srid = target_srid THEN
      CONTINUE;
    END IF;

    -- decide suffix from dims (best effort; avoids ZZ by checking base_type itself)
    suffix :=
      CASE
        WHEN r.dims = 4 THEN 'ZM'
        WHEN r.dims = 3 THEN 'Z'
        ELSE ''
      END;

    -- if base_type already ends with Z/M/ZM (any case), do NOT append suffix
    IF r.base_type ~* '(ZM|Z|M)$' THEN
      type_name := r.base_type;
    ELSE
      type_name := r.base_type || suffix;
    END IF;

    BEGIN
      q := format(
        'ALTER TABLE %I.%I
           ALTER COLUMN %I
           TYPE geometry(%s, %s)
           USING ST_SetSRID(%I, %s)',
        r.sch, r.tbl, r.col,
        type_name,
        target_srid,
        r.col,
        target_srid
      );

      EXECUTE q;

      RAISE NOTICE 'SRID updated: %.%.% → EPSG %', r.sch, r.tbl, r.col, target_srid;

    EXCEPTION WHEN OTHERS THEN
      failed := array_append(
        failed,
        format('%.%.% (type=%s dims=%s cur_srid=%s): %s', r.sch, r.tbl, r.col, r.base_type, r.dims, r.cur_srid, SQLERRM)
      );
      RAISE NOTICE 'SRID update failed for %.%.%: %', r.sch, r.tbl, r.col, SQLERRM;
    END;
  END LOOP;

  IF array_length(failed, 1) IS NOT NULL THEN
    RAISE EXCEPTION 'set_project_srid failed for % column(s): %', array_length(failed, 1), array_to_string(failed, ' | ');
  END IF;
END
$$;



-- Rebuild polygon geometries from geodetic points (tab_geopts)
-- - collects points from ranges
-- - sorts by id_pts
-- - closes line (adds startpoint to end)
-- - removes consecutive duplicates
-- - validates (min points, simple line, valid polygon)
-- - stores into tab_polygons.geom_top / geom_bottom
CREATE OR REPLACE FUNCTION rebuild_polygon_geoms_from_geopts(p_polygon_name text)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_line     geometry;
  v_poly     geometry;
  v_poly_try geometry;
  v_reason   text;
  q          text;
  side_table text;
  target_col text;
BEGIN
  FOR side_table, target_col IN
    VALUES
      ('tab_polygon_geopts_binding_top',    'geom_top'),
      ('tab_polygon_geopts_binding_bottom', 'geom_bottom')
  LOOP
    -- collect points from ranges and sort them ascending by id_pts
    q := format($SQL$
      WITH ranges AS (
        SELECT pts_from, pts_to
        FROM %I
        WHERE ref_polygon = $1
      ),
      pts AS (
        SELECT DISTINCT ON (g.id_pts) g.id_pts, g.pts_geom
        FROM ranges r
        JOIN tab_geopts g
          ON g.id_pts BETWEEN r.pts_from AND r.pts_to
        WHERE g.pts_geom IS NOT NULL
        ORDER BY g.id_pts
      )
      SELECT CASE
               WHEN COUNT(*) >= 3
                 THEN ST_MakeLine(ARRAY_AGG(pts_geom ORDER BY id_pts))
               ELSE NULL
             END
      FROM pts
    $SQL$, side_table);

    EXECUTE q INTO v_line USING p_polygon_name;

    IF v_line IS NULL THEN
      EXECUTE format('UPDATE tab_polygons SET %I = NULL WHERE polygon_name = $1', target_col)
      USING p_polygon_name;
      RAISE NOTICE 'Not enough points to build polygon (% for %).', target_col, p_polygon_name;
      CONTINUE;
    END IF;

    -- close the polyline
    IF NOT ST_Equals(ST_StartPoint(v_line), ST_EndPoint(v_line)) THEN
      v_line := ST_AddPoint(v_line, ST_StartPoint(v_line));
    END IF;

    -- remove duplicities (consecutive)
    v_line := ST_RemoveRepeatedPoints(v_line, 1e-7);

    -- enforce 3D only if needed (tab_geopts.pts_geom is PointZ, so usually already 3D)
    IF ST_CoordDim(v_line) < 3 THEN
      v_line := ST_Force3D(v_line);
    END IF;

    -- GUARD 1: must have at least 4 points in closed ring (3 distinct + closing point)
    IF ST_NPoints(v_line) < 4 THEN
      EXECUTE format('UPDATE tab_polygons SET %I = NULL WHERE polygon_name = $1', target_col)
      USING p_polygon_name;
      RAISE NOTICE 'Too few vertices after closing (% for %).', target_col, p_polygon_name;
      CONTINUE;
    END IF;

    -- GUARD 2: line cannot self-intersect
    IF NOT ST_IsSimple(v_line) THEN
      EXECUTE format('UPDATE tab_polygons SET %I = NULL WHERE polygon_name = $1', target_col)
      USING p_polygon_name;
      RAISE NOTICE 'Self-intersection detected in line (% for %).', target_col, p_polygon_name;
      CONTINUE;
    END IF;

    -- build polygon (no autocorrection)
    v_poly_try := ST_MakePolygon(v_line);

    -- GUARD 3: polygon must be valid
    IF NOT ST_IsValid(v_poly_try) THEN
      v_reason := ST_IsValidReason(v_poly_try);
      EXECUTE format('UPDATE tab_polygons SET %I = NULL WHERE polygon_name = $1', target_col)
      USING p_polygon_name;
      RAISE NOTICE 'Invalid polygon (% for %): %', target_col, p_polygon_name, v_reason;
      CONTINUE;
    END IF;

    -- enforce PolygonZ only if needed
    IF ST_CoordDim(v_poly_try) < 3 THEN
      v_poly := ST_Force3D(v_poly_try);
    ELSE
      v_poly := v_poly_try;
    END IF;

    -- final check: must be a single polygon
    IF ST_IsEmpty(v_poly) OR ST_GeometryType(v_poly) <> 'ST_Polygon' THEN
      EXECUTE format('UPDATE tab_polygons SET %I = NULL WHERE polygon_name = $1', target_col)
      USING p_polygon_name;
      RAISE NOTICE 'Built geometry is empty or not a single Polygon (% for %).', target_col, p_polygon_name;
      CONTINUE;
    END IF;

    -- save
    EXECUTE format('UPDATE tab_polygons SET %I = $1 WHERE polygon_name = $2', target_col)
    USING v_poly, p_polygon_name;
  END LOOP;
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
  IF NEW.gps_lat IS NULL OR NEW.gps_lon IS NULL THEN
    NEW.photo_centroid := NULL;
    RETURN NEW;
  END IF;

  v_epsg := Find_SRID(TG_TABLE_SCHEMA::text, TG_TABLE_NAME::text, 'photo_centroid'::text);
  IF v_epsg IS NULL OR v_epsg <= 0 THEN
    NEW.photo_centroid := NULL;
    RETURN NEW;
  END IF;

  NEW.photo_centroid :=
    ST_SetSRID(
      ST_MakePoint(NEW.gps_lon, NEW.gps_lat, COALESCE(NEW.gps_alt, 0)),
      v_epsg
    );

  RETURN NEW;

EXCEPTION
  WHEN OTHERS THEN
    NEW.photo_centroid := NULL;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_tab_photos_set_centroid ON tab_photos;

CREATE TRIGGER trg_tab_photos_set_centroid
BEFORE INSERT OR UPDATE OF gps_lat, gps_lon, gps_alt
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

  NEW.pts_geom := ST_SetSRID(ST_MakePoint(NEW.x, NEW.y, NEW.h), v_epsg);

  RETURN NEW;

EXCEPTION
  WHEN OTHERS THEN
    NEW.pts_geom := NULL;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_tab_geopts_set_geom ON tab_geopts;
CREATE TRIGGER trg_tab_geopts_set_geom
BEFORE INSERT OR UPDATE OF x, y, h
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

-- this function requires the ID of section and lists all SJs cut by this section
CREATE OR REPLACE FUNCTION fnc_get_section_and_related_sjs(choose_section INTEGER)
 RETURNS TABLE(id_section INTEGER, id_sj INTEGER, docu_plan BOOLEAN, docu_vertical BOOLEAN)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            tc.id_section,
            tsj.id_sj,
            tsj.docu_plan,
	    tsj.docu_vertical
        FROM
            tab_section tc
        INNER JOIN
            tabaid_sj_section tasc ON tc.id_section = tasc.ref_section
        INNER JOIN
            tab_sj tsj ON tasc.ref_sj = tsj.id_sj
	WHERE tc.id_section = choose_section
    );
END;
$function$
;

-- this function takes ID of SJ and list all sections cutting this SJ 
CREATE OR REPLACE FUNCTION fnc_get_sj_and_related_sections(choose_sj INTEGER)
 RETURNS TABLE(sj_id INTEGER, id_section INTEGER, description CHARACTER VARYING)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tc.id_section,
            tc.description
        FROM
            tab_sj sj
        INNER JOIN
            tabaid_sj_section tasc ON sj.id_sj = tasc.ref_sj
        INNER JOIN
            tab_section tc ON tasc.ref_section = tc.id_section
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
