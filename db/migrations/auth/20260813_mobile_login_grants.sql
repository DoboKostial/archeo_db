-- One-time grants used to exchange an authenticated web session for a
-- short-lived mobile login. Run against auth_db as a PostgreSQL superuser.

BEGIN;

SET ROLE own_auth_db;

CREATE TABLE IF NOT EXISTS public.mobile_login_grants (
    token_hash char(64) NOT NULL,
    user_mail varchar(80) NOT NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamptz NOT NULL,
    used_at timestamptz NULL,
    CONSTRAINT mobile_login_grants_pkey PRIMARY KEY (token_hash),
    CONSTRAINT mobile_login_grants_user_fkey
        FOREIGN KEY (user_mail)
        REFERENCES public.app_users(mail)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT mobile_login_grants_token_hash_check
        CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT mobile_login_grants_expiry_check
        CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS mobile_login_grants_expires_at_idx
    ON public.mobile_login_grants (expires_at);

CREATE OR REPLACE FUNCTION public.consume_mobile_login_grant(p_token_hash text)
RETURNS TABLE (
    user_mail varchar(80),
    user_name varchar(150),
    user_role varchar(40),
    user_enabled boolean
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    WITH consumed AS (
        UPDATE public.mobile_login_grants
        SET used_at = CURRENT_TIMESTAMP
        WHERE token_hash = p_token_hash
          AND used_at IS NULL
          AND expires_at > CURRENT_TIMESTAMP
        RETURNING user_mail
    )
    SELECT
        users.mail,
        users.name,
        users.group_role,
        users.enabled
    FROM consumed
    JOIN public.app_users AS users
      ON users.mail = consumed.user_mail;
$$;

RESET ROLE;

GRANT SELECT, INSERT, DELETE ON public.mobile_login_grants TO grp_app_auth_rw;
REVOKE ALL ON FUNCTION public.consume_mobile_login_grant(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.consume_mobile_login_grant(text) TO app_mobile_db;

COMMIT;
