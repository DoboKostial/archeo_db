# Personal GIS access

Apply GIS account management and project privileges together:

```bash
sudo -u postgres bash /path/to/archeo_db/db/apply_gis_access.sh
```

The script first applies the auth migration to `auth_db`, then the terrain
migration to `terrain_db_template` and every project database whose name starts
with a digit, matching the project list in web_app. It checks all target schemas
before applying terrain grants. The migrations can be run repeatedly.

If the auth migration is already installed, use `--terrain-only`. This mode can
also run under the terrain database owner using standard libpq connection
settings (`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSFILE`). Applying only the auth
migration does not grant access to existing terrain databases.

Grant GIS access to a user in `/admin`, then set the separate GIS password in
`/profile`. Connect using the exact application email as the PostgreSQL username:

```bash
psql -h localhost -U 'user@example.com' -d '01_Project'
```

Personal accounts belong to `gis_ro` for analysts or `gis_rw` for archeologists
and documentators. Both groups currently have `CONNECT` to project databases,
schema `USAGE`, and `SELECT` on `tab_geopts`, `tab_polygons`, `tab_section`,
`tab_sj`, and `tab_photos`. Write privileges for `gis_rw` will accompany the
editable GIS layers once their geometry model is implemented.

New databases created through `/admin` receive GIS `CONNECT` grants and inherit
table privileges from the migrated template. Personal GIS accounts cannot
connect to `auth_db` or `terrain_db_template`.
