\set ON_ERROR_STOP on

-- Passwords and connection strings are deliberately not managed here. Provision
-- credentials through the deployment secret store before enabling LOGIN use.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sinofgear_owner') THEN
        CREATE ROLE sinofgear_owner LOGIN NOINHERIT BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sinofgear_app') THEN
        CREATE ROLE sinofgear_app LOGIN NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

ALTER ROLE sinofgear_owner
    LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;
ALTER ROLE sinofgear_app
    LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
DO $$
BEGIN
    IF pg_has_role('sinofgear_app', 'sinofgear_owner', 'MEMBER') THEN
        REVOKE sinofgear_owner FROM sinofgear_app;
    END IF;
END
$$;

SELECT format('ALTER DATABASE %I OWNER TO sinofgear_owner', current_database())
\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO sinofgear_owner, sinofgear_app', current_database())
\gexec

ALTER SCHEMA public OWNER TO sinofgear_owner;

DO $$
DECLARE
    object_record record;
BEGIN
    FOR object_record IN
        SELECT c.relname, c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')
        ORDER BY c.relname
    LOOP
        IF object_record.relkind = 'S' THEN
            EXECUTE format('ALTER SEQUENCE public.%I OWNER TO sinofgear_owner', object_record.relname);
        ELSE
            EXECUTE format('ALTER TABLE public.%I OWNER TO sinofgear_owner', object_record.relname);
        END IF;
    END LOOP;
END
$$;

GRANT USAGE ON SCHEMA public TO sinofgear_app;
REVOKE CREATE ON SCHEMA public FROM sinofgear_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sinofgear_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sinofgear_app;

ALTER DEFAULT PRIVILEGES FOR ROLE sinofgear_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sinofgear_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sinofgear_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO sinofgear_app;

DO $$
BEGIN
    IF to_regprocedure('public.app_current_organization_id()') IS NOT NULL THEN
        REVOKE ALL ON FUNCTION app_current_organization_id() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_current_organization_id() TO sinofgear_app;
    END IF;
END
$$;
