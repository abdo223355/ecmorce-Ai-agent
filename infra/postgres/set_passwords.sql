-- Set (or rotate) the passwords of the database logins. Run as the superuser, over the container's own socket:
--   docker compose exec -T postgres psql -U postgres -d postgres \
--     -v gateway_pw="$GATEWAY_DB_PASSWORD" -v novacart_pw="$NOVACART_DB_PASSWORD" -v postgres_pw="$POSTGRES_PASSWORD" \
--     -f - < infra/postgres/set_passwords.sql
-- The values come from .env (GATEWAY_DB_PASSWORD, NOVACART_DB_PASSWORD, POSTGRES_PASSWORD). The ui_app role has its own
-- password (ui_role.sql, UI_DB_PASSWORD). After running it, recreate the services that hold the old password:
--   docker compose up -d --no-deps backend gateway
ALTER ROLE gateway  PASSWORD :'gateway_pw';
ALTER ROLE novacart PASSWORD :'novacart_pw';
ALTER ROLE postgres PASSWORD :'postgres_pw';
