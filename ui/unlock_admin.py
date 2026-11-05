"""Unlock an admin account that was locked by wrong passwords (or by someone trying a known name). Run it with the database
OWNER, on purpose, from a terminal:

    docker compose run --rm --no-deps -v ./ui:/app -w /app \
        -e GATEWAY_DATABASE_URL="postgresql://gateway:$GATEWAY_DB_PASSWORD@postgres:5432/gateway" ui python unlock_admin.py owner

It only clears the lock and the failed-attempt counter. It never prints or changes a password.
"""
from __future__ import annotations

import os
import sys

import psycopg

from novacart_ui.auth import normalize_username


def main(raw_name: str) -> int:
    name = normalize_username(raw_name)
    with psycopg.connect(os.environ["GATEWAY_DATABASE_URL"], connect_timeout=5, autocommit=True) as conn:
        cur = conn.execute("UPDATE admin_users SET failed_attempts = 0, locked_until = NULL WHERE username = %s", (name,))
        conn.execute("INSERT INTO admin_login_events (username, success, reason) VALUES (%s, false, 'unlocked_by_owner')", (name,)) \
            if cur.rowcount else None
    print("unlocked" if cur.rowcount else "no such account")
    return 0 if cur.rowcount else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else print("usage: unlock_admin.py <username>") or 2)
