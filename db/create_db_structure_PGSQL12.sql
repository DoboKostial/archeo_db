-- #### TABLES #####
-- public.gloss_docu_typ definition

-- Drop table

-- DROP TABLE gloss_docu_typ;

CREATE TABLE gloss_docu_typ (
	docu_typ varchar(60) NOT NULL,
	description varchar(200) NULL,
	CONSTRAINT gloss_docu_typ_pk PRIMARY KEY (docu_typ)
);


-- public.gloss_object_type definition

-- Drop table

-- DROP TABLE gloss_object_type;

CREATE TABLE gloss_object_type (
	object_typ varchar(100) NOT NULL,
	description_typ varchar(200) NULL,
	CONSTRAINT gloss_object_type_pk PRIMARY KEY (object_typ)
);


-- public.gloss_personalia definition

-- Drop table

-- DROP TABLE gloss_personalia;

CREATE TABLE gloss_personalia (
	mail varchar(80) NOT NULL,
	"name" varchar(60) NULL,
	surname varchar(100) NULL,
	CONSTRAINT gloss_personalia_pk PRIMARY KEY (mail)
);
CREATE UNIQUE INDEX gloss_personalia_mail_idx ON public.gloss_personalia USING btree (mail);


-- public.tab_cut definition

-- Drop table

-- DROP TABLE tab_cut;

CREATE TABLE tab_cut (
	id_cut int4 NOT NULL,
	description varchar(500) NULL,
	CONSTRAINT tab_cut_pk PRIMARY KEY (id_cut)
);


-- public.tab_geopts definition

-- Drop table

-- DROP TABLE tab_geopts;

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

-- Drop table

-- DROP TABLE tab_object;

CREATE TABLE tab_object (
	id_object int4 NOT NULL,
	object_typ varchar(100) NULL,
	superior_object int4 NULL DEFAULT 0,
	notes varchar(600) NULL,
	CONSTRAINT tab_object_pk PRIMARY KEY (id_object)
);


-- public.tab_polygon definition

-- Drop table

-- DROP TABLE tab_polygon;

CREATE TABLE tab_polygon (
	id_polygon int4 NOT NULL,
	polygon_typ varchar(50) NULL,
	superior_polygon int4 NULL DEFAULT 0,
	notes varchar(200) NULL,
	CONSTRAINT tab_polygon_pk PRIMARY KEY (id_polygon)
);


-- public.tab_sj_stratigraphy definition

-- Drop table

-- DROP TABLE tab_sj_stratigraphy;

CREATE TABLE tab_sj_stratigraphy (
	id_aut serial4 NOT NULL,
	ref_sj1 int4 NULL,
	relation varchar(20) NULL,
	ref_sj2 int4 NULL,
	CONSTRAINT tab_sj_stratigraphy_pk PRIMARY KEY (id_aut)
);


-- public.tab_foto definition

-- Drop table

-- DROP TABLE tab_foto;

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

-- Drop table

-- DROP TABLE tab_sj;

CREATE TABLE tab_sj (
	id_sj int4 NOT NULL,
	sj_typ varchar(20) NULL,
	description varchar(800) NULL,
	interpretation varchar(400) NULL,
	author varchar(100) NULL,
	recorded date NULL,
	docu_plan bool NULL,
	docu_vertical bool NULL,
	CONSTRAINT tab_sj_pk PRIMARY KEY (id_sj),
	CONSTRAINT tab_sj_fk FOREIGN KEY (author) REFERENCES gloss_personalia(mail)
);
CREATE UNIQUE INDEX tab_sj_id_sj_idx ON public.tab_sj USING btree (id_sj);


-- public.tab_sj_deposit definition

-- Drop table

-- DROP TABLE tab_sj_deposit;

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

-- Drop table

-- DROP TABLE tab_sj_negativ;

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

-- Drop table

-- DROP TABLE tab_sj_structure;

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

-- Drop table

-- DROP TABLE tab_sketch;

CREATE TABLE tab_sketch (
	id_sketch varchar(100) NOT NULL,
	sketch_typ varchar(80) NULL,
	author varchar(100) NULL,
	datum date NULL,
	notes varchar(800) NULL,
	CONSTRAINT tab_sketch_pk PRIMARY KEY (id_sketch),
	CONSTRAINT tab_sketch_fk FOREIGN KEY (author) REFERENCES gloss_personalia(mail)
);


-- public.tab_fotogram definition

-- Drop table

-- DROP TABLE tab_fotogram;

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

-- Drop table

-- DROP TABLE tab_sack;

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

-- Drop table

-- DROP TABLE tabaid_cut_fotogram;

CREATE TABLE tabaid_cut_fotogram (
	id_aut serial4 NOT NULL,
	ref_cut int4 NULL,
	ref_fotogram varchar(100) NULL,
	CONSTRAINT tabaid_cut_fotogram_pk PRIMARY KEY (id_aut)
);


-- public.tabaid_fotogram_foto definition

-- Drop table

-- DROP TABLE tabaid_fotogram_foto;

CREATE TABLE tabaid_fotogram_foto (
	id_aut serial4 NOT NULL,
	ref_fotogram varchar(100) NULL,
	ref_foto varchar(100) NULL,
	CONSTRAINT tabaid_fotogram_foto_pk PRIMARY KEY (id_aut)
);


-- public.tabaid_fotogram_sj definition

-- Drop table

-- DROP TABLE tabaid_fotogram_sj;

CREATE TABLE tabaid_fotogram_sj (
	id_aut serial4 NOT NULL,
	ref_fotogram varchar(100) NULL,
	ref_sj int4 NULL,
	CONSTRAINT tabaid_fotogram_sj_pk PRIMARY KEY (id_aut)
);


-- public.tabaid_cut_fotogram foreign keys

ALTER TABLE public.tabaid_cut_fotogram ADD CONSTRAINT tabaid_cut_fotogram_fk FOREIGN KEY (ref_fotogram) REFERENCES tab_fotogram(id_fotogram);
ALTER TABLE public.tabaid_cut_fotogram ADD CONSTRAINT tabaid_cut_fotogram_fk_1 FOREIGN KEY (ref_cut) REFERENCES tab_cut(id_cut);


-- public.tabaid_fotogram_foto foreign keys

ALTER TABLE public.tabaid_fotogram_foto ADD CONSTRAINT tabaid_fotogram_foto_fk FOREIGN KEY (ref_fotogram) REFERENCES tab_fotogram(id_fotogram);
ALTER TABLE public.tabaid_fotogram_foto ADD CONSTRAINT tabaid_fotogram_foto_fk_1 FOREIGN KEY (ref_foto) REFERENCES tab_foto(id_foto);


-- public.tabaid_fotogram_sj foreign keys

ALTER TABLE public.tabaid_fotogram_sj ADD CONSTRAINT tabaid_fotogram_sj_fk FOREIGN KEY (ref_fotogram) REFERENCES tab_fotogram(id_fotogram);
ALTER TABLE public.tabaid_fotogram_sj ADD CONSTRAINT tabaid_fotogram_sj_fk_1 FOREIGN KEY (ref_sj) REFERENCES tab_sj(id_sj);



-- #### FUNCTIONS ###


CREATE OR REPLACE FUNCTION public.show_fotograms_by_photo(fotopattern character varying)
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

CREATE OR REPLACE FUNCTION public.show_fotos_by_fotogram(fotogramm character varying)
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
