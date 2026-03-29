-- =====================================================================
-- create_auth_db.sql
-- ArcheoDB - central authentication database + shared role model
-- Run first.
-- The purpose of this script is to create one indepedent DB and one table
-- used for authentication for app user in whole PG cluster. While the cluster
-- could have more identical databases ("projects"), the independent authentication mechanizm
-- has to be deployed
--- ArcheoDB project; author dobo@dobo.sk
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


\set ON_ERROR_STOP on

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

-- web stack = full auth + full terrain + ownership/provisioning
GRANT grp_app_auth_rw TO app_terrain_db;
GRANT grp_app_terrain_rw TO app_terrain_db;
GRANT own_auth_db TO app_terrain_db;
GRANT own_terrain_db TO app_terrain_db;

-- desktop stack = same as web
GRANT grp_app_auth_rw TO app_desktop_db;
GRANT grp_app_terrain_rw TO app_desktop_db;
GRANT own_auth_db TO app_desktop_db;
GRANT own_terrain_db TO app_desktop_db;

-- mobile stack = auth readonly + terrain readwrite
GRANT grp_app_auth_ro TO app_mobile_db;
GRANT grp_app_terrain_rw TO app_mobile_db;

-- GIS stack = auth readonly + terrain readwrite
GRANT grp_app_auth_ro TO app_gis_db;
GRANT grp_app_terrain_rw TO app_gis_db;

-- ---------------------------------------------------------------------
-- 5. Central auth database
-- ---------------------------------------------------------------------
CREATE DATABASE auth_db OWNER own_auth_db ENCODING 'UTF8';

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

-- ---------------------------------------------------------------------
-- 6. Auth objects - create as owner role
-- ---------------------------------------------------------------------
SET ROLE own_auth_db;

CREATE TABLE public.app_users (
    mail varchar(80) NOT NULL,
    name varchar(150) NOT NULL,
    password_hash varchar(250) NOT NULL,
    group_role varchar(40) NOT NULL,
    last_login date NULL,
    enabled bool DEFAULT true NOT NULL,
    CONSTRAINT app_users_pkey PRIMARY KEY (mail)
);

-- readonly stacks will read through view, not directly from table grants
CREATE VIEW public.v_app_login_users AS
SELECT
    mail,
    name,
    password_hash,
    group_role,
    last_login,
    enabled
FROM public.app_users;

RESET ROLE;

-- ---------------------------------------------------------------------
-- 7. Grants in auth_db
-- ---------------------------------------------------------------------

-- mobile/GIS/etc. readonly auth access
GRANT SELECT ON TABLE public.v_app_login_users TO grp_app_auth_ro;

-- web/desktop full auth management
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.app_users TO grp_app_auth_rw;
GRANT SELECT ON TABLE public.v_app_login_users TO grp_app_auth_rw;

-- default privileges for future auth objects created by owner role
ALTER DEFAULT PRIVILEGES FOR ROLE own_auth_db IN SCHEMA public
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO grp_app_auth_rw;

ALTER DEFAULT PRIVILEGES FOR ROLE own_auth_db IN SCHEMA public
GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO grp_app_auth_rw;

ALTER DEFAULT PRIVILEGES FOR ROLE own_auth_db IN SCHEMA public
GRANT EXECUTE ON FUNCTIONS TO grp_app_auth_rw;

