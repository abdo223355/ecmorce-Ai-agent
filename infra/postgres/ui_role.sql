-- The database role of the user-facing screens (the `ui` service): least privilege.
-- It can READ what the dashboard and the Lab show, write sign-in events, and change only the three counters of an
-- account. It cannot change a password, a role or the active flag, and it cannot touch the RAG tables' data.
-- Run it as the superuser, AFTER the tables exist (the gateway makes `events` and `handoffs`; ui/seed_admins.py makes the
-- rest). It is safe to run again whenever a grant is added:
--   docker compose exec -T postgres psql -U postgres -d gateway -v ui_password="$UI_DB_PASSWORD" -f - < infra/postgres/ui_role.sql
-- The password is UI_DB_PASSWORD from .env (no default: the ui service refuses to start without it):
--   -v ui_password="$(grep ^UI_DB_PASSWORD= .env | cut -d= -f2-)"
SELECT 'CREATE ROLE ui_app LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ui_app') \gexec
ALTER ROLE ui_app PASSWORD :'ui_password';
GRANT CONNECT ON DATABASE gateway TO ui_app;
GRANT USAGE ON SCHEMA public TO ui_app;
GRANT SELECT ON events, policy_versions, policy_chunks TO ui_app;
GRANT SELECT ON admin_users TO ui_app;
GRANT UPDATE (failed_attempts, locked_until, last_login_at) ON admin_users TO ui_app;
GRANT SELECT, INSERT ON admin_login_events TO ui_app;
GRANT USAGE ON SEQUENCE admin_login_events_id_seq TO ui_app;
-- the staff console reads the cases and changes them ONLY through these two functions (no UPDATE on the table itself)
GRANT SELECT ON handoffs TO ui_app;
GRANT EXECUTE ON FUNCTION claim_handoff(UUID, TEXT), resolve_handoff(UUID, TEXT, TEXT) TO ui_app;
