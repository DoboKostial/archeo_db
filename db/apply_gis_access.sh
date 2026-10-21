#!/usr/bin/env bash
# Complete GIS upgrade using normal libpq settings. No services are restarted.
set -Eeuo pipefail
GIS_SCRIPT_DIR="$(dirname -- "${BASH_SOURCE[0]}")"
GIS_AUTH_DATABASE="${GIS_AUTH_DATABASE:-auth_db}"
GIS_TERRAIN_ONLY=0
GIS_INCLUDE_LEGACY=0
GIS_CHECK=0
for gis_argument in "$@"; do
    case "$gis_argument" in
        --terrain-only) GIS_TERRAIN_ONLY=1 ;;
        --include-legacy) GIS_INCLUDE_LEGACY=1 ;;
        --check) GIS_CHECK=1 ;;
        *) printf 'Usage: %s [--terrain-only] [--include-legacy] [--check]\n' "$0" >&2; exit 2 ;;
    esac
done
gis_fail() { printf 'GIS upgrade: %s\n' "$*" >&2; exit 1; }
GIS_AUTH_FILES=()
GIS_TERRAIN_FILES=()
if [[ "$GIS_INCLUDE_LEGACY" == 1 ]]; then
    GIS_AUTH_FILES+=(migrations/auth/20260813_mobile_login_grants.sql
        migrations/auth/20260927_mobile_login_users_grant.sql)
    GIS_TERRAIN_FILES+=(migrations/20260810_optional_find_box.sql
        migrations/20260810_optional_find_count.sql
        migrations/20260813_move_excav_extent_to_su.sql
        migrations/20260815_add_geopt_codes.sql
        migrations/20260815_add_photogram_date.sql)
fi
GIS_AUTH_FILES+=(migrations/auth/20261004_gis_access.sql)
GIS_TERRAIN_FILES+=(migrations/20261004_gis_access.sql
    migrations/20261009_gis_write_access.sql
    migrations/20261009_spatial_representations.sql)
[[ "$GIS_TERRAIN_ONLY" == 0 ]] || GIS_AUTH_FILES=()

# Verify the entire file set before touching any database.
GIS_FILES=("${GIS_AUTH_FILES[@]}" "${GIS_TERRAIN_FILES[@]}")
for gis_file in "${GIS_FILES[@]}"; do
    [[ -f "$GIS_SCRIPT_DIR/$gis_file" ]] || gis_fail "Missing migration file: $GIS_SCRIPT_DIR/$gis_file"
    [[ -r "$GIS_SCRIPT_DIR/$gis_file" ]] || gis_fail "Migration is not readable: $GIS_SCRIPT_DIR/$gis_file"
done

# Stage migrations together, keeping auth and terrain filenames separate.
# Handle sudo inheriting a cwd below a private home that psql cannot reopen.
GIS_TMP_DIR="$(mktemp -d /tmp/archeodb-gis.XXXXXX)"
trap 'rm -rf -- "$GIS_TMP_DIR"' EXIT
for gis_file in "${GIS_FILES[@]}"; do
    mkdir -p -- "$GIS_TMP_DIR/$(dirname -- "$gis_file")"
    cp -- "$GIS_SCRIPT_DIR/$gis_file" "$GIS_TMP_DIR/$gis_file"
done
GIS_PSQL_CWD="$(pwd -P)"
[[ -x "$GIS_PSQL_CWD" ]] || GIS_PSQL_CWD="$GIS_TMP_DIR"
GIS_PSQL=(psql -X -w -v ON_ERROR_STOP=1)
export PGOPTIONS="${PGOPTIONS:+$PGOPTIONS }-c lock_timeout=10s"
gis_psql() { (cd -- "$GIS_PSQL_CWD" && "${GIS_PSQL[@]}" "$@") || return 1; }

gis_role_list="own_auth_db,own_terrain_db,grp_app_auth_ro,grp_app_auth_rw,grp_app_terrain_ro,grp_app_terrain_rw,app_terrain_db,app_mobile_db"
[[ "$GIS_TERRAIN_ONLY" == 0 ]] || gis_role_list="own_terrain_db,grp_app_terrain_ro,grp_app_terrain_rw,gis_ro,gis_rw"
gis_missing_roles="$(gis_psql -Atq -d "$GIS_AUTH_DATABASE" -v roles="$gis_role_list" <<'SQL'
SELECT string_agg(name, ', ' ORDER BY name)
FROM unnest(string_to_array(:'roles', ',')) required(name)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=name);
SQL
)"
[[ -z "$gis_missing_roles" ]] || gis_fail "Missing prerequisite roles: $gis_missing_roles"
if [[ "$GIS_TERRAIN_ONLY" == 0 ]]; then
    gis_psql -q -d "$GIS_AUTH_DATABASE" <<'SQL'
BEGIN READ ONLY;
DO $$ BEGIN
    IF to_regclass('public.app_users') IS NULL OR to_regclass('public.v_app_login_users') IS NULL THEN
        RAISE EXCEPTION 'Auth tables or the login view are missing';
    END IF;
    IF EXISTS (SELECT 1 FROM public.app_users WHERE octet_length(mail)>63) THEN
        RAISE EXCEPTION 'An email exceeds 63 bytes; no migration was applied and no email was shortened';
    END IF;
