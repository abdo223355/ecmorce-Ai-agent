#!/bin/sh
set -e
# Seed once (skips when data already exists).
# Rebuild: docker compose run --rm backend python -m novacart_backend.seed --reset
python -m novacart_backend.seed --scenarios-file /app/keys/SEED_SCENARIOS.md || true
exec gunicorn -w 2 -b 0.0.0.0:8000 "novacart_backend.app:create_app()"
