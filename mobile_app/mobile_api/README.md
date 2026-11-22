# mobile_api

Standalone backend scaffold for the ArcheoDB mobile stack.

## Purpose

This service is intentionally separate from `web_app`.
It is meant to support the Android client under `../app/` without changing or depending on the released web frontend.

## Intended scope

- mobile authentication against `auth_db`
- terrain DB selection
- terrain data collection CRUD
- media upload/download for field work

## Explicit non-goals

- no admin routes
- no DB stack management
- no password change route

## Deployment idea

`mobile_api` should be deployed as its own service and connect to PostgreSQL using the limited technical role `app_mobile_db`.

The repository deployment is automated by `deploy/07_mobile_api_gunicorn.sh`.
It creates a separate virtualenv and the hardened
`archeodb-mobile-api.service`, bound to loopback on port 5050 by default.
`deploy/03_nginx.sh` publishes it under `/mobile_api/`; Nginx removes that
external prefix before forwarding requests to Flask.

The production `config.py` is local-only and must use the shared `/data`
media directories, the `app_mobile_db` role, an independent JWT secret, and
the same web password-reset secret and SMTP relay as `web_app`.

## Current implementation status

This folder currently contains the standalone Flask backend used by the Android
client. It includes:

- Flask app factory
- config template
- database connection helpers
- logger setup
- implemented mobile routes

- `GET /health`
- `POST /api/mobile/auth/login`
- `POST /api/mobile/auth/qr-login`

The QR login endpoint exchanges a short-lived, single-use code created by the
authenticated web dashboard for the same mobile JWT returned by password login.
- `POST /api/mobile/auth/forgot-password`
- `GET /api/mobile/projects`
- terrain CRUD for polygons, SUs, objects, sections, finds, and samples
- documentation CRUD for photos, sketches, drawings, and photograms
- media upload/content endpoints backed by the shared `DATA_DIR`
- terrain/documentation statistics

The mobile API is intentionally narrower than the web application. Password
changes remain part of the existing web flow; mobile only links into the web
forgot-password process.

## Negative fills

Requires terrain migration `db/migrations/20261122_add_su_fills.sql` before deployment.
SU list/detail/create/update responses include integer arrays `fill_ids` and
`negative_ids`. A negative may have zero or more deposit/structure fills; a fill
may belong to multiple different negatives. These links are independent of
objects and stratigraphic relations.

For `POST`/`PUT /api/mobile/terrain/<db>/su/<kind>[/<id>]`, send `fill_ids` for
`negatives`, or `negative_ids` for `deposits`/`structures`. The array replaces that
SU's links; `[]` clears them. Omitting the field preserves existing links, so older
Android clients can continue editing metadata safely. IDs must be positive JSON
integers of existing SUs with the appropriate type; duplicate IDs are collapsed.
Do not send a nonempty array for the opposite direction. Invalid requests roll
back the SU edit and link changes together. No Android UI change is included in
this API extension.
