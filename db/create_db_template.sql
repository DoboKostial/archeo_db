-- This is basix SQL script
-- basix role and privileges
-- making database with owner grp_dbas creating all tables under this account

CREATE ROLE grp_dbas WITH CREATEDB CREATEROLE INHERIT;
GRANT pg_write_all_data TO grp_dbas;
CREATE ROLE grp_analysts WITH INHERIT;
GRANT pg_read_all_data TO grp_analysts;

-- This database is intended to be a template while assuming
-- cluster would server for more terrain DBs. After template creation You are able to create new database with 'CREATE DATABASE XYZ WITH TEMPLATE = 'terrain_db_template;''
CREATE DATABASE terrain_db_template OWNER grp_dbas ENCODING 'UTF8' IS_TEMPLATE true;

-- Connect to the template database to configure it
\c terrain_db_template;

-- default privileges for users
ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO grp_dbas;
ALTER DEFAULT PRIVILEGES GRANT ALL ON SEQUENCES TO grp_dbas;
ALTER DEFAULT PRIVILEGES GRANT ALL ON FUNCTIONS TO grp_dbas;
ALTER DEFAULT PRIVILEGES GRANT ALL ON TYPES TO grp_dbas;
ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO grp_dbas;

SET ROLE grp_dbas;

--###### TABLES definitions here #######
-- #### Glossaries as tables #####
--######################################


-- public.gloss_docu_typ definition

CREATE TABLE gloss_docu_typ (
	docu_typ varchar(60) NOT NULL,
	description varchar(200) NULL,
	CONSTRAINT gloss_docu_typ_pk PRIMARY KEY (docu_typ)
);


-- public.gloss_object_type definition
-- glossary for archaeological objects

CREATE TABLE gloss_object_type (
	object_typ varchar(100) NOT NULL,
	description_typ varchar(200) NULL,
	CONSTRAINT gloss_object_type_pk PRIMARY KEY (object_typ)
);


-- public.gloss_personalia definition

CREATE TABLE gloss_personalia (
	mail varchar(80) NOT NULL,
	"name" varchar(60) NULL,
	surname varchar(100) NULL,
	CONSTRAINT gloss_personalia_pk PRIMARY KEY (mail)
);
CREATE UNIQUE INDEX gloss_personalia_mail_idx ON public.gloss_personalia USING btree (mail);

------
-- ### Here tables - terrain entities
------
-- public.tab_cut definition

CREATE TABLE tab_cut (
	id_cut int4 NOT NULL,
	description varchar(500) NULL,
	CONSTRAINT tab_cut_pk PRIMARY KEY (id_cut)
);


-- public.tab_geopts definition

CREATE TABLE tab_geopts (
	id_pts int4 NOT NULL,
	x float8 NULL,
	y float8 NULL,
	h float8 NULL,
	code varchar(30) NULL,
	notes varchar(200) NULL,
	CONSTRAINT tab_geomeasuring_pk PRIMARY KEY (id_pts)
);
CREATE UNIQUE INDEX tab_geomeasuring_id_pts_idx ON public.tab_geopts USING btree (id_pts);


-- public.tab_object definition

CREATE TABLE tab_object (
	id_object int4 NOT NULL,
	object_typ varchar(100) NULL,
	superior_object int4 NULL DEFAULT 0,
	notes varchar(600) NULL,
	CONSTRAINT tab_object_pk PRIMARY KEY (id_object)
);


-- public.tab_polygon definition

CREATE TABLE tab_polygon (
	id_polygon int4 NOT NULL,
	polygon_typ varchar(50) NULL,
	superior_polygon int4 NULL DEFAULT 0,
	notes varchar(200) NULL,
	CONSTRAINT tab_polygon_pk PRIMARY KEY (id_polygon)
);


-- public.tab_sj_stratigraphy definition

CREATE TABLE tab_sj_stratigraphy (
	id_aut serial4 NOT NULL,
	ref_sj1 int4 NULL,
	relation varchar(20) NULL,
	ref_sj2 int4 NULL,
	CONSTRAINT tab_sj_stratigraphy_pk PRIMARY KEY (id_aut)
);


-- public.tab_foto definition

