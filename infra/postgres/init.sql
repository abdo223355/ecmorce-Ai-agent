-- One PostgreSQL container, two databases (learning setup, Phase 6 D130):
--   novacart = the "existing" NovaCart backend DB (Flask owns it)
--   gateway  = the Gateway DB (pgvector for RAG, audit, outbox ... — D12, D48)
-- Both owners start with a RANDOM password nobody knows (no default to guess). The real ones come from .env through
-- infra/postgres/set_passwords.sql, which must be run once right after the first start of a new volume.
DO $$ BEGIN
    EXECUTE format('CREATE USER novacart WITH PASSWORD %L', gen_random_uuid()::text || gen_random_uuid()::text);
    EXECUTE format('CREATE USER gateway WITH PASSWORD %L', gen_random_uuid()::text || gen_random_uuid()::text);
END $$;
CREATE DATABASE novacart OWNER novacart;
CREATE DATABASE gateway OWNER gateway;
\connect gateway
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL ON SCHEMA public TO gateway;
