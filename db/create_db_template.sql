-- This is basix SQL script for making database structure
--- ArcheoDB project; author dobo@dobo.sk


/*
Role and privilege model (tree view)
====================================

ArcheoDB
├── Owner roles (NOLOGIN)
│   ├── own_auth_db
│   └── own_terrain_db
│       └── owns: terrain_db_template and all concrete terrain DBs
│
├── Privilege roles (NOLOGIN)
│   ├── grp_app_auth_ro
│   ├── grp_app_auth_rw
│   ├── grp_app_terrain_ro
│   │   └── readonly access to terrain DBs
│   └── grp_app_terrain_rw
│       └── readwrite access to terrain DBs
│
└── Technical stack roles (LOGIN)
    ├── app_terrain_db
    │   └── full management stack, may access template DB
    ├── app_desktop_db
    │   └── full management stack, may access template DB
    ├── app_mobile_db
    │   └── runtime client, no access to template DB
    └── app_gis_db
        └── runtime client, no access to template DB

Terrain DB access model
=======================
- terrain_db_template is visible only to web and desktop stacks
- concrete terrain DBs created from template should later grant:
    GRANT CONNECT ON DATABASE <terrain_db_name>
    TO grp_app_terrain_ro, grp_app_terrain_rw, gis_ro, gis_rw;
- readonly role grp_app_terrain_ro is prepared for future analysts/RO clients
*/

-- ---------------------------------------------------------------------
-- 1. Template database
-- ---------------------------------------------------------------------
CREATE DATABASE terrain_db_template
    OWNER own_terrain_db
    ENCODING 'UTF8'
    IS_TEMPLATE true;

\c terrain_db_template

ALTER DATABASE terrain_db_template OWNER TO own_terrain_db;
ALTER SCHEMA public OWNER TO own_terrain_db;

-- lock down PUBLIC
REVOKE ALL ON DATABASE terrain_db_template FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- only management stacks may connect to template DB
GRANT CONNECT ON DATABASE terrain_db_template TO app_terrain_db;
GRANT CONNECT ON DATABASE terrain_db_template TO app_desktop_db;

-- terrain privilege groups may use schema
GRANT USAGE ON SCHEMA public TO grp_app_terrain_ro;
GRANT USAGE ON SCHEMA public TO grp_app_terrain_rw;
GRANT USAGE ON SCHEMA public TO gis_ro, gis_rw;

-- owner role must be able to create objects in public schema
GRANT USAGE, CREATE ON SCHEMA public TO own_terrain_db;

-- ---------------------------------------------------------------------
-- 2. Extensions
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------
-- 3. Default privileges for future terrain objects
-- ---------------------------------------------------------------------
SET ROLE own_terrain_db;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON TABLES TO grp_app_terrain_ro;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO grp_app_terrain_rw;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT USAGE, SELECT ON SEQUENCES TO grp_app_terrain_ro;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO grp_app_terrain_rw;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT EXECUTE ON FUNCTIONS TO grp_app_terrain_ro, grp_app_terrain_rw;





-- ---------------------------------------------------------------------
-- 4. Create terrain objects as owner role
-- ---------------------------------------------------------------------
SET ROLE own_terrain_db;


--###### TABLES definitions here #######
-- #### Glossaries as tables #####
--######################################

---
-- GLOSSARIES
---

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
      'NI', -- nivelation for making surfaces
      'PF', -- point field for total station stationing
      'FI', -- point for precise finds measuring
      'PR', -- direct profile measuring
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
	object_typ varchar(150) NULL,
	superior_object int4 NULL,
	notes text NULL,
	CONSTRAINT tab_object_no_self_parent CHECK (((superior_object IS NULL) OR (superior_object <> id_object))),
	CONSTRAINT tab_object_pk PRIMARY KEY (id_object),
	CONSTRAINT tab_object_superior_fk FOREIGN KEY (superior_object) REFERENCES tab_object(id_object) ON DELETE RESTRICT
);


CREATE TABLE IF NOT EXISTS tab_object_inhum_grave (
  id_object        int4 PRIMARY KEY REFERENCES tab_object(id_object) ON DELETE CASCADE,

  preservation     text NULL,             -- e.g.. 'complete'|'partial'|'poor'...
  orientation_dir  text NULL,             -- head directed to N, W, NE...
  bone_map         jsonb NULL,            
  notes_grave      text NULL,
  anthropo_present BOOL NOT NULL DEFAULT false, -- was the grave excavated by anthropologist?
  burial_box_type  text NULL  -- e.g. coffin, sarcophagus, none, 
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
	excav_extent NUMERIC(3,0) NULL,
	ref_object int4 NULL,
	CONSTRAINT tab_sj_pk PRIMARY KEY (id_sj),
	CONSTRAINT tab_sj_excav_extent_chk CHECK (excav_extent IS NULL OR (excav_extent >= 0 AND excav_extent <= 100))
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
    CHECK (id_sketch ~ '^[0-9]+_[A-Za-z0-9._-]+[.][a-z0-9]+$'),
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
  id_drawing       VARCHAR(150) PRIMARY KEY,                       
  author           VARCHAR(100) NOT NULL REFERENCES gloss_personalia(mail),
  datum            date         NOT NULL,
  notes            text,
  mime_type        text         NOT NULL,
  file_size        bigint       NOT NULL CHECK (file_size >= 0),
  checksum_sha256  text         NOT NULL,
  -- mime and PK validation:
  CONSTRAINT tab_drawings_id_format_chk CHECK (id_drawing ~ '^[0-9]+_[A-Za-z0-9._-]+[.][a-z0-9]+$'),
  CONSTRAINT tab_drawings_mime_chk CHECK (mime_type IN ('image/jpeg','image/png','image/tiff','image/svg+xml','application/pdf'))
);
-- indexes:
CREATE INDEX tab_drawings_author_idx     ON tab_drawings (author);
CREATE INDEX tab_drawings_datum_idx      ON tab_drawings (datum);
CREATE INDEX tab_drawings_checksum_idx   ON tab_drawings (checksum_sha256);


