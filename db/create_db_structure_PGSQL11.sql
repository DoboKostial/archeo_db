-- public.tab_terrain_action definition

-- Drop table

-- DROP TABLE public.tab_terrain_action;

CREATE TABLE public.tab_terrain_action (
	id_action int2 NOT NULL,
	"owner" varchar(150) NOT NULL,
	institution varchar(250) NOT NULL,
	date_start date NULL,
	date_end date NULL
);
