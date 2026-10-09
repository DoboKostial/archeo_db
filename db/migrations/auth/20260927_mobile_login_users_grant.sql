-- Ensure the mobile API role can perform password-based login checks.
-- Run against auth_db as a PostgreSQL superuser.

BEGIN;

GRANT SELECT ON public.v_app_login_users TO grp_app_auth_ro;
GRANT SELECT ON public.v_app_login_users TO app_mobile_db;

COMMIT;