CREATE TABLE tab_photograms (
	id_photogram TEXT NOT NULL,
	photogram_typ TEXT NOT NULL,
	author VARCHAR(100) NULL REFERENCES gloss_personalia(mail),
	datum DATE NOT NULL,
	ref_sketch VARCHAR(120) NULL,
	notes TEXT NULL,
	mime_type TEXT NOT NULL,
	file_size int8 NOT NULL,
	checksum_sha256 TEXT NOT NULL,
	ref_photo_from VARCHAR(150) NULL,
	ref_photo_to VARCHAR(150) NULL,
	CONSTRAINT tab_photograms_file_size_check CHECK ((file_size >= 0)),
	CONSTRAINT tab_photograms_id_format_chk CHECK (((id_photogram)::text ~ '^[0-9]+_[A-Za-z0-9._-]+[.][a-z0-9]+$'::text)),
	CONSTRAINT tab_photograms_mime_chk CHECK ((mime_type = ANY (ARRAY['image/jpeg'::text, 'image/png'::text, 'image/tiff'::text, 'image/svg+xml'::text, 'application/pdf'::text]))),
	CONSTRAINT tab_photograms_pkey PRIMARY KEY (id_photogram),
	CONSTRAINT tab_photograms_photo_from_fk FOREIGN KEY (ref_photo_from) REFERENCES tab_photos(id_photo) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tab_photograms_photo_to_fk FOREIGN KEY (ref_photo_to) REFERENCES tab_photos(id_photo) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tab_photograms_ref_sketch_fkey FOREIGN KEY (ref_sketch) REFERENCES tab_sketches(id_sketch) ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE INDEX tab_photograms_checksum_idx ON tab_photograms USING btree (checksum_sha256);
CREATE INDEX tab_photograms_datum_idx ON tab_photograms USING btree (datum);
CREATE INDEX tab_photograms_author_idx ON tab_photograms (author);
CREATE INDEX tab_photograms_ref_sketch_idx ON tab_photograms USING btree (ref_sketch);


-- tab_finds definition
-- mostly is it sack/bag as primary identificator - container for finds
-- -------------------------
-- Finds (one record = one bag of a given type from one SU)
-- -------------------------
CREATE TABLE IF NOT EXISTS tab_finds (
  id_find        int4  NOT NULL,                 -- manual ID (entered by user)
  ref_find_type  text  NOT NULL,                 -- FK -> gloss_find_type(type_code)
  description    text  NULL,
  count          int2  NULL,                     -- number of pieces in the bag, if known
  ref_sj         int4  NOT NULL,                 -- mandatory: comes from one stratigraphic unit
  ref_geopt      int4  NULL,                     -- optional: NO FK (geopts may be imported later)
  ref_polygon    text  NULL,                     -- optional: FK to tab_polygons
  box            int2  NULL,                     -- box for storing sacks/bags, if known
  CONSTRAINT tab_finds_pk PRIMARY KEY (id_find), CONSTRAINT tab_finds_sj_fk FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT tab_finds_polygon_fk FOREIGN KEY (ref_polygon) REFERENCES tab_polygons(polygon_name) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT tab_finds_find_type_fk FOREIGN KEY (ref_find_type) REFERENCES gloss_find_type(type_code) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT tab_finds_count_check CHECK (count IS NULL OR count > 0),
  CONSTRAINT tab_finds_box_check CHECK (box IS NULL OR box > 0)
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
	ref_photo VARCHAR(150) NOT NULL,
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
	ref_drawing VARCHAR(150) NOT NULL,
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
-- this table is clue between SUs and photograms (m:n)
CREATE TABLE tabaid_photogram_sj (
	id_aut serial4 NOT NULL,
	ref_photogram TEXT NOT NULL,
	ref_sj int4 NOT NULL,
	CONSTRAINT tabaid_photogram_sj_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_photogram_sj_fk_photogram FOREIGN KEY (ref_photogram) REFERENCES tab_photograms(id_photogram) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT tabaid_photogram_sj_fk_sj FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE ON UPDATE CASCADE
);


-- tabaid_sj_sketch definition
-- this tabaid clues SUs and Sketches (m:n)
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
-- this clues SUs and polygons (m:n)
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
  ref_photo    varchar(150) NOT NULL REFERENCES tab_photos(id_photo) ON UPDATE CASCADE ON DELETE CASCADE,
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
CREATE INDEX tabaid_polygon_photograms_photogram_idx ON tabaid_polygon_photograms USING btree (ref_photogram);


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
  ref_photo varchar(150) NOT NULL REFERENCES tab_photos(id_photo) ON UPDATE CASCADE ON DELETE CASCADE,
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
  ref_drawing varchar(150) NOT NULL REFERENCES tab_drawings(id_drawing) ON UPDATE CASCADE ON DELETE CASCADE,
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

-- this fnc loops over all SUs and returns related photos
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
-- this fnc loops over all SUs and returns related photograms
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
-- this fnc loops over all SUs and returns related sketches
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

-- this function requires the ID of section and lists all SUs cut by this section
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

-- this function takes ID of SU and list all sections cutting this SU 
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

-- this function takes SU id and returns list of all related photos
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

-- this function requires SU id and returns list of referenced photograms
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

-- this function use SU is as an argument and prints all sketches associated with
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
            RAISE NOTICE 'For SU %, Associated Photo: %', sj_record.id_sj, photo_info;
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
	SELECT
		fg.id_photogram,
		fg.photogram_typ,
		fg.ref_sketch
	FROM tab_photograms fg
	WHERE fg.ref_photo_from ILIKE fotopattern
	   OR fg.ref_photo_to ILIKE fotopattern;
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
	SELECT DISTINCT
		fo.id_photo,
		fo.photo_typ,
		fo.notes
	FROM tab_photograms tf
	JOIN tab_photos fo
	  ON fo.id_photo = tf.ref_photo_from
	  OR fo.id_photo = tf.ref_photo_to
	WHERE tf.id_photogram ILIKE fotogramm;
END;
   $function$
;

-- this function takes object/feature as argument and prints all SUs it consists of
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
-- this function loops over all SUs and prints all
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
        output_text := 'For SU ID=' || loop_sj_id || ' we have following items:';

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
-- this superfunction works same as previous but not for all SUs
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
    output_text := 'For SU ID=' || target_sj_id || ' we have following items:';

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


-- this function checks if all objects are created by SUs (has reference)
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
        RAISE NOTICE 'All objects are fine, having SUs';
    ELSE
        RAISE NOTICE 'Objects with missing SUs:%', E'\n' || missing_objects;
    END IF;
END;
$function$
;


-- this function checks if all SUs have at least one photo
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
        -- Print SU records without foto records
        RAISE NOTICE 'Following SUs have no foto entry:';
        FOR sj_id IN (SELECT id_sj FROM tab_sj sj WHERE NOT EXISTS (
            SELECT 1 FROM tabaid_photo_sj foto WHERE foto.ref_sj = sj.id_sj
        )) LOOP
            RAISE NOTICE '%', sj_id;
        END LOOP;
    ELSE
        -- All SU records have corresponding foto records
        RAISE NOTICE 'Check OK, all SUs have appropriate fotorecord';
    END IF;
END;
$function$
;

-- this function checks if SUs have or not sketches
CREATE OR REPLACE FUNCTION fnc_check_all_sjs_has_sketch()
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    sj_id INT;
BEGIN
    -- Check if there are SU records without corresponding sketch records
    IF EXISTS (
        SELECT 1
        FROM tab_sj
        WHERE NOT EXISTS (
            SELECT 1
            FROM tabaid_sj_sketch
            WHERE tabaid_sj_sketch.ref_sj = tab_sj.id_sj
        )
    ) THEN
        -- Print SU records without sketch records
        RAISE NOTICE 'Following SUs have no sketch entry:';
        FOR sj_id IN (SELECT id_sj FROM tab_sj WHERE NOT EXISTS (
            SELECT 1 FROM tabaid_sj_sketch WHERE tabaid_sj_sketch.ref_sj = tab_sj.id_sj
        )) LOOP
            RAISE NOTICE '%', sj_id;
        END LOOP;
    ELSE
        -- All SU records have corresponding foto records
        RAISE NOTICE 'Check OK, all SUs have appropriate sketch:';
    END IF;
END;
$function$
;


----
-- END OF CREATEING OBJECTS
----

-- ---------------------------------------------------------------------
-- 5. Grants to already created objects in template
-- ---------------------------------------------------------------------
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grp_app_terrain_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO grp_app_terrain_rw;
GRANT SELECT ON tab_geopts, tab_polygons, tab_section, tab_sj, tab_photos TO gis_ro, gis_rw;
GRANT INSERT, UPDATE, DELETE ON tab_geopts, tab_polygons, tab_section, tab_sj, tab_photos TO gis_rw;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO grp_app_terrain_ro;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO grp_app_terrain_rw;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO grp_app_terrain_ro, grp_app_terrain_rw;

-- grant usage on custom enum / custom types explicitly
GRANT USAGE ON TYPE public.section_type TO grp_app_terrain_ro, grp_app_terrain_rw;
GRANT USAGE ON TYPE public.geopt_code TO grp_app_terrain_ro, grp_app_terrain_rw;
GRANT USAGE ON TYPE public.allocation_reason TO grp_app_terrain_ro, grp_app_terrain_rw;

RESET ROLE;

-- BEGIN SPATIAL MODEL
-- ---------------------------------------------------------------------
-- 6. Spatial representations, source files and native GIS editing
-- ---------------------------------------------------------------------
SET ROLE own_terrain_db;
CREATE TABLE IF NOT EXISTS public.tab_spatial_files (
    id_file bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    file_kind text NOT NULL CHECK (file_kind IN ('cad_gis_source', 'world_file')),
    original_name text NOT NULL,
    storage_key text NOT NULL UNIQUE,
    mime_type text NOT NULL,
    file_size bigint NOT NULL CHECK (file_size >= 0),
    checksum_sha256 char(64) NOT NULL CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    source_software text,
    source_software_version text,
    notes text,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.tab_entity_geometries (
    id_geometry bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    ref_polygon text REFERENCES public.tab_polygons(polygon_name) ON UPDATE CASCADE ON DELETE CASCADE,
    ref_sj integer REFERENCES public.tab_sj(id_sj) ON UPDATE CASCADE ON DELETE CASCADE,
    ref_section integer REFERENCES public.tab_section(id_section) ON UPDATE CASCADE ON DELETE CASCADE,
    ref_find integer REFERENCES public.tab_finds(id_find) ON UPDATE CASCADE ON DELETE CASCADE,
    ref_sample integer REFERENCES public.tab_samples(id_sample) ON UPDATE CASCADE ON DELETE CASCADE,
    ref_photogram text REFERENCES public.tab_photograms(id_photogram) ON UPDATE CASCADE ON DELETE CASCADE,
    ref_drawing varchar(150) REFERENCES public.tab_drawings(id_drawing) ON UPDATE CASCADE ON DELETE CASCADE,
    geom geometry,
    geometry_role text NOT NULL DEFAULT 'outline' CHECK (geometry_role IN
        ('location','outline','top','bottom','extent','section_trace','other')),
    source_method text NOT NULL DEFAULT 'unknown' CHECK (source_method IN
        ('survey_points','digitized','derived','manual_edit','unknown')),
    source_software text,
    source_software_version text,
    is_proxy boolean NOT NULL DEFAULT true,
    notes text,
    build_method text CHECK (build_method IN ('point','ordered_line','ordered_polygon','convex_hull','legacy_line')),
    build_geometry_type text CHECK (build_geometry_type IN
        ('Point','MultiPoint','LineString','MultiLineString','Polygon','MultiPolygon')),
    -- Preserve historical FROM/TO recipes, including measurements imported later.
    -- New definitions use the ordered FK table below and clear this field.
    legacy_point_ranges jsonb,
    last_built_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT entity_geometry_one_parent CHECK (num_nonnulls(ref_polygon,ref_sj,
        ref_section,ref_find,ref_sample,ref_photogram,ref_drawing) = 1),
    CONSTRAINT entity_geometry_simple_type CHECK (geom IS NULL OR
        (GeometryType(geom) IN ('POINT','MULTIPOINT','LINESTRING','MULTILINESTRING','POLYGON','MULTIPOLYGON')
         AND ST_Zmflag(geom) IN (0,2) AND NOT ST_IsEmpty(geom))),
    CONSTRAINT entity_geometry_point_entities CHECK (
        (ref_find IS NULL AND ref_sample IS NULL) OR
        (geometry_role='location' AND (geom IS NULL OR GeometryType(geom)='POINT'))),
    CONSTRAINT entity_geometry_polygon_roles CHECK (ref_polygon IS NULL OR
        (geometry_role IN ('top','bottom') AND (geom IS NULL OR
         (GeometryType(geom)='POLYGON' AND ST_Zmflag(geom)=2)))),
    CONSTRAINT entity_geometry_section_role CHECK (ref_section IS NULL OR
        (geometry_role='section_trace' AND (geom IS NULL OR GeometryType(geom)='LINESTRING'))),
    CONSTRAINT entity_geometry_recipe CHECK ((build_method IS NULL) = (build_geometry_type IS NULL))
);
CREATE INDEX IF NOT EXISTS entity_geometry_gix ON public.tab_entity_geometries USING gist(geom);
CREATE UNIQUE INDEX IF NOT EXISTS entity_geometry_polygon_uq ON public.tab_entity_geometries(ref_polygon,geometry_role) WHERE ref_polygon IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS entity_geometry_section_uq ON public.tab_entity_geometries(ref_section) WHERE ref_section IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS entity_geometry_find_uq ON public.tab_entity_geometries(ref_find) WHERE ref_find IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS entity_geometry_sample_uq ON public.tab_entity_geometries(ref_sample) WHERE ref_sample IS NOT NULL;
CREATE INDEX IF NOT EXISTS entity_geometry_sj_idx ON public.tab_entity_geometries(ref_sj) WHERE ref_sj IS NOT NULL;
CREATE INDEX IF NOT EXISTS entity_geometry_photogram_idx ON public.tab_entity_geometries(ref_photogram) WHERE ref_photogram IS NOT NULL;
CREATE INDEX IF NOT EXISTS entity_geometry_drawing_idx ON public.tab_entity_geometries(ref_drawing) WHERE ref_drawing IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.tab_geometry_geopts (
    ref_geometry bigint NOT NULL REFERENCES public.tab_entity_geometries(id_geometry) ON DELETE CASCADE,
    part_no integer NOT NULL DEFAULT 1 CHECK (part_no>0),
    ring_no integer NOT NULL DEFAULT 0 CHECK (ring_no>=0),
    point_order integer NOT NULL CHECK (point_order>0),
    ref_geopt integer NOT NULL REFERENCES public.tab_geopts(id_pts) ON UPDATE CASCADE ON DELETE RESTRICT,
    PRIMARY KEY(ref_geometry,part_no,ring_no,point_order)
);
CREATE INDEX IF NOT EXISTS geometry_geopts_point_idx ON public.tab_geometry_geopts(ref_geopt);
CREATE TABLE IF NOT EXISTS public.tabaid_sj_spatial_files (
    ref_sj integer NOT NULL REFERENCES public.tab_sj(id_sj) ON UPDATE CASCADE ON DELETE CASCADE,
    ref_file bigint NOT NULL REFERENCES public.tab_spatial_files(id_file) ON DELETE RESTRICT,
    PRIMARY KEY(ref_sj,ref_file)
);
CREATE TABLE IF NOT EXISTS public.tabaid_geometry_files (
    ref_geometry bigint NOT NULL REFERENCES public.tab_entity_geometries(id_geometry) ON DELETE CASCADE,
    ref_file bigint NOT NULL REFERENCES public.tab_spatial_files(id_file) ON DELETE RESTRICT,
    PRIMARY KEY(ref_geometry,ref_file)
);

ALTER TABLE public.tab_photograms ADD COLUMN IF NOT EXISTS ref_world_file bigint
    REFERENCES public.tab_spatial_files(id_file) ON DELETE RESTRICT;
ALTER TABLE public.tab_photograms ADD COLUMN IF NOT EXISTS has_world_file boolean
    GENERATED ALWAYS AS (ref_world_file IS NOT NULL) STORED;

CREATE OR REPLACE FUNCTION public.check_photogram_world_file() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
    IF NEW.ref_world_file IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.tab_spatial_files WHERE id_file=NEW.ref_world_file AND file_kind='world_file'
    ) THEN RAISE EXCEPTION 'The photogram attachment must be a world file'; END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS check_photogram_world_file ON public.tab_photograms;
CREATE TRIGGER check_photogram_world_file BEFORE INSERT OR UPDATE OF ref_world_file ON public.tab_photograms
FOR EACH ROW EXECUTE FUNCTION public.check_photogram_world_file();

CREATE OR REPLACE FUNCTION public.preserve_spatial_file_kind() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    IF NEW.file_kind<>OLD.file_kind THEN RAISE EXCEPTION 'An attachment file kind cannot be changed'; END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS preserve_spatial_file_kind ON public.tab_spatial_files;
CREATE TRIGGER preserve_spatial_file_kind BEFORE UPDATE ON public.tab_spatial_files
FOR EACH ROW EXECUTE FUNCTION public.preserve_spatial_file_kind();

CREATE OR REPLACE FUNCTION public.validate_entity_geometry() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE expected_srid integer; operation text;
BEGIN
    operation := COALESCE(current_setting('archeodb.geometry_operation',true),'');
    IF NEW.geom IS NOT NULL THEN
        expected_srid := Find_SRID('public','tab_geopts','pts_geom');
        IF operation <> 'migration' AND expected_srid<=0 THEN
            RAISE EXCEPTION 'Configure the project EPSG before defining geometry';
        END IF;
        IF ST_SRID(NEW.geom)<>expected_srid THEN
            RAISE EXCEPTION 'Geometry SRID % differs from project SRID %',ST_SRID(NEW.geom),expected_srid;
        END IF;
        IF NOT ST_IsValid(NEW.geom) THEN RAISE EXCEPTION 'Invalid geometry: %',ST_IsValidReason(NEW.geom); END IF;
    END IF;
    IF TG_OP='UPDATE' THEN
        IF NEW.id_geometry IS DISTINCT FROM OLD.id_geometry THEN RAISE EXCEPTION 'A representation ID cannot be changed'; END IF;
        IF NEW.geometry_role IS DISTINCT FROM OLD.geometry_role AND OLD.ref_polygon IS NOT NULL THEN
            RAISE EXCEPTION 'Delete the polygon representation before changing its side';
        END IF;
        IF ROW(NEW.ref_polygon,NEW.ref_sj,NEW.ref_section,NEW.ref_find,NEW.ref_sample,NEW.ref_photogram,NEW.ref_drawing)
           IS DISTINCT FROM ROW(OLD.ref_polygon,OLD.ref_sj,OLD.ref_section,OLD.ref_find,OLD.ref_sample,OLD.ref_photogram,OLD.ref_drawing)
           AND pg_trigger_depth()=1 THEN
            RAISE EXCEPTION 'A representation cannot be reassigned to another entity';
        END IF;
        NEW.created_at := OLD.created_at;
        IF NEW.geom IS DISTINCT FROM OLD.geom AND operation NOT IN ('build','migration') THEN
            NEW.source_method := 'manual_edit';
            IF NEW.source_software IS NOT DISTINCT FROM OLD.source_software THEN NEW.source_software:=NULL; END IF;
            IF NEW.source_software_version IS NOT DISTINCT FROM OLD.source_software_version THEN NEW.source_software_version:=NULL; END IF;
        END IF;
    END IF;
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS validate_entity_geometry ON public.tab_entity_geometries;
CREATE TRIGGER validate_entity_geometry BEFORE INSERT OR UPDATE ON public.tab_entity_geometries
FOR EACH ROW EXECUTE FUNCTION public.validate_entity_geometry();

-- Keep legacy polygon readers usable while all clients adopt the common model.
CREATE OR REPLACE FUNCTION public.sync_polygon_geometry_columns() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE p text; side text; value geometry;
BEGIN
    IF pg_trigger_depth()>1 THEN RETURN NULL; END IF;
    IF TG_OP='DELETE' THEN p:=OLD.ref_polygon; side:=OLD.geometry_role;
    ELSE p:=NEW.ref_polygon; side:=NEW.geometry_role; value:=NEW.geom; END IF;
    IF p IS NOT NULL THEN
        EXECUTE format('UPDATE public.tab_polygons SET %I=$1 WHERE polygon_name=$2','geom_'||side) USING value,p;
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS sync_polygon_geometry_columns ON public.tab_entity_geometries;
CREATE TRIGGER sync_polygon_geometry_columns AFTER INSERT OR UPDATE OR DELETE ON public.tab_entity_geometries
FOR EACH ROW EXECUTE FUNCTION public.sync_polygon_geometry_columns();
CREATE OR REPLACE FUNCTION public.sync_legacy_polygon_geometry() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE side text; value geometry;
BEGIN
    IF pg_trigger_depth()>1 THEN RETURN NEW; END IF;
    FOREACH side IN ARRAY ARRAY['top','bottom'] LOOP
        IF side='top' THEN
            IF TG_OP='UPDATE' AND NEW.geom_top IS NOT DISTINCT FROM OLD.geom_top THEN CONTINUE; END IF;
            value:=NEW.geom_top;
        ELSE
            IF TG_OP='UPDATE' AND NEW.geom_bottom IS NOT DISTINCT FROM OLD.geom_bottom THEN CONTINUE; END IF;
            value:=NEW.geom_bottom;
        END IF;
        UPDATE public.tab_entity_geometries SET geom=value
        WHERE ref_polygon=NEW.polygon_name AND geometry_role=side;
        IF NOT FOUND AND value IS NOT NULL THEN
            INSERT INTO public.tab_entity_geometries(ref_polygon,geometry_role,geom,source_method,is_proxy)
            VALUES(NEW.polygon_name,side,value,'manual_edit',false);
        END IF;
    END LOOP;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS sync_legacy_polygon_geometry ON public.tab_polygons;
CREATE TRIGGER sync_legacy_polygon_geometry AFTER INSERT OR UPDATE ON public.tab_polygons
FOR EACH ROW EXECUTE FUNCTION public.sync_legacy_polygon_geometry();

CREATE OR REPLACE FUNCTION public.build_entity_geometry(p_id bigint,p_replace_manual boolean DEFAULT false)
RETURNS geometry LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE r public.tab_entity_geometries%ROWTYPE; part record; ring record;
    pts geometry[]; shells geometry[]:=ARRAY[]::geometry[]; holes geometry[];
    line geometry; result geometry; previous_operation text;
BEGIN
    SELECT * INTO STRICT r FROM public.tab_entity_geometries WHERE id_geometry=p_id FOR UPDATE;
    IF r.build_method IS NULL THEN RAISE EXCEPTION 'Geometry % has no point construction recipe',p_id; END IF;
    IF r.geom IS NOT NULL AND r.source_method<>'survey_points' AND NOT p_replace_manual THEN
        RAISE EXCEPTION 'Confirm replacing the existing geometry and its source method';
    END IF;
    IF Find_SRID('public','tab_geopts','pts_geom')<=0 THEN RAISE EXCEPTION 'Configure the project EPSG first'; END IF;
    IF r.legacy_point_ranges IS NOT NULL THEN
        SELECT array_agg(g.pts_geom ORDER BY g.id_pts) INTO pts FROM public.tab_geopts g
        WHERE EXISTS(SELECT 1 FROM jsonb_array_elements(r.legacy_point_ranges) b
            WHERE g.id_pts BETWEEN (b->>'from')::integer AND (b->>'to')::integer);
        IF array_length(pts,1) IS NULL OR array_position(pts,NULL) IS NOT NULL THEN
            RAISE EXCEPTION 'Source points are missing or have no project geometry';
        END IF;
        IF r.build_method='point' THEN
            IF array_length(pts,1)<>1 THEN RAISE EXCEPTION 'A point requires exactly one source point'; END IF;
            result:=pts[1];
        ELSIF r.build_method='convex_hull' THEN result:=ST_ConvexHull(ST_Collect(pts));
        ELSE
            line:=ST_MakeLine(pts);
            IF r.build_method='ordered_polygon' THEN
                IF NOT ST_IsClosed(line) THEN line:=ST_AddPoint(line,ST_StartPoint(line)); END IF;
                result:=ST_MakePolygon(line);
            ELSE result:=line; END IF;
        END IF;
    ELSE
        IF NOT EXISTS(SELECT 1 FROM public.tab_geometry_geopts WHERE ref_geometry=p_id) THEN
            RAISE EXCEPTION 'Select source points first';
        END IF;
        FOR part IN SELECT DISTINCT part_no FROM public.tab_geometry_geopts WHERE ref_geometry=p_id ORDER BY part_no LOOP
            line:=NULL; holes:=ARRAY[]::geometry[];
            FOR ring IN SELECT DISTINCT ring_no FROM public.tab_geometry_geopts
                WHERE ref_geometry=p_id AND part_no=part.part_no ORDER BY ring_no LOOP
                SELECT array_agg(g.pts_geom ORDER BY b.point_order) INTO pts
                FROM public.tab_geometry_geopts b JOIN public.tab_geopts g ON g.id_pts=b.ref_geopt
                WHERE b.ref_geometry=p_id AND b.part_no=part.part_no AND b.ring_no=ring.ring_no;
                IF array_position(pts,NULL) IS NOT NULL THEN RAISE EXCEPTION 'A selected point has no project geometry'; END IF;
                IF r.build_method='point' THEN
                    IF array_length(pts,1)<>1 OR ring.ring_no<>0 THEN RAISE EXCEPTION 'Each point part requires one source point'; END IF;
                    line:=pts[1];
                ELSIF r.build_method='convex_hull' THEN
                    IF ring.ring_no<>0 THEN RAISE EXCEPTION 'An envelope does not accept inner rings'; END IF;
                    line:=ST_ConvexHull(ST_Collect(pts));
                ELSIF r.build_method IN ('ordered_line','legacy_line') THEN
                    IF ring.ring_no<>0 OR array_length(pts,1)<2 THEN RAISE EXCEPTION 'A line requires at least two ordered points'; END IF;
                    line:=ST_MakeLine(pts);
                ELSE
                    IF array_length(pts,1)<3 THEN RAISE EXCEPTION 'A polygon ring requires at least three vertices'; END IF;
                    result:=ST_MakeLine(pts);
                    IF NOT ST_IsClosed(result) THEN result:=ST_AddPoint(result,ST_StartPoint(result)); END IF;
                    IF ring.ring_no=0 THEN line:=result; ELSE holes:=array_append(holes,result); END IF;
                END IF;
            END LOOP;
            IF line IS NULL THEN RAISE EXCEPTION 'An outer ring is required'; END IF;
            IF r.build_method='ordered_polygon' THEN line:=ST_MakePolygon(line,holes); END IF;
            shells:=array_append(shells,line);
        END LOOP;
        IF r.build_geometry_type LIKE 'Multi%' THEN result:=ST_Multi(ST_Collect(shells));
        ELSE
            IF array_length(shells,1)<>1 THEN RAISE EXCEPTION 'Use a Multi geometry for multiple parts'; END IF;
            result:=shells[1];
        END IF;
    END IF;
    IF GeometryType(result)<>upper(r.build_geometry_type) OR NOT ST_IsValid(result) THEN
        RAISE EXCEPTION 'The selected points do not form a valid %',r.build_geometry_type;
    END IF;
    IF r.ref_section IS NOT NULL AND r.build_method<>'legacy_line' AND ST_NPoints(result)<>2 THEN
        RAISE EXCEPTION 'A section requires exactly two source points';
    END IF;
    previous_operation:=COALESCE(current_setting('archeodb.geometry_operation',true),'');
    PERFORM set_config('archeodb.geometry_operation','build',true);
    UPDATE public.tab_entity_geometries SET geom=result,source_method='survey_points',
        source_software='ArcheoDB',source_software_version=NULL,last_built_at=clock_timestamp()
    WHERE id_geometry=p_id;
    PERFORM set_config('archeodb.geometry_operation',previous_operation,true);
    RETURN result;
END $$;

-- Views expose one geometry type and dimension to native GIS clients.
-- Legacy callers receive the same protection against discarding manual edits.
CREATE OR REPLACE FUNCTION public.rebuild_polygon_geoms_from_geopts(p_polygon_name text)
RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE r public.tab_entity_geometries%ROWTYPE; side text; ranges jsonb;
BEGIN
    FOREACH side IN ARRAY ARRAY['top','bottom'] LOOP
        EXECUTE format('SELECT jsonb_agg(jsonb_build_object(''from'',pts_from,''to'',pts_to) ORDER BY pts_from,pts_to)
            FROM public.%I WHERE ref_polygon=$1','tab_polygon_geopts_binding_'||side) INTO ranges USING p_polygon_name;
        SELECT * INTO r FROM public.tab_entity_geometries
            WHERE ref_polygon=p_polygon_name AND geometry_role=side FOR UPDATE;
        IF NOT FOUND THEN
            IF ranges IS NULL THEN CONTINUE; END IF;
            INSERT INTO public.tab_entity_geometries(ref_polygon,geometry_role,is_proxy,build_method,build_geometry_type,legacy_point_ranges)
            VALUES(p_polygon_name,side,false,'ordered_polygon','Polygon',ranges) RETURNING * INTO r;
        ELSIF r.legacy_point_ranges IS NOT NULL AND ranges IS NOT NULL THEN
            UPDATE public.tab_entity_geometries SET legacy_point_ranges=ranges WHERE id_geometry=r.id_geometry;
        ELSIF ranges IS NOT NULL THEN
            RAISE EXCEPTION 'Use Define geometry to replace a representation with an explicit point recipe or GIS geometry';
        ELSIF r.build_method IS NULL THEN CONTINUE;
        END IF;
        PERFORM public.build_entity_geometry(r.id_geometry,false);
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.write_geometry_view() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
    IF TG_OP='DELETE' THEN DELETE FROM public.tab_entity_geometries WHERE id_geometry=OLD.id_geometry; RETURN OLD; END IF;
    IF TG_OP='INSERT' THEN
        INSERT INTO public.tab_entity_geometries(ref_polygon,ref_sj,ref_section,ref_find,ref_sample,ref_photogram,ref_drawing,
            geom,geometry_role,source_method,source_software,source_software_version,is_proxy,notes)
        VALUES(NEW.ref_polygon,NEW.ref_sj,NEW.ref_section,NEW.ref_find,NEW.ref_sample,NEW.ref_photogram,NEW.ref_drawing,
            NEW.geom,COALESCE(NEW.geometry_role,CASE WHEN NEW.ref_find IS NOT NULL OR NEW.ref_sample IS NOT NULL
                THEN 'location' WHEN NEW.ref_section IS NOT NULL THEN 'section_trace' ELSE 'outline' END),
            COALESCE(NEW.source_method,'digitized'),NEW.source_software,
            NEW.source_software_version,COALESCE(NEW.is_proxy,true),NEW.notes)
        RETURNING id_geometry INTO NEW.id_geometry;
    ELSE
        IF NEW.id_geometry IS DISTINCT FROM OLD.id_geometry THEN RAISE EXCEPTION 'A representation ID cannot be changed'; END IF;
        UPDATE public.tab_entity_geometries SET ref_polygon=NEW.ref_polygon,ref_sj=NEW.ref_sj,ref_section=NEW.ref_section,
            ref_find=NEW.ref_find,ref_sample=NEW.ref_sample,ref_photogram=NEW.ref_photogram,ref_drawing=NEW.ref_drawing,
            geom=NEW.geom,geometry_role=NEW.geometry_role,source_method=NEW.source_method,source_software=NEW.source_software,
            source_software_version=NEW.source_software_version,is_proxy=NEW.is_proxy,notes=NEW.notes
        WHERE id_geometry=OLD.id_geometry;
    END IF;
    SELECT geometry_role,source_method,source_software,source_software_version,is_proxy,created_at,updated_at
    INTO NEW.geometry_role,NEW.source_method,NEW.source_software,NEW.source_software_version,NEW.is_proxy,NEW.created_at,NEW.updated_at
    FROM public.tab_entity_geometries WHERE id_geometry=NEW.id_geometry;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.refresh_geometry_views() RETURNS void
-- Views must retain the schema owner's identity even when an application or
-- administrator calls set_project_srid(), so later upgrades can replace them.
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE kind text; dims integer; view_name text; srid integer;
BEGIN
    srid:=Find_SRID('public','tab_geopts','pts_geom');
    FOREACH kind IN ARRAY ARRAY['Point','MultiPoint','LineString','MultiLineString','Polygon','MultiPolygon'] LOOP
        FOREACH dims IN ARRAY ARRAY[2,3] LOOP
            view_name:='v_gis_'||lower(kind)||CASE WHEN dims=3 THEN '_z' ELSE '_xy' END;
            EXECUTE format('DROP VIEW IF EXISTS public.%I',view_name);
            EXECUTE format('CREATE VIEW public.%I AS SELECT id_geometry,ref_polygon,ref_sj,ref_section,ref_find,ref_sample,
                ref_photogram,ref_drawing,geometry_role,source_method,source_software,source_software_version,is_proxy,notes,
                created_at,updated_at,geom::geometry(%s,%s) AS geom FROM public.tab_entity_geometries
                WHERE GeometryType(geom)=%L AND ST_CoordDim(geom)=%s',view_name,
                kind||CASE WHEN dims=3 THEN 'Z' ELSE '' END,srid,upper(kind),dims);
            EXECUTE format('CREATE TRIGGER write_geometry_view INSTEAD OF INSERT OR UPDATE OR DELETE ON public.%I
                FOR EACH ROW EXECUTE FUNCTION public.write_geometry_view()',view_name);
            EXECUTE format('GRANT SELECT ON public.%I TO gis_ro,gis_rw',view_name);
            EXECUTE format('GRANT INSERT,UPDATE,DELETE ON public.%I TO gis_rw',view_name);
        END LOOP;
    END LOOP;
END $$;

-- Preserve mixed XY/XYZ in the common table when assigning a project SRID.
CREATE OR REPLACE FUNCTION public.set_project_srid(target_srid integer,in_schema text DEFAULT current_schema())
RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE r record; type_name text;
BEGIN
    IF target_srid IS NULL OR target_srid<=0 OR NOT EXISTS(SELECT 1 FROM public.spatial_ref_sys WHERE srid=target_srid) THEN
        RAISE EXCEPTION 'Invalid project SRID: %',target_srid;
    END IF;
    -- Casts in GIS views depend on the geometry column's type modifier.
    FOR r IN SELECT viewname FROM pg_views WHERE schemaname='public' AND viewname LIKE 'v_gis_%' LOOP
        EXECUTE format('DROP VIEW public.%I',r.viewname);
    END LOOP;
    FOR r IN SELECT c.relname,a.attname,postgis_typmod_type(a.atttypmod) AS kind,postgis_typmod_dims(a.atttypmod) AS dims
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid
        JOIN pg_type t ON t.oid=a.atttypid WHERE n.nspname=in_schema AND c.relkind IN ('r','p')
        AND a.attnum>0 AND NOT a.attisdropped AND t.typname='geometry' AND c.relname<>'tab_entity_geometries' LOOP
        type_name:=r.kind;
        IF type_name !~* '(ZM|Z|M)$' THEN type_name:=type_name||CASE WHEN r.dims=3 THEN 'Z' WHEN r.dims=4 THEN 'ZM' ELSE '' END; END IF;
        EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN %I TYPE geometry(%s,%s) USING ST_SetSRID(%I,%s)',
            in_schema,r.relname,r.attname,type_name,target_srid,r.attname,target_srid);
    END LOOP;
    PERFORM set_config('archeodb.geometry_operation','migration',true);
    UPDATE public.tab_entity_geometries SET geom=ST_SetSRID(geom,target_srid) WHERE geom IS NOT NULL;
    PERFORM set_config('archeodb.geometry_operation','',true);
    PERFORM public.refresh_geometry_views();
END $$;

SELECT public.refresh_geometry_views();
GRANT SELECT ON public.tab_entity_geometries,public.tab_geometry_geopts,public.tab_spatial_files,
    public.tabaid_sj_spatial_files,public.tabaid_geometry_files TO gis_ro,gis_rw;
GRANT INSERT,UPDATE,DELETE ON public.tab_entity_geometries,public.tab_geometry_geopts TO gis_rw;
GRANT SELECT ON public.tab_finds,public.tab_samples,public.tab_photograms,public.tab_drawings TO gis_ro,gis_rw;
GRANT INSERT,UPDATE,DELETE ON public.tab_finds,public.tab_samples,public.tab_photograms,public.tab_drawings TO gis_rw;
GRANT SELECT ON public.gloss_find_type,public.gloss_sample_type TO gis_ro,gis_rw;
GRANT USAGE,SELECT ON SEQUENCE public.tab_entity_geometries_id_geometry_seq TO gis_rw;
REVOKE ALL ON FUNCTION public.build_entity_geometry(bigint,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.build_entity_geometry(bigint,boolean) TO gis_rw,grp_app_terrain_rw;
REVOKE ALL ON FUNCTION public.refresh_geometry_views() FROM PUBLIC;
RESET ROLE;
-- END SPATIAL MODEL

/*
Provisioning note for future concrete terrain DBs
=================================================

Use this pattern from web/desktop stack:

CREATE DATABASE some_terrain_db
    OWNER own_terrain_db
    ENCODING 'UTF8'
    TEMPLATE terrain_db_template;

REVOKE ALL ON DATABASE some_terrain_db FROM PUBLIC;
GRANT CONNECT ON DATABASE some_terrain_db TO grp_app_terrain_ro;
GRANT CONNECT ON DATABASE some_terrain_db TO grp_app_terrain_rw;
GRANT CONNECT ON DATABASE some_terrain_db TO gis_ro, gis_rw;

Important:
- mobile/GIS connect only to SPECIFIC terrain DBs
- mobile/GIS do not connect to terrain_db_template
*/
