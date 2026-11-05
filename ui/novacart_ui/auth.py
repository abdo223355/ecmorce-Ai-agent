"""Sign-in of the owner's pages (Admin, Lab): one account per person, kept in the Gateway DB.

- Passwords are stored as scrypt hashes with a salt per account, never as text.
- 5 wrong passwords lock the account for 15 minutes (the lock lives in the database, so a new browser tab does not reset it).
- Every attempt is written to `admin_login_events` (name, time, result; never the password).
- The answer to a failed sign-in is always the same, so the screen does not reveal which names exist; an unknown name
  costs the same time as a known one.
- The screen's database role (ui_app) can read, and can change only the three counters of an account: it cannot change a
  password, a role or the active flag (infra/postgres/ui_role.sql).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1        # about 16 MB and 50 ms per check: slow for a guesser, fine for a person
MAX_FAILURES = 5
LOCK_MINUTES = 15
IDLE_MINUTES = 30
ROLES = ("admin", "support")
USERNAME = re.compile(r"^[a-z0-9_-]{3,32}$")

DDL = """
CREATE TABLE IF NOT EXISTS admin_users (
    username        TEXT PRIMARY KEY CHECK (username ~ '^[a-z0-9_-]{3,32}$'),
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('admin', 'support')),
    active          BOOLEAN NOT NULL DEFAULT true,
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS admin_login_events (
    id       BIGSERIAL PRIMARY KEY,
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    username TEXT NOT NULL,                 -- as typed, cut to 64 characters; never a password
    success  BOOLEAN NOT NULL,
    reason   TEXT NOT NULL                  -- ok | bad_password | unknown_user | inactive | locked | role_denied
);
CREATE INDEX IF NOT EXISTS admin_login_events_ts ON admin_login_events (ts DESC);
"""


# ---------- passwords ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """True only for the right password. A malformed stored value is simply False, never an error."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(digest) // 2)
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


def generate_password() -> str:
    return secrets.token_urlsafe(18)


DUMMY_HASH = hash_password("not-a-real-password")   # spent on unknown names so they take as long as real ones


def idle_expired(seen: float, now: float, minutes: int = IDLE_MINUTES) -> bool:
    """True when the person has done nothing for more than `minutes` (times are seconds, as time.time() gives)."""
    return now - seen > minutes * 60


def normalize_username(raw: str) -> str:
    return raw.strip().lower()[:64]


# ---------- the decision (pure) ----------
@dataclass(frozen=True)
class AdminUser:
    username: str
    role: str
    active: bool
    failed_attempts: int
    locked_until: datetime | None
    password_hash: str


@dataclass(frozen=True)
class LoginOutcome:
    ok: bool
    reason: str                 # ok | bad_password | unknown_user | inactive | locked
    user: AdminUser | None = None


def evaluate(user: AdminUser | None, password: str, now: datetime) -> LoginOutcome:
    """One scrypt check on every path (the time says nothing), then the decision. A locked account is refused even with
    the right password."""
    verified = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if user is None:
        return LoginOutcome(False, "unknown_user")
    if not user.active:
        return LoginOutcome(False, "inactive")
    if user.locked_until is not None and user.locked_until > now:
        return LoginOutcome(False, "locked")
    return LoginOutcome(True, "ok", user) if verified else LoginOutcome(False, "bad_password")


# ---------- the database ----------
class AuthUnavailable(Exception):
    """The database did not answer: nobody is let in."""


class AdminStore:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn, connect_timeout=5, autocommit=True)

    def get_user(self, username: str) -> AdminUser | None:
        with self._connect() as conn:
            row = conn.execute("SELECT username, role, active, failed_attempts, locked_until, password_hash "
                               "FROM admin_users WHERE username = %s", (username,)).fetchone()
        return AdminUser(*row) if row else None

    def log_event(self, username: str, success: bool, reason: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO admin_login_events (username, success, reason) VALUES (%s, %s, %s)",
                         (username[:64], success, reason))

    def login(self, raw_username: str, password: str) -> LoginOutcome:
        """The whole sign-in: look the account up, decide, update the counters and write the event."""
        username = normalize_username(raw_username)
        try:
            user = self.get_user(username) if USERNAME.match(username) else None
            outcome = evaluate(user, password, datetime.now(timezone.utc))
            with self._connect() as conn:
                if outcome.ok:
                    conn.execute("UPDATE admin_users SET failed_attempts = 0, locked_until = NULL, last_login_at = now() "
                                 "WHERE username = %s", (username,))
                elif user is not None and outcome.reason == "bad_password":
                    conn.execute("UPDATE admin_users SET failed_attempts = failed_attempts + 1, "
                                 "locked_until = CASE WHEN failed_attempts + 1 >= %s THEN now() + make_interval(mins => %s) "
                                 "ELSE locked_until END WHERE username = %s", (MAX_FAILURES, LOCK_MINUTES, username))
            self.log_event(username, outcome.ok, outcome.reason)
            return outcome
        except psycopg.Error:
            raise AuthUnavailable() from None