CREATE TABLE tab_foto (
	id_foto varchar(100) NOT NULL,
	foto_typ varchar(60) NULL,
	datum date NULL,
	author varchar(100) NULL,
	notes varchar(500) NULL,
	CONSTRAINT tab_foto_pk PRIMARY KEY (id_foto),
	CONSTRAINT tab_foto_fk FOREIGN KEY (author) REFERENCES gloss_personalia(mail)
);


-- public.tab_sj definition

CREATE TABLE public.tab_sj (
	id_sj int4 NOT NULL,
	sj_typ varchar(20) NULL,
	description varchar(800) NULL,
	interpretation varchar(400) NULL,
	author varchar(100) NULL,
	recorded date NULL,
	docu_plan bool NULL,
	docu_vertical bool NULL,
	ref_object int4 NULL,
	CONSTRAINT tab_sj_pk PRIMARY KEY (id_sj)
);
CREATE UNIQUE INDEX tab_sj_id_sj_idx ON public.tab_sj USING btree (id_sj);

-- public.tab_sj foreign keys
ALTER TABLE public.tab_sj ADD CONSTRAINT tab_sj_fk FOREIGN KEY (author) REFERENCES public.gloss_personalia(mail);




-- public.tab_sj_deposit definition

CREATE TABLE tab_sj_deposit (
	id_deposit int4 NOT NULL,
	deposit_typ varchar(20) NULL,
	color varchar(50) NULL,
	boundary_visibility varchar(50) NULL,
	"structure" varchar(80) NULL,
	compactness varchar(50) NULL,
	deposit_removed varchar(50) NULL,
	CONSTRAINT tab_sj_deposit_pk PRIMARY KEY (id_deposit),
	CONSTRAINT tab_sj_deposit_fk FOREIGN KEY (id_deposit) REFERENCES tab_sj(id_sj)
);
CREATE UNIQUE INDEX tab_sj_deposit_id_deposit_idx ON public.tab_sj_deposit USING btree (id_deposit);


-- public.tab_sj_negativ definition

CREATE TABLE tab_sj_negativ (
	id_negativ int4 NOT NULL,
	negativ_typ varchar(40) NULL,
	excav_extent varchar(40) NULL,
	ident_niveau_cut bool NULL,
	shape_plan varchar(50) NULL,
	shape_sides varchar(50) NULL,
	shape_bottom varchar(50) NULL,
	CONSTRAINT tab_sj_negativ_pk PRIMARY KEY (id_negativ),
	CONSTRAINT tab_sj_negativ_fk FOREIGN KEY (id_negativ) REFERENCES tab_sj(id_sj)
);
CREATE UNIQUE INDEX tab_sj_negativ_id_negativ_idx ON public.tab_sj_negativ USING btree (id_negativ);


-- public.tab_sj_structure definition

CREATE TABLE tab_sj_structure (
	id_structure int4 NOT NULL,
	structure_typ varchar(80) NULL,
	construction_typ varchar(100) NULL,
	binder varchar(60) NULL,
	basic_material varchar(60) NULL,
	length_m float8 NULL,
	width_m float8 NULL,
	height_m float8 NULL,
	CONSTRAINT tab_sj_structure_pk PRIMARY KEY (id_structure),
	CONSTRAINT tab_sj_structure_fk FOREIGN KEY (id_structure) REFERENCES tab_sj(id_sj)
);
CREATE UNIQUE INDEX tab_sj_structure_id_structure_idx ON public.tab_sj_structure USING btree (id_structure);


-- public.tab_sketch definition

CREATE TABLE tab_sketch (
	id_sketch varchar(100) NOT NULL,
	sketch_typ varchar(80) NULL,
	author varchar(100) NULL,
	datum date NULL,
	notes varchar(800) NULL,
	CONSTRAINT tab_sketch_pk PRIMARY KEY (id_sketch),
	CONSTRAINT tab_sketch_fk FOREIGN KEY (author) REFERENCES gloss_personalia(mail)
);


-- public.tabaid_foto_sj definition
-- this table connects fotos and SJ (stratigraphic units)

CREATE TABLE tabaid_foto_sj (
	id_aut serial4 NOT NULL,
	ref_foto varchar(100) NULL,
	ref_sj int4 NULL,
	CONSTRAINT tabaid_foto_sj_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_foto_sj_fk FOREIGN KEY (ref_foto) REFERENCES tab_foto(id_foto) ON DELETE CASCADE,
	CONSTRAINT tabaid_foto_sj_fk_1 FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON DELETE CASCADE
);


