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


-- public.tab_su definition

-- Drop table

-- DROP TABLE public.tab_su;

CREATE TABLE public.tab_su (
	su_id int4 NOT NULL,
	su_type bpchar(1) NOT NULL,
	description varchar(300) NULL,
	interpretation varchar(300) NULL,
	record_author bpchar(30) NULL
);


-- public.tab_terrain_action definition

-- Drop table

-- DROP TABLE public.tab_terrain_action;

CREATE TABLE public.tab_terrain_action (
	id_action int2 NOT NULL,
	action_owner varchar(150) NOT NULL,
	institution varchar(250) NOT NULL,
	date_start date NULL,
	date_end date NULL,
	"type" varchar(150) NULL,
	"location" point NULL
);
