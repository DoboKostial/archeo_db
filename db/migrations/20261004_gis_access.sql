-- GIS groups may connect to every concrete terrain database. Spatial layer
-- privileges are assigned with the GIS data model, not through broad app roles.
BEGIN;

GRANT USAGE ON SCHEMA public TO gis_ro, gis_rw;
GRANT SELECT ON tab_geopts, tab_polygons, tab_section, tab_sj, tab_photos TO gis_ro, gis_rw;

DO $$
BEGIN
    IF current_database() <> 'terrain_db_template' THEN
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO gis_ro, gis_rw', current_database());
    END IF;
END $$;

COMMIT;