-- public.tab_fotogram definition

CREATE TABLE tab_fotogram (
	id_fotogram varchar(80) NOT NULL,
	fotogram_typ varchar(60) NULL,
	ref_sketch varchar(60) NULL,
	notes varchar(800) NULL,
	CONSTRAINT tab_fotogram_pk PRIMARY KEY (id_fotogram),
	CONSTRAINT tab_fotogram_fk FOREIGN KEY (ref_sketch) REFERENCES tab_sketch(id_sketch)
);
CREATE INDEX tab_fotogram_id_fotogram_idx ON public.tab_fotogram USING btree (id_fotogram);


-- public.tab_sack definition
-- sacks are containers for finds

CREATE TABLE tab_sack (
	id_sack int4 NOT NULL,
	ref_sj int4 NULL,
	"content" varchar(80) NULL,
	description varchar(600) NULL,
	"number" int4 NULL,
	CONSTRAINT tab_sack_pk PRIMARY KEY (id_sack),
	CONSTRAINT tab_sack_fk FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj)
);


-- public.tabaid_cut_fotogram definition
-- this table connects cuts and fotograms (m:n)


CREATE TABLE tabaid_cut_fotogram (
	id_aut serial4 NOT NULL,
	ref_cut int4 NULL,
	ref_fotogram varchar(100) NULL,
	CONSTRAINT tabaid_cut_fotogram_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_cut_fotogram_fk FOREIGN KEY (ref_fotogram) REFERENCES tab_fotogram(id_fotogram) ON UPDATE CASCADE,
	CONSTRAINT tabaid_cut_fotogram_fk_1 FOREIGN KEY (ref_cut) REFERENCES tab_cut(id_cut) ON UPDATE CASCADE
);


-- public.tabaid_fotogram_foto definition
-- this table connects fotograms and fotos (m:n)


CREATE TABLE tabaid_fotogram_foto (
	id_aut serial4 NOT NULL,
	ref_fotogram varchar(100) NULL,
	ref_foto varchar(100) NULL,
	CONSTRAINT tabaid_fotogram_foto_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_fotogram_foto_fk FOREIGN KEY (ref_fotogram) REFERENCES tab_fotogram(id_fotogram) ON UPDATE CASCADE,
	CONSTRAINT tabaid_fotogram_foto_fk_1 FOREIGN KEY (ref_foto) REFERENCES tab_foto(id_foto) ON UPDATE CASCADE
);


-- public.tabaid_fotogram_sj definition
-- this table is clue between SJs and fotogramss (m:n)

CREATE TABLE tabaid_fotogram_sj (
	id_aut serial4 NOT NULL,
	ref_fotogram varchar(100) NULL,
	ref_sj int4 NULL,
	CONSTRAINT tabaid_fotogram_sj_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_fotogram_sj_fk FOREIGN KEY (ref_fotogram) REFERENCES tab_fotogram(id_fotogram) ON UPDATE CASCADE,
	CONSTRAINT tabaid_fotogram_sj_fk_1 FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj) ON UPDATE CASCADE
);

-- public.tabaid_sj_cut definition
-- this table is clue between SJs and CUTs (m:n)

CREATE TABLE public.tabaid_sj_cut (
	id_aut serial4 NOT NULL,
	ref_sj int4 NOT NULL,
	ref_cut int4 NOT NULL,
	CONSTRAINT tabaid_sj_cut_pk PRIMARY KEY (id_aut)
);

-- public.tabaid_sj_sketch definition
-- this tabaid clues SJs and Sketches (m:n)

CREATE TABLE public.tabaid_sj_sketch (
	id_aut serial4 NOT NULL,
	ref_sj int4 NOT NULL,
	ref_sketch int4 NOT NULL,
	CONSTRAINT tabaid_sj_sketch_pk PRIMARY KEY (id_aut)
);

-- public.tabaid_sj_polygon definition
-- this clues SJs and polygons (m:n)

CREATE TABLE public.tabaid_sj_polygon (
 	id_aut serial4 NOT NULL,
	ref_sj int4 NOT NULL,
	ref_polygon int4 NOT NULL,
	CONSTRAINT tabaid_sj_polygon_pk PRIMARY KEY (id_aut)
);


