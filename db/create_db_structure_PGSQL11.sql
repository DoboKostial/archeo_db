----
-- SEQUENCES AND DEFINITIONS FIRST
----



-- public.gloss_personalia_id_seq definition

-- DROP SEQUENCE public.gloss_personalia_id_seq;

CREATE SEQUENCE public.gloss_personalia_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;


-- public.tabaid_photo_su_id_aut_seq definition

-- DROP SEQUENCE public.tabaid_photo_su_id_aut_seq;

CREATE SEQUENCE public.tabaid_photo_su_id_aut_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;


-- public.tabaid_su_cut_id_aut_seq definition

-- DROP SEQUENCE public.tabaid_su_cut_id_aut_seq;

CREATE SEQUENCE public.tabaid_su_cut_id_aut_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
	

-- DROP TYPE strat_relation;

CREATE TYPE strat_relation AS ENUM (
	'earlier than',
	'later than');



----
NOW TABLES
----



-- public.gloss_personalia definition

-- Drop table

-- DROP TABLE public.gloss_personalia;

CREATE TABLE public.gloss_personalia (
	id serial NOT NULL DEFAULT nextval('gloss_personalia_id_seq'::regclass),
	"name" varchar(50) NULL,
	surname varchar(100) NOT NULL,
	"position" bpchar(20) NOT NULL,
	email bpchar(50) NULL,
	CONSTRAINT gloss_personalia_pk PRIMARY KEY (id)
);


-- public.spatial_ref_sys definition

-- Drop table

-- DROP TABLE public.spatial_ref_sys;

CREATE TABLE public.spatial_ref_sys (
	srid int4 NOT NULL,
	auth_name varchar(256) NULL,
	auth_srid int4 NULL,
	srtext varchar(2048) NULL,
	proj4text varchar(2048) NULL,
	CONSTRAINT spatial_ref_sys_pkey PRIMARY KEY (srid),
	CONSTRAINT spatial_ref_sys_srid_check CHECK (((srid > 0) AND (srid <= 998999)))
);


-- public.tab_cut definition

-- Drop table

-- DROP TABLE public.tab_cut;

CREATE TABLE public.tab_cut (
	id int2 NOT NULL,
	description varchar(300) NULL,
	CONSTRAINT tab_cut_pk PRIMARY KEY (id)
);


-- public.tab_fotogram definition

-- Drop table

-- DROP TABLE public.tab_fotogram;

CREATE TABLE public.tab_fotogram (
	id_fotogram int4 NOT NULL,
	fotogram_method varchar NOT NULL,
	ref_sketch int4 NULL,
	notes varchar NULL
);


-- public.tab_object definition

-- Drop table

-- DROP TABLE public.tab_object;

CREATE TABLE public.tab_object (
	id int4 NOT NULL,
	typ varchar(150) NOT NULL,
	superior_obj int4 NULL DEFAULT 0,
	note varchar(400) NULL,
	CONSTRAINT tab_object_pk PRIMARY KEY (id)
);


-- public.tab_polygon definition

-- Drop table

-- DROP TABLE public.tab_polygon;

CREATE TABLE public.tab_polygon (
	id int2 NOT NULL,
	typ bpchar(30) NOT NULL,
	superior_pol int2 NULL DEFAULT 0,
	note varchar(300) NULL,
	CONSTRAINT tab_polygon_pk PRIMARY KEY (id)
);


-- public.tab_strat definition

-- Drop table

-- DROP TABLE public.tab_strat;

CREATE TABLE public.tab_strat (
	su_1 int4 NOT NULL,
	relation strat_relation NOT NULL,
	su_2 int4 NOT NULL
);


-- public.tab_su definition

-- Drop table

-- DROP TABLE public.tab_su;

CREATE TABLE public.tab_su (
	su_id int4 NOT NULL,
	su_type bpchar(10) NOT NULL,
	description varchar(300) NULL,
	interpretation varchar(300) NULL,
	record_author int2 NULL,
	visibility bpchar(15) NULL,
	CONSTRAINT tab_su_pk PRIMARY KEY (su_id)
);


-- public.tab_su_deposit definition

