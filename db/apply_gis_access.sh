#!/usr/bin/env bash
# Use normal libpq connection settings (PGHOST, PGPORT, PGUSER, PGPASSFILE).
# Run as a PostgreSQL administrator, or use --terrain-only after the auth migration.
set -Eeuo pipefail

GIS_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIS_AUTH_DATABASE="${GIS_AUTH_DATABASE:-auth_db}"
GIS_TERRAIN_ONLY=0

case "${1:-}" in
    "") ;;
    --terrain-only) GIS_TERRAIN_ONLY=1 ;;
    *) printf 'Usage: %s [--terrain-only]\n' "$0" >&2; exit 2 ;;
esac

GIS_PSQL=(psql -X -w -v ON_ERROR_STOP=1)

if [[ "$GIS_TERRAIN_ONLY" == 0 ]]; then
    "${GIS_PSQL[@]}" -d "$GIS_AUTH_DATABASE" \
        -f "$GIS_SCRIPT_DIR/migrations/auth/20261004_gis_access.sql"
fi

gis_roles_ready="$("${GIS_PSQL[@]}" -Atq -d "$GIS_AUTH_DATABASE" -c \
    "SELECT count(*) = 2 FROM pg_roles WHERE rolname IN ('gis_ro', 'gis_rw');")"
if [[ "$gis_roles_ready" != t ]]; then
    printf 'GIS group roles are missing; apply the auth GIS migration first.\n' >&2
    exit 1
fi

# Match the project database naming used by web_app and include its template.
gis_database_list="$("${GIS_PSQL[@]}" -Atq -d "$GIS_AUTH_DATABASE" -c "
    SELECT datname FROM pg_database
    WHERE datallowconn AND (
        datname = 'terrain_db_template'
        OR (datname ~ '^[0-9]' AND NOT datistemplate)
    ) ORDER BY datname;
")"
if [[ -z "$gis_database_list" ]]; then
    printf 'No terrain databases found.\n'
    exit 0
fi
mapfile -t gis_databases <<<"$gis_database_list"

# Check every target before changing privileges in any database.
for gis_database in "${gis_databases[@]}"; do
    gis_schema_ready="$("${GIS_PSQL[@]}" -Atq -d "$gis_database" -c "
        SELECT count(*) = 5 FROM (
            VALUES ('public.tab_geopts'), ('public.tab_polygons'),
                   ('public.tab_section'), ('public.tab_sj'), ('public.tab_photos')
        ) AS required(name) WHERE to_regclass(name) IS NOT NULL;
    ")"
    if [[ "$gis_schema_ready" != t ]]; then
        printf 'Missing terrain tables in %s; no GIS grants applied.\n' "$gis_database" >&2
        exit 1
    fi
done

for gis_database in "${gis_databases[@]}"; do
    printf 'Applying GIS grants to %s\n' "$gis_database"
    "${GIS_PSQL[@]}" -d "$gis_database" \
        -f "$GIS_SCRIPT_DIR/migrations/20261004_gis_access.sql"
    "${GIS_PSQL[@]}" -d "$gis_database" \
        -f "$GIS_SCRIPT_DIR/migrations/20261009_gis_write_access.sql"
done