-- #################################
-- #### FUNCTIONS ###
-- there are 2 types of functions:
-- 1. check functions - checking the logical consistency of data - 'fnc_check...'
-- 2. getions - retrieving data from database (main purpose of database) - 'fnc_get...'
-- #################################


--###################
--GET FUNCTIONS
--###################

-- this fnc loops over all SJs and returns related fotos
CREATE OR REPLACE FUNCTION public.fnc_get_all_sjs_and_related_foto()
 RETURNS TABLE(sj_id integer, foto_id character varying, foto_typ character varying, foto_datum date)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tf.id_foto,
            tf.foto_typ,
            tf.datum AS foto_datum
        FROM
            public.tab_sj sj
        INNER JOIN
            public.tabaid_foto_sj tafs ON sj.id_sj = tafs.ref_sj
        INNER JOIN
            public.tab_foto tf ON tafs.ref_foto = tf.id_foto
    );
END;
$function$
;


-- 
-- this fnc loops over all SJs and returns related fotograms
CREATE OR REPLACE FUNCTION public.fnc_get_all_sjs_and_related_fotogram()
 RETURNS TABLE(sj_id integer, id_fotogram character varying, fotogram_typ character varying)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tf.id_fotogram,
            tf.fotogram_typ
        FROM
            public.tab_sj sj
        INNER JOIN
            public.tabaid_fotogram_sj tafs ON sj.id_sj = tafs.ref_sj
        INNER JOIN
            public.tab_fotogram tf ON tafs.ref_fotogram = tf.id_fotogram
    );
END;
$function$
;

--
-- this fnc loops over all SJs and returns related sketches
CREATE OR REPLACE FUNCTION public.fnc_get_all_sjs_and_related_sketch()
 RETURNS TABLE(sj_id integer, id_sketch character varying, sketch_typ character varying, datum date)
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
            public.tab_sj sj
        INNER JOIN
            public.tabaid_sj_sketch tass ON sj.id_sj = tass.ref_sj
        INNER JOIN
            public.tab_sketch ts ON tass.ref_sketch = ts.id_sketch
    );
END;
$function$
;

-- this function requires the ID of cut and lists all SJs cut by this cut
CREATE OR REPLACE FUNCTION public.fnc_get_cut_and_related_sjs(choose_cut integer)
 RETURNS TABLE(id_cut integer, id_sj integer, docu_plan boolean, docu_vertical boolean)
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
            public.tab_cut tc
        INNER JOIN
            public.tabaid_sj_cut tasc ON tc.id_cut = tasc.ref_cut
        INNER JOIN
            public.tab_sj tsj ON tasc.ref_sj = tsj.id_sj
	WHERE tc.id_cut = choose_cut
    );
END;
$function$
;

-- this function takes ID of SJ and list all cuts cutting this SJ 
CREATE OR REPLACE FUNCTION public.fnc_get_sj_and_related_cuts(choose_sj integer)
 RETURNS TABLE(sj_id integer, id_cut integer, description character varying)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tc.id_cut,
            tc.description
        FROM
            public.tab_sj sj
        INNER JOIN
            public.tabaid_sj_cut tasc ON sj.id_sj = tasc.ref_sj
        INNER JOIN
            public.tab_cut tc ON tasc.ref_cut = tc.id_cut
	WHERE sj.id_sj = choose_sj
    );
END;
$function$
;

-- this function takes SJ id and returns list of all related fotos
CREATE OR REPLACE FUNCTION public.fnc_get_sj_and_related_foto(choose_sj integer)
 RETURNS TABLE(sj_id integer, foto_id character varying, foto_typ character varying, foto_datum date)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tf.id_foto,
            tf.foto_typ,
            tf.datum AS foto_datum
        FROM
            public.tab_sj sj
        INNER JOIN
            public.tabaid_foto_sj tafs ON sj.id_sj = tafs.ref_sj
        INNER JOIN
            public.tab_foto tf ON tafs.ref_foto = tf.id_foto
	WHERE sj.id_sj = choose_sj
    );
END;
$function$
;