END $$;
COMMIT;
SQL
fi

gis_database_list="$(gis_psql -Atq -d "$GIS_AUTH_DATABASE" -c "
    SELECT datname FROM pg_database
    WHERE datallowconn AND (datname='terrain_db_template'
        OR (datname ~ '^[0-9]' AND NOT datistemplate)) ORDER BY datname;
")"
[[ -n "$gis_database_list" ]] || gis_fail 'No terrain databases or template found; no migration was applied.'
mapfile -t gis_databases <<<"$gis_database_list"
printf 'GIS upgrade targets (%s):\n' "${#gis_databases[@]}"
printf '  %s\n' "${gis_databases[@]}"

# Check every target before applying any auth or terrain migration.
for gis_database in "${gis_databases[@]}"; do
    printf 'Checking %s\n' "$gis_database"
    gis_psql -q -d "$gis_database" -v include_legacy="$GIS_INCLUDE_LEGACY" <<'SQL'
BEGIN READ ONLY;
DO $$ DECLARE missing text; blocked text; expected_srid integer; BEGIN
    SELECT string_agg(name, ', ' ORDER BY name) INTO missing FROM (VALUES
        ('public.tab_geopts'),('public.tab_polygons'),('public.tab_section'),
        ('public.tab_sj'),('public.tab_sj_negativ'),('public.tab_photos'),
        ('public.tab_finds'),('public.tab_samples'),('public.tab_photograms'),
        ('public.tab_drawings'),('public.gloss_find_type'),('public.gloss_sample_type'),
        ('public.tab_polygon_geopts_binding_top'),('public.tab_polygon_geopts_binding_bottom'),
        ('public.tab_section_geopts_binding'),('public.tabaid_photogram_geopts')
    ) required(name) WHERE to_regclass(name) IS NULL;
    IF missing IS NOT NULL THEN RAISE EXCEPTION 'Missing terrain tables: %',missing; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='postgis') THEN
        RAISE EXCEPTION 'PostGIS is missing';
    END IF;
    IF NOT has_schema_privilege('own_terrain_db','public','CREATE') THEN
        RAISE EXCEPTION 'own_terrain_db cannot create objects in public';
    END IF;
    SELECT string_agg(c.relname, ', ' ORDER BY c.relname) INTO blocked
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND (c.relname IN
        ('tab_photograms','tab_polygons','tab_entity_geometries','tab_spatial_files','tab_geometry_geopts')
        OR c.relname LIKE 'v_gis_%')
        AND NOT pg_has_role('own_terrain_db',c.relowner,'USAGE');
    IF blocked IS NOT NULL THEN
        RAISE EXCEPTION 'Objects are not owned by own_terrain_db or an inherited role: %. Ownership was not changed.',blocked;
    END IF;
    expected_srid:=Find_SRID('public','tab_geopts','pts_geom');
    IF EXISTS (SELECT 1 FROM public.tab_polygons p
        CROSS JOIN LATERAL (VALUES(p.geom_top),(p.geom_bottom)) shapes(geom)
        WHERE geom IS NOT NULL AND (NOT ST_IsValid(geom) OR ST_IsEmpty(geom)
            OR ST_SRID(geom)<>expected_srid OR ST_Zmflag(geom)<>2)) THEN
        RAISE EXCEPTION 'Existing polygon is invalid or has a different SRID/dimension; it was not modified';
    END IF;
END $$;
\if :include_legacy
-- Earlier upgrades retain original SU fields and existing photogram dates.
\else
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
        AND table_name='tab_sj' AND column_name='excav_extent')
        OR NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
        AND table_name='tab_photograms' AND column_name='datum') THEN
        RAISE EXCEPTION 'Earlier web schema upgrades are missing; rerun with --include-legacy';
    END IF;
END $$;
\endif
COMMIT;
SQL
done

printf 'Auth migrations:\n'
[[ ${#GIS_AUTH_FILES[@]} == 0 ]] || printf '  %s\n' "${GIS_AUTH_FILES[@]}"
printf 'Terrain migrations (each target):\n'
printf '  %s\n' "${GIS_TERRAIN_FILES[@]}"
if [[ "$GIS_INCLUDE_LEGACY" == 1 ]]; then
    printf 'Legacy source SU fields are retained; missing photogram dates use the migration date.\n'
fi
if [[ "$GIS_CHECK" == 1 ]]; then
    printf 'Preflight passed. No database changes were made.\n'
    exit 0
fi
for gis_file in "${GIS_AUTH_FILES[@]}"; do
    printf 'Applying %s to %s\n' "$gis_file" "$GIS_AUTH_DATABASE"
    gis_psql -d "$GIS_AUTH_DATABASE" -f "$GIS_TMP_DIR/$gis_file"
done
for gis_database in "${gis_databases[@]}"; do
    for gis_file in "${GIS_TERRAIN_FILES[@]}"; do
        printf 'Applying %s to %s\n' "$gis_file" "$gis_database"
        gis_psql -d "$gis_database" -f "$GIS_TMP_DIR/$gis_file"
    done
done
printf 'GIS upgrade complete. Each migration is atomic; the multi-database run is not.\n'
