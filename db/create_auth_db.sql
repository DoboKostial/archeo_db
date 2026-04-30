-- =====================================================================
-- create_auth_db.sql
-- ArcheoDB - central authentication database + shared role model
-- Run first.
-- =====================================================================

/*
Role and privilege model (tree view)
====================================

ArcheoDB
├── Owner roles (NOLOGIN)
│   ├── own_auth_db
│   │   └── owns: auth_db and objects inside auth_db
│   └── own_terrain_db
│       └── owns: terrain_db_template and all concrete terrain DBs
│
├── Privilege roles (NOLOGIN)
│   ├── grp_app_auth_ro
│   │   └── read-only access to login/auth view in auth_db
│   ├── grp_app_auth_rw
│   │   └── read-write access to auth_db user management
│   ├── grp_app_terrain_ro
│   │   └── read-only access to terrain DBs
│   └── grp_app_terrain_rw
│       └── read-write access to terrain DBs
│
└── Technical stack roles (LOGIN)
    ├── app_terrain_db
    │   ├── member of grp_app_auth_rw
    │   ├── member of grp_app_terrain_rw
    │   ├── member of own_auth_db
    │   ├── member of own_terrain_db
    │   └── CREATEDB
    │
    ├── app_desktop_db
    │   ├── member of grp_app_auth_rw
    │   ├── member of grp_app_terrain_rw
    │   ├── member of own_auth_db
    │   ├── member of own_terrain_db
    │   └── CREATEDB
    │
    ├── app_mobile_db
    │   ├── member of grp_app_auth_ro
    │   └── member of grp_app_terrain_rw
    │
    └── app_gis_db
        ├── member of grp_app_auth_ro
        └── member of grp_app_terrain_rw

Notes
=====
- Human users live only in auth_db.public.app_users
- Mobile/GIS may read auth data, but may not manage users
- Mobile/GIS do not access terrain_db_template
- grp_app_terrain_ro is prepared for future read-only stacks / analysts
*/

-- ---------------------------------------------------------------------
-- 1. Shared owner roles
-- ---------------------------------------------------------------------
CREATE ROLE own_auth_db NOLOGIN;
CREATE ROLE own_terrain_db NOLOGIN;

-- ---------------------------------------------------------------------
-- 2. Shared privilege roles
-- ---------------------------------------------------------------------
CREATE ROLE grp_app_auth_ro NOLOGIN;
CREATE ROLE grp_app_auth_rw NOLOGIN;
CREATE ROLE grp_app_terrain_ro NOLOGIN;
CREATE ROLE grp_app_terrain_rw NOLOGIN;

-- ---------------------------------------------------------------------
-- 3. Technical stack roles
--    Replace passwords before first use.
-- ---------------------------------------------------------------------
CREATE ROLE app_terrain_db LOGIN PASSWORD 'CHANGE_ME_WEB' CREATEDB;
CREATE ROLE app_desktop_db LOGIN PASSWORD 'CHANGE_ME_DESKTOP' CREATEDB;
CREATE ROLE app_mobile_db LOGIN PASSWORD 'CHANGE_ME_MOBILE';
CREATE ROLE app_gis_db LOGIN PASSWORD 'CHANGE_ME_GIS';

-- ---------------------------------------------------------------------
-- 4. Memberships
-- ---------------------------------------------------------------------
GRANT grp_app_auth_rw TO app_terrain_db;
GRANT grp_app_terrain_rw TO app_terrain_db;
GRANT own_auth_db TO app_terrain_db;
GRANT own_terrain_db TO app_terrain_db;

GRANT grp_app_auth_rw TO app_desktop_db;
GRANT grp_app_terrain_rw TO app_desktop_db;
GRANT own_auth_db TO app_desktop_db;
GRANT own_terrain_db TO app_desktop_db;

GRANT grp_app_auth_ro TO app_mobile_db;
GRANT grp_app_terrain_rw TO app_mobile_db;

GRANT grp_app_auth_ro TO app_gis_db;
GRANT grp_app_terrain_rw TO app_gis_db;

-- ---------------------------------------------------------------------
-- 5. Central auth database
-- ---------------------------------------------------------------------
CREATE DATABASE auth_db OWNER own_auth_db ENCODING 'UTF8';

-- switch to the new database
\c auth_db

ALTER DATABASE auth_db OWNER TO own_auth_db;
ALTER SCHEMA public OWNER TO own_auth_db;

-- lock down PUBLIC
REVOKE ALL ON DATABASE auth_db FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- allow connect only to auth privilege groups
GRANT CONNECT ON DATABASE auth_db TO grp_app_auth_ro;
GRANT CONNECT ON DATABASE auth_db TO grp_app_auth_rw;

-- allow schema usage only to auth privilege groups
GRANT USAGE ON SCHEMA public TO grp_app_auth_ro;
GRANT USAGE ON SCHEMA public TO grp_app_auth_rw;

-- owner role must be able to create objects in public schema
GRANT USAGE, CREATE ON SCHEMA public TO own_auth_db;

-- ---------------------------------------------------------------------
-- 6. Auth objects - create as owner role
-- ---------------------------------------------------------------------
SET ROLE own_auth_db;

-- default privileges for future auth objects created by own_auth_db
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO grp_app_auth_rw;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO grp_app_auth_rw;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT EXECUTE ON FUNCTIONS TO grp_app_auth_rw;

CREATE TABLE public.app_users (
    mail varchar(80) NOT NULL,
    name varchar(150) NOT NULL,
    password_hash varchar(250) NOT NULL,
    group_role varchar(40) NOT NULL,
    last_login date NULL,
    enabled bool DEFAULT true NOT NULL,
    CONSTRAINT app_users_pkey PRIMARY KEY (mail)
);

-- readonly stacks read through this view
CREATE VIEW public.v_app_login_users AS
SELECT
    mail,
    name,
    password_hash,
    group_role,
    last_login,
    enabled
FROM public.app_users;

CREATE TABLE public.random_citation (
    id serial4 NOT NULL,
    citation varchar(500) NULL,
    CONSTRAINT random_citation_pk PRIMARY KEY (id)
);

INSERT INTO public.random_citation (citation) VALUES
    ('"Archaeology is like a pornography - no fun without pictures." (V.F.)'),
    ('"Little did ancient people suspect that the garbage they discarded would one day be resurrected by these scientific rag-and-bone merchants." (P.B.)'),
    ('"Why are archaeologists so romantic? They''re experts in dating methods!" (N.N.)'),
    ('"The work of archaeologists is reminiscent of that of garbage collectors - they even often dress the same way." (P.B.)');

RESET ROLE;

-- ---------------------------------------------------------------------
-- 7. Grants in auth_db
-- ---------------------------------------------------------------------

-- readonly auth access for mobile / GIS / future clients
GRANT SELECT ON public.v_app_login_users TO grp_app_auth_ro;

-- full auth management for web / desktop
GRANT SELECT, INSERT, UPDATE, DELETE ON public.app_users TO grp_app_auth_rw;
GRANT SELECT ON public.v_app_login_users TO grp_app_auth_rw;
GRANT SELECT ON public.random_citation TO grp_app_auth_rw;