-- this function requires SJ id and returns list of referenced fotograms
CREATE OR REPLACE FUNCTION public.fnc_get_sj_and_related_fotogram(strat_j integer)
 RETURNS TABLE(sj_id integer, id_fotogram character varying, fotogram_typ character varying)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tf.id_fotogram,
            tf.fotogram_typ
        FROM
            public.tab_sj sj
        INNER JOIN
            public.tabaid_fotogram_sj tafs ON sj.id_sj = tafs.ref_sj
        INNER JOIN
            public.tab_fotogram tf ON tafs.ref_fotogram = tf.id_fotogram
	WHERE sj.id_sj = strat_j
    );
END;
$function$
;

-- this function use SJ is as an argument and prints all sketches associated with
CREATE OR REPLACE FUNCTION public.fnc_get_sj_and_related_sketch(strat_j integer)
 RETURNS TABLE(sj_id integer, id_sketch character varying, sketch_typ character varying, datum date)
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
            public.tab_sj sj
        INNER JOIN
            public.tabaid_sj_sketch tass ON sj.id_sj = tass.ref_sj
        INNER JOIN
            public.tab_sketch ts ON tass.ref_sketch = ts.id_sketch
	WHERE sj.id_sj = strat_j
    );
END;
$function$
;


-- similar as 1st function but this uses loop
CREATE OR REPLACE FUNCTION public.fnc_get_all_sjs_and_associated_photos()
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
            SELECT tf.id_foto || ' (' || tf.foto_typ || ')' AS photo_description
            FROM tabaid_foto_sj tafs
            JOIN tab_foto tf ON tafs.ref_foto = tf.id_foto
            WHERE tafs.ref_sj = sj_record.id_sj
        ) LOOP
            RAISE NOTICE 'For SJ %, Associated Photo: %', sj_record.id_sj, photo_info;
        END LOOP;
    END LOOP;
END;
$function$
;

-- this function lists all objects/features and prints associated sjs
CREATE OR REPLACE FUNCTION public.fnc_get_all_objects_sjs()
 RETURNS TABLE(objekt integer, typ_objektu character varying, strat_j integer, interpretace character varying)
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

-- this function takes foto ID and prints all fotograms associated
CREATE OR REPLACE FUNCTION public.fnc_get_fotograms_by_photo(fotopattern character varying)
 RETURNS TABLE(id_fotogram character varying, fotogram_typ character varying, ref_sketch character varying)
 LANGUAGE plpgsql
AS $function$
	BEGIN
		RETURN QUERY
		SELECT fg.id_fotogram, fg.fotogram_typ, fg.ref_sketch
		FROM tab_fotogram fg
		INNER JOIN tabaid_fotogram_foto tff ON fg.id_fotogram = tff.ref_fotogram
		INNER JOIN tab_foto fo ON tff.ref_foto = fo.id_foto
		WHERE fo.id_foto ILIKE fotopattern;

	END;
   $function$
;

-- this func takes fotogram ID and lists all fotos associated
CREATE OR REPLACE FUNCTION public.fnc_get_fotos_by_fotogram(fotogramm character varying)
 RETURNS TABLE(id_foto character varying, foto_typ character varying, notes character varying)
 LANGUAGE plpgsql
AS $function$
	BEGIN
		RETURN QUERY
		SELECT fo.id_foto, fo.typ, fo.notes
		FROM tab_foto fo
		INNER JOIN tabaid_fotogram_foto tff ON fo.id_foto = tff.ref_foto
		INNER JOIN tab_fotogram tf ON tff.ref_fotogram = tf.id_fotogram
		WHERE tf.id_fotogram ILIKE fotogramm;

	END;
   $function$
;

-- this function takes object/feature as argument and prints all SJs it consists of
CREATE OR REPLACE FUNCTION public.fnc_get_sj_by_object(objekt integer)
 RETURNS TABLE(strat_j_id integer, interpretace character varying)
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
CREATE OR REPLACE FUNCTION public.superfnc_get_all_sjs_and_related_docu_entities()
 RETURNS TABLE(output_text text)
 LANGUAGE plpgsql
AS $function$
DECLARE
    sj_id integer;
    record_row record;
    loop_sj_id integer; -- Separate variable for sj_id
