# Updating existing databases

Changing `create_auth_db.sql` or `create_db_template.sql` does not update existing
databases. Every database change must include a migration here as well as the
corresponding provisioning change. Include permissions, functions, and triggers,
not just tables and columns. Keep migrations in Git with the feature that needs
them and document their order and any data conversion.

Apply terrain migrations to both `terrain_db_template` and every existing
project. Updating the template only affects projects created afterwards.
The project list used by web_app consists of databases whose names start with
a digit; connection labels in QGIS may have different names.

## GIS changes on feature/gis

| Order | Target | Migration | Changes |
| --- | --- | --- | --- |
| 1 | `auth_db` and cluster roles | [auth/20261004_gis_access.sql](auth/20261004_gis_access.sql) | `gis_ro`, `gis_rw`, restricted role manager, email limit of 63 bytes, `gis_enabled`, managed-account registry, lifecycle trigger, GIS password function and permissions |
| 2 | Template and each project | [20261004_gis_access.sql](20261004_gis_access.sql) | Schema usage, spatial table reads, project database `CONNECT` |
| 3 | Template and each project | [20261009_gis_write_access.sql](20261009_gis_write_access.sql) | `INSERT`, `UPDATE`, `DELETE` on the five exposed tables for `gis_rw` |

From the repository root, run all three in order:

```bash
sudo -u postgres bash db/apply_gis_access.sh
```

The helper discovers existing projects and includes the template. It uses
`ON_ERROR_STOP` and checks that the five required terrain tables exist in every
target before changing terrain grants. It applies only the GIS migrations,
not the earlier web/mobile migrations listed below.

If the auth migration is already installed, the terrain database owner can run
`bash db/apply_gis_access.sh --terrain-only` with normal libpq connection settings.
Set `GIS_AUTH_DATABASE` if the authentication database has a different name.

These GIS migrations can be reapplied. The auth migration rejects existing
emails longer than 63 bytes without truncating them. Existing application users
start with GIS access disabled. Application password hashes are preserved;
GIS passwords are separate and are set through `/profile`. Reapplying the
migrations preserves already configured GIS accounts and their passwords.
Each migration has its own transaction; the whole multi-database run is not
atomic. After a failed run, fix the reported problem and rerun the helper.

The `/admin` and `/profile` buttons are application changes and use this database
support. The web application's new-project path grants GIS `CONNECT` explicitly;
other provisioning tools must also grant it when creating a project.
`pg_hba.conf`, listening addresses, and TLS are PostgreSQL server configuration
and are managed separately from SQL migrations. See [GIS access](../GIS_ACCESS.md)
for the current table scope and geometry limitations.

## Earlier web/mobile migrations retained after the master merge

Apply any missing migrations in the following order. They are separate from
the GIS feature; in particular, the SU error reported in this discussion is
handled by `20260813_move_excav_extent_to_su.sql`.

| Target | Migration | Changes |
| --- | --- | --- |
| Template and each project | [20260810_optional_find_box.sql](20260810_optional_find_box.sql) | Optional find box; positive value when supplied |
| Template and each project | [20260810_optional_find_count.sql](20260810_optional_find_count.sql) | Optional find count; positive value when supplied |
| Template and each project | [20260813_move_excav_extent_to_su.sql](20260813_move_excav_extent_to_su.sql) | Move excavation extent from negative SU details to common SU attributes and convert legacy categories to percentages |
| `auth_db` | [auth/20260813_mobile_login_grants.sql](auth/20260813_mobile_login_grants.sql) | Single-use mobile login grants, consumption function and permissions |
| Template and each project | [20260815_add_geopt_codes.sql](20260815_add_geopt_codes.sql) | Add `FI` and `PR` geodetic codes |
| Template and each project | [20260815_add_photogram_date.sql](20260815_add_photogram_date.sql) | Required photogram date and index |
| `auth_db` | [auth/20260927_mobile_login_users_grant.sql](auth/20260927_mobile_login_users_grant.sql) | Mobile password login access to the login view |

Run individual files with error checking, using the actual database name:

```bash
sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d auth_db \
  -f db/migrations/auth/20260813_mobile_login_grants.sql
sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d terrain_db_template \
  -f db/migrations/20260813_move_excav_extent_to_su.sql
sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d '01_Project' \
  -f db/migrations/20260813_move_excav_extent_to_su.sql
```

Repeat terrain commands for every existing project. The photogram migration
fills missing dates with its execution date, which is a fallback rather than a
recovered capture date. The SU migration converts `whole`, `more_than_50`,
`around_50`, and `less_than_50` to 100, 75, 50, and 25 respectively, keeps existing
numeric percentages, and removes the old column after conversion. Back up the
affected data before running these conversions.

New spatial geometry models discussed in this thread have not been implemented
yet. Their future template changes must ship with migrations for existing
databases using the same process.
