"""Make the admin tables and 5 made-up accounts. Run it with the database OWNER (the gateway user), once:

    docker compose run --rm --no-deps -v ./ui:/app -w /app \\
        -e GATEWAY_DATABASE_URL="postgresql://gateway:$GATEWAY_DB_PASSWORD@postgres:5432/gateway" ui python seed_admins.py

Every new account gets a random strong password. The passwords go to ui/SEED_ADMINS.local.md (not in git) and are never
printed. Running again keeps the accounts that exist; --reset gives every account a NEW password.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

from novacart_ui.auth import DDL, generate_password, hash_password

ACCOUNTS = (("owner", "admin"), ("ops-1", "admin"), ("ops-2", "admin"), ("support-1", "support"), ("support-2", "support"))
OUT = Path(__file__).with_name("SEED_ADMINS.local.md")


def main(reset: bool) -> None:
    dsn = os.environ["GATEWAY_DATABASE_URL"]
    created: dict[str, tuple[str, str]] = {}
    with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
        conn.execute(DDL)
        for username, role in ACCOUNTS:
            exists = conn.execute("SELECT 1 FROM admin_users WHERE username = %s", (username,)).fetchone()
            if exists and not reset:
                continue
            password = generate_password()
            conn.execute("""INSERT INTO admin_users (username, password_hash, role) VALUES (%s, %s, %s)
                            ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash, role = EXCLUDED.role,
                            active = true, failed_attempts = 0, locked_until = NULL""",
                         (username, hash_password(password), role))
            created[username] = (role, password)
    if created:
        lines = ["# Admin accounts (made-up, for local testing)", "",
                 "Local file. NEVER commit it or paste it anywhere. Re-run `seed_admins.py --reset` for new passwords.", "",
                 "| username | role | password |", "|---|---|---|"]
        lines += [f"| {u} | {role} | {pw} |" for u, (role, pw) in created.items()]
        existing = OUT.read_text(encoding="utf-8") if OUT.exists() and not reset else ""
        OUT.write_text("\n".join(lines) + "\n" if reset or not existing else existing + "\n" + "\n".join(lines[4:]) + "\n",
                       encoding="utf-8")
    print(f"accounts in the table: {len(ACCOUNTS)}; new passwords written to {OUT.name}: {len(created)}")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