BEGIN
    FOR sj_id IN (SELECT DISTINCT id_sj FROM public.tab_sj) LOOP
        loop_sj_id := sj_id; -- Assign sj_id to a separate variable

        -- Initialize the output text for this sj_id
        output_text := 'For SJ ID=' || loop_sj_id || ' we have following items:';

        -- Call the function to retrieve fotos
        FOR record_row IN
            SELECT * FROM public.fnc_get_all_sjs_and_related_foto() AS f WHERE f.sj_id = loop_sj_id LOOP
            output_text := output_text || CHR(10) || '- Fotos: ' || record_row.foto_id || ', ' || record_row.foto_typ || ', ' || record_row.foto_datum;
        END LOOP;

        -- Call the function to retrieve fotograms
        FOR record_row IN
            SELECT * FROM public.fnc_get_all_sjs_and_related_fotogram() AS fg WHERE fg.sj_id = loop_sj_id LOOP
            output_text := output_text || CHR(10) || '- Fotograms: ' || record_row.id_fotogram || ', ' || record_row.fotogram_typ;
        END LOOP;

        -- Call the function to retrieve sketches
        FOR record_row IN
            SELECT * FROM public.fnc_get_all_sjs_and_related_sketch() AS s WHERE s.sj_id = loop_sj_id LOOP
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
CREATE OR REPLACE FUNCTION public.superfnc_get_sj_and_related_docu_entities(target_sj_id integer)
 RETURNS TABLE(output_text text)
 LANGUAGE plpgsql
AS $function$
DECLARE
    loop_sj_id integer; -- Separate variable for sj_id
    record_row record;
BEGIN
    -- Initialize the output text for the specified sj_id
    output_text := 'For SJ ID=' || target_sj_id || ' we have following items:';

    loop_sj_id := target_sj_id; -- Assign the specified sj_id to a separate variable

    -- Call the function to retrieve fotos
    FOR record_row IN
        SELECT * FROM public.fnc_get_all_sjs_and_related_foto() AS f WHERE f.sj_id = loop_sj_id LOOP
        output_text := output_text || CHR(10) || '- Fotos: ' || record_row.foto_id || ', ' || record_row.foto_typ || ', ' || record_row.foto_datum;
    END LOOP;

    -- Call the function to retrieve fotograms
    FOR record_row IN
        SELECT * FROM public.fnc_get_all_sjs_and_related_fotogram() AS fg WHERE fg.sj_id = loop_sj_id LOOP
        output_text := output_text || CHR(10) || '- Fotograms: ' || record_row.id_fotogram || ', ' || record_row.fotogram_typ;
    END LOOP;

    -- Call the function to retrieve sketches
    FOR record_row IN
        SELECT * FROM public.fnc_get_all_sjs_and_related_sketch() AS s WHERE s.sj_id = loop_sj_id LOOP
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
CREATE OR REPLACE FUNCTION public.fnc_check_objects_have_sj()
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    object_count INTEGER;
    missing_objects TEXT;  -- String to store the IDs of missing objects
BEGIN
    -- Get the total count of objects
    SELECT COUNT(*) INTO object_count FROM public.tab_object;

    -- Collect the IDs of objects without corresponding sj_id in tab_sj
    SELECT string_agg(tab_object.id_object::TEXT, E'\n') INTO missing_objects
    FROM public.tab_object
    LEFT JOIN public.tab_sj ON tab_object.id_object = tab_sj.ref_object
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


-- this function checks if all SJs have at least one foto
CREATE OR REPLACE FUNCTION public.fnc_check_all_sjs_has_foto()
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    sj_id INT;
BEGIN
    -- Check if there are SJ records without corresponding foto records
    IF EXISTS (
        SELECT 1
        FROM tab_sj sj
        WHERE NOT EXISTS (
            SELECT 1
            FROM tabaid_foto_sj foto
            WHERE foto.ref_sj = sj.id_sj
        )
    ) THEN
        -- Print SJ records without foto records
        RAISE NOTICE 'Following SJs have no foto entry:';
        FOR sj_id IN (SELECT id_sj FROM tab_sj sj WHERE NOT EXISTS (
            SELECT 1 FROM tabaid_foto_sj foto WHERE foto.ref_sj = sj.id_sj
        )) LOOP
            RAISE NOTICE '%', sj_id;
        END LOOP;
    ELSE
        -- All SJ records have corresponding foto records
        RAISE NOTICE 'Check OK, all fotos have appropriate fotorecord';
    END IF;
END;
$function$
;

-- this function checks if SJs have or not sketches
CREATE OR REPLACE FUNCTION public.fnc_check_all_sjs_has_sketch()
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
