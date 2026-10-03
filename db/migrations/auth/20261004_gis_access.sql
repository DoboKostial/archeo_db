-- Personal GIS logins are managed from auth_db. Safe to apply repeatedly.
BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gis_ro') THEN
        CREATE ROLE gis_ro NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gis_rw') THEN
        CREATE ROLE gis_rw NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gis_role_manager') THEN
        CREATE ROLE gis_role_manager NOLOGIN CREATEROLE;
    END IF;
END $$;

ALTER ROLE gis_role_manager NOLOGIN CREATEROLE;
GRANT gis_ro, gis_rw TO gis_role_manager WITH ADMIN OPTION;
GRANT pg_signal_backend TO gis_role_manager;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.app_users WHERE octet_length(mail) > 63) THEN
        RAISE EXCEPTION 'Cannot enable GIS logins: an existing email exceeds the 63-byte PostgreSQL role-name limit';
    END IF;

    IF (SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'app_users' AND column_name = 'mail') <> 63 THEN
        DROP VIEW public.v_app_login_users;
        ALTER TABLE public.app_users ALTER COLUMN mail TYPE varchar(63);
        CREATE VIEW public.v_app_login_users AS
        SELECT mail, name, password_hash, group_role, last_login, enabled
        FROM public.app_users;
        ALTER VIEW public.v_app_login_users OWNER TO own_auth_db;
        GRANT SELECT ON public.v_app_login_users TO grp_app_auth_ro, grp_app_auth_rw, app_mobile_db;
    END IF;
END $$;

ALTER TABLE public.app_users
    ADD COLUMN IF NOT EXISTS gis_enabled boolean NOT NULL DEFAULT false;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.app_users'::regclass
                   AND conname = 'app_users_mail_bytes_check') THEN
        ALTER TABLE public.app_users
            ADD CONSTRAINT app_users_mail_bytes_check CHECK (octet_length(mail) <= 63);
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS gis_admin AUTHORIZATION gis_role_manager;
GRANT USAGE ON SCHEMA public TO gis_role_manager;
GRANT SELECT ON public.app_users TO gis_role_manager;
GRANT UPDATE ON public.app_users TO gis_role_manager;
GRANT REFERENCES (mail) ON public.app_users TO gis_role_manager;

SET ROLE gis_role_manager;

CREATE TABLE IF NOT EXISTS gis_admin.account_roles (
    user_mail varchar(63) PRIMARY KEY
        REFERENCES public.app_users(mail) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION gis_admin.sync_app_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gis_admin, pg_temp
AS $$
DECLARE
    managed boolean;
    session_pid integer;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM gis_admin.account_roles WHERE user_mail = NEW.mail
    ) INTO managed;

    IF NEW.gis_enabled AND NOT managed THEN
        -- PostgreSQL 16+ can auto-grant the creator membership in a new role.
        -- Keep that disabled when the setting exists; PostgreSQL 14 has no setting.
        IF current_setting('createrole_self_grant', true) IS NOT NULL THEN
            PERFORM set_config('createrole_self_grant', '', true);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = NEW.mail) THEN
            RAISE EXCEPTION 'PostgreSQL role already exists for %', NEW.mail;
        END IF;
        EXECUTE format('CREATE ROLE %I NOLOGIN PASSWORD NULL', NEW.mail);
        INSERT INTO gis_admin.account_roles (user_mail) VALUES (NEW.mail);
        managed := true;
    END IF;

    IF NOT managed THEN
        RETURN NEW;
    END IF;

    IF pg_has_role(NEW.mail, 'gis_ro', 'member') THEN
        EXECUTE format('REVOKE gis_ro FROM %I', NEW.mail);
    END IF;
    IF pg_has_role(NEW.mail, 'gis_rw', 'member') THEN
        EXECUTE format('REVOKE gis_rw FROM %I', NEW.mail);
    END IF;
    IF NEW.gis_enabled AND NEW.enabled THEN
        IF NEW.group_role IN ('archeolog', 'documentator') THEN
            EXECUTE format('GRANT gis_rw TO %I', NEW.mail);
        ELSIF NEW.group_role = 'analyst' THEN
            EXECUTE format('GRANT gis_ro TO %I', NEW.mail);
        ELSE
            RAISE EXCEPTION 'Unsupported GIS user role: %', NEW.group_role;
        END IF;
        EXECUTE format('ALTER ROLE %I LOGIN', NEW.mail);
    ELSE
        EXECUTE format('ALTER ROLE %I NOLOGIN PASSWORD NULL', NEW.mail);
    END IF;

    IF TG_OP = 'UPDATE' AND
       (OLD.enabled IS DISTINCT FROM NEW.enabled OR
        OLD.gis_enabled IS DISTINCT FROM NEW.gis_enabled OR
        OLD.group_role IS DISTINCT FROM NEW.group_role) THEN
        FOR session_pid IN
            SELECT pid FROM pg_catalog.pg_stat_activity
            WHERE usename = NEW.mail AND pid <> pg_catalog.pg_backend_pid()
        LOOP
            IF NOT pg_catalog.pg_terminate_backend(session_pid, 5000) THEN
                RAISE EXCEPTION 'Could not close an active GIS session for %', NEW.mail;
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gis_admin.set_password(p_mail text, p_password text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gis_admin, pg_temp
AS $$
BEGIN
    IF p_password IS NULL OR length(p_password) < 12 OR
       p_password !~ '[[:lower:]]' OR p_password !~ '[[:upper:]]' OR
       p_password !~ '[[:digit:]]' THEN
        RAISE EXCEPTION 'GIS password does not meet the password policy';
    END IF;

    PERFORM 1
    FROM public.app_users u
    JOIN gis_admin.account_roles a ON a.user_mail = u.mail
    WHERE u.mail = p_mail AND u.enabled AND u.gis_enabled
    FOR UPDATE OF u;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS access is not enabled for this user';
    END IF;

    EXECUTE format('ALTER ROLE %I PASSWORD %L', p_mail, p_password);
END;
$$;

RESET ROLE;

DROP TRIGGER IF EXISTS trg_sync_gis_user ON public.app_users;
CREATE TRIGGER trg_sync_gis_user
AFTER INSERT OR UPDATE OF enabled, gis_enabled, group_role
ON public.app_users
FOR EACH ROW EXECUTE FUNCTION gis_admin.sync_app_user();

REVOKE ALL ON SCHEMA gis_admin FROM PUBLIC;
GRANT USAGE ON SCHEMA gis_admin TO app_terrain_db;
REVOKE ALL ON FUNCTION gis_admin.sync_app_user() FROM PUBLIC;
REVOKE ALL ON FUNCTION gis_admin.set_password(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gis_admin.set_password(text, text) TO app_terrain_db;

COMMIT;
