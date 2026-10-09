-- Allow personal GIS editors to change the existing exposed terrain entities.
-- Keep analysts read-only and avoid granting schema creation or owner privileges.
BEGIN;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    public.tab_geopts, public.tab_polygons, public.tab_section,
    public.tab_sj, public.tab_photos
TO gis_rw;

COMMIT;
