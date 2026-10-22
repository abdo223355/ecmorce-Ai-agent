-- One PostgreSQL container, two databases (learning setup, Phase 6 D130):
--   novacart = the "existing" NovaCart backend DB (Flask owns it)
--   gateway  = the Gateway DB (pgvector for RAG, audit, outbox ... — D12, D48)
CREATE USER novacart WITH PASSWORD 'novacart';
CREATE DATABASE novacart OWNER novacart;
CREATE USER gateway WITH PASSWORD 'gateway';
CREATE DATABASE gateway OWNER gateway;
\connect gateway
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL ON SCHEMA public TO gateway;
