-- The purpose of this script is to create one indepedent DB and one table
-- used for authentication for app user in whole PG cluster. While the cluster
-- could have more identical databases ("projects"), the independent authentication mechanizm
-- has to be deployed

CREATE DATABASE auth_db OWNER app_terrain_db ENCODING 'UTF8';

-- Connect to the template database to configure it
\c auth_db;

-- default privileges for users
ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO app_terrain_db;
ALTER DEFAULT PRIVILEGES GRANT ALL ON SEQUENCES TO app_terrain_db;
ALTER DEFAULT PRIVILEGES GRANT ALL ON FUNCTIONS TO app_terrain_db;
ALTER DEFAULT PRIVILEGES GRANT ALL ON TYPES TO app_terrain_db;
ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO app_terrain_db;

SET ROLE app_terrain_db;

CREATE TABLE app_users (
    mail VARCHAR(80) NOT NULL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    password_hash VARCHAR(250) NOT NULL,
    group_role VARCHAR(40) NOT NULL,
    last_login DATE
);

RESET ROLE;