-- Drop table

-- DROP TABLE public.tab_su_deposit;

CREATE TABLE public.tab_su_deposit (
	id int4 NOT NULL,
	typ bpchar(15) NOT NULL,
	removed_by bpchar(20) NOT NULL,
	colour varchar(40) NULL,
	composition varchar(50) NULL,
	CONSTRAINT tab_su_deposit_pk PRIMARY KEY (id)
);


-- public.tab_su_negative definition

-- Drop table

-- DROP TABLE public.tab_su_negative;

CREATE TABLE public.tab_su_negative (
	id int4 NOT NULL,
	typ varchar(50) NOT NULL,
	shape varchar(40) NULL,
	length_m float8 NULL,
	width_m float8 NULL,
	depth_m float8 NULL,
	ident_cut_niveau bool NULL DEFAULT false,
	CONSTRAINT tab_su_negative_pk PRIMARY KEY (id)
);


-- public.tab_terrain_action definition

-- Drop table

-- DROP TABLE public.tab_terrain_action;

CREATE TABLE public.tab_terrain_action (
	id_action int2 NOT NULL,
	action_owner int2 NOT NULL,
	institution varchar(250) NOT NULL,
	date_start date NULL,
	date_end date NULL,
	"type" varchar(150) NULL,
	"location" point NULL
);


-- public.tab_sketch definition

-- Drop table

-- DROP TABLE public.tab_sketch;

CREATE TABLE public.tab_sketch (
	id varchar(100) NOT NULL,
	typ varchar(20) NULL,
	"date" date NULL,
	author int2 NULL,
	note varchar(250) NULL,
	CONSTRAINT tab_sketch_pk PRIMARY KEY (id),
	CONSTRAINT tab_sketch_fk FOREIGN KEY (author) REFERENCES gloss_personalia(id) ON UPDATE CASCADE
);


-- public.tab_ter_photo definition

-- Drop table

-- DROP TABLE public.tab_ter_photo;

CREATE TABLE public.tab_ter_photo (
	id varchar(100) NOT NULL,
	typ varchar(20) NULL,
	pro_fotogram bool NULL,
	"date" date NULL,
	author int2 NULL,
	note varchar(250) NULL,
	CONSTRAINT tab_ter_photo_pk PRIMARY KEY (id),
	CONSTRAINT tab_ter_photo_fk FOREIGN KEY (author) REFERENCES gloss_personalia(id) ON UPDATE CASCADE
);


-- public.tabaid_photo_su definition

-- Drop table

-- DROP TABLE public.tabaid_photo_su;

CREATE TABLE public.tabaid_photo_su (
	id_aut serial NOT NULL DEFAULT nextval('tabaid_photo_su_id_aut_seq'::regclass),
	ref_id_photo varchar NULL,
	ref_id_su int4 NULL,
	CONSTRAINT tabaid_photo_su_pkey PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_photo_su_fk FOREIGN KEY (ref_id_su) REFERENCES tab_su(su_id) ON UPDATE CASCADE ON DELETE CASCADE,
	CONSTRAINT tabaid_photo_su_fk2 FOREIGN KEY (ref_id_photo) REFERENCES tab_ter_photo(id) ON UPDATE CASCADE ON DELETE CASCADE
);


-- public.tabaid_su_cut definition

-- Drop table

-- DROP TABLE public.tabaid_su_cut;

CREATE TABLE public.tabaid_su_cut (
	id_aut serial NOT NULL DEFAULT nextval('tabaid_su_cut_id_aut_seq'::regclass),
	ref_su int4 NOT NULL,
	ref_cut int2 NOT NULL,
	CONSTRAINT tabaid_su_cut_pk PRIMARY KEY (id_aut),
	CONSTRAINT tabaid_su_cut_fk FOREIGN KEY (ref_su) REFERENCES tab_su(su_id) ON UPDATE CASCADE ON DELETE CASCADE,
	CONSTRAINT tabaid_su_cut_fk_1 FOREIGN KEY (ref_cut) REFERENCES tab_cut(id) ON UPDATE CASCADE ON DELETE CASCADE
);
