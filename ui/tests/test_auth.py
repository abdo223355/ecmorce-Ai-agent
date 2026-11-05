"""Sign-in of the owner's pages: the hashes, the decision, and (against the real database) the lock and the log.

The database tests need the Gateway PostgreSQL with the admin tables and an OWNER connection in GATEWAY_DATABASE_URL;
they use a throwaway account and remove it, and they skip if the database is not reachable.
"""
import os
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from novacart_ui.auth import (DDL, LOCK_MINUTES, MAX_FAILURES, AdminStore, AdminUser, evaluate, generate_password,
                              hash_password, normalize_username, verify_password)

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def user(**kw) -> AdminUser:
    base = dict(username="owner", role="admin", active=True, failed_attempts=0, locked_until=None,
                password_hash=hash_password("right-password"))
    return AdminUser(**{**base, **kw})


# ---------- passwords ----------
def test_a_password_is_stored_as_a_salted_scrypt_hash_never_as_text():
    h = hash_password("secret-one")
    assert h.startswith("scrypt$") and "secret-one" not in h
    assert hash_password("secret-one") != h                         # a new salt every time


def test_only_the_right_password_verifies():
    h = hash_password("secret-one")
    assert verify_password("secret-one", h) and not verify_password("secret-two", h) and not verify_password("", h)


def test_a_broken_stored_value_is_a_refusal_not_an_error():
    for bad in ("", "scrypt$", "plain-text", "md5$1$2$3$ab$cd", "scrypt$16384$8$1$zz$zz"):
        assert verify_password("x", bad) is False


def test_generated_passwords_are_long_and_different():
    a, b = generate_password(), generate_password()
    assert a != b and len(a) >= 24


def test_names_are_trimmed_lowercased_and_cut():
    assert normalize_username("  OWNER ") == "owner" and len(normalize_username("a" * 200)) == 64


# ---------- the decision ----------
def test_the_right_password_of_an_active_unlocked_account_gets_in():
    out = evaluate(user(), "right-password", NOW)
    assert out.ok and out.reason == "ok" and out.user.username == "owner"


def test_every_refusal_has_its_own_reason_and_no_user():
    assert evaluate(user(), "wrong", NOW).reason == "bad_password"
    assert evaluate(None, "right-password", NOW).reason == "unknown_user"
    assert evaluate(user(active=False), "right-password", NOW).reason == "inactive"
    for out in (evaluate(user(), "wrong", NOW), evaluate(None, "x", NOW)):
        assert out.ok is False and out.user is None


def test_a_locked_account_is_refused_even_with_the_right_password_until_the_lock_ends():
    assert evaluate(user(locked_until=NOW + timedelta(minutes=1)), "right-password", NOW).reason == "locked"
    assert evaluate(user(locked_until=NOW - timedelta(seconds=1)), "right-password", NOW).ok is True


# ---------- against the database ----------
NAME = "pytest-admin"


@pytest.fixture
def store():
    dsn = os.getenv("GATEWAY_DATABASE_URL", "postgresql://gateway:gateway@127.0.0.1:5433/gateway")
    try:
        conn = psycopg.connect(dsn, connect_timeout=3, autocommit=True)
    except psycopg.Error:
        pytest.skip("gateway database not reachable")
    conn.execute(DDL)
    conn.execute("DELETE FROM admin_users WHERE username = %s", (NAME,))
    conn.execute("INSERT INTO admin_users (username, password_hash, role) VALUES (%s, %s, 'support')", (NAME, hash_password("db-password")))
    yield AdminStore(dsn), conn
    conn.execute("DELETE FROM admin_users WHERE username = %s", (NAME,))
    conn.execute("DELETE FROM admin_login_events WHERE username LIKE 'pytest%%' OR username LIKE '%%drop table%%'")
    conn.close()


def events(conn, name=NAME):
    return conn.execute("SELECT success, reason FROM admin_login_events WHERE username = %s ORDER BY id", (name,)).fetchall()


def test_login_succeeds_resets_the_counters_and_is_logged(store):
    s, conn = store
    conn.execute("UPDATE admin_users SET failed_attempts = 3 WHERE username = %s", (NAME,))
    out = s.login(f"  {NAME.upper()} ", "db-password")
    assert out.ok and out.user.role == "support"
    assert conn.execute("SELECT failed_attempts, locked_until, last_login_at IS NOT NULL FROM admin_users WHERE username = %s",
                        (NAME,)).fetchone() == (0, None, True)
    assert events(conn) == [(True, "ok")]


def test_five_wrong_passwords_lock_the_account_and_the_right_one_is_then_refused(store):
    s, conn = store
    for _ in range(MAX_FAILURES):
        assert s.login(NAME, "wrong").reason == "bad_password"
    locked_until = conn.execute("SELECT locked_until FROM admin_users WHERE username = %s", (NAME,)).fetchone()[0]
    assert locked_until is not None and timedelta(minutes=LOCK_MINUTES - 1) < locked_until - datetime.now(timezone.utc) <= timedelta(minutes=LOCK_MINUTES)
    assert s.login(NAME, "db-password").reason == "locked"
    assert [r for _, r in events(conn)] == ["bad_password"] * MAX_FAILURES + ["locked"]


def test_an_unknown_name_is_logged_and_looks_like_any_other_failure(store):
    s, conn = store
    out = s.login("pytest-nobody", "whatever")
    assert out.ok is False and out.reason == "unknown_user" and events(conn, "pytest-nobody") == [(False, "unknown_user")]


def test_sql_in_the_name_is_just_a_name(store):
    s, conn = store
    evil = "x'; drop table admin_users; --"
    assert s.login(evil, "x").ok is False
    assert conn.execute("SELECT count(*) FROM admin_users WHERE username = %s", (NAME,)).fetchone()[0] == 1   # the table is alive
    assert events(conn, evil[:64]) == [(False, "unknown_user")]


def test_no_password_reaches_the_log_or_the_table_as_text(store):
    s, conn = store
    s.login(NAME, "db-password")
    s.login(NAME, "a-wrong-password-123")
    blob = str(conn.execute("SELECT * FROM admin_login_events WHERE username = %s", (NAME,)).fetchall()) + \
           str(conn.execute("SELECT * FROM admin_users WHERE username = %s", (NAME,)).fetchall())
    assert "db-password" not in blob and "a-wrong-password-123" not in blob


def test_an_inactive_account_cannot_sign_in(store):
    s, conn = store
    conn.execute("UPDATE admin_users SET active = false WHERE username = %s", (NAME,))
    assert s.login(NAME, "db-password").reason == "inactive"


# ---------- idle end and unlock ----------
from novacart_ui.auth import IDLE_MINUTES, idle_expired


def test_a_session_ends_only_after_the_idle_minutes():
    assert idle_expired(seen=1000.0, now=1000.0 + IDLE_MINUTES * 60 + 1) is True
    assert idle_expired(seen=1000.0, now=1000.0 + IDLE_MINUTES * 60) is False
    assert idle_expired(seen=1000.0, now=1000.0) is False


def test_the_owner_can_unlock_a_locked_account_and_it_is_logged(store, monkeypatch):
    s, conn = store
    for _ in range(MAX_FAILURES):
        s.login(NAME, "wrong")
    assert s.login(NAME, "db-password").reason == "locked"
    import unlock_admin
    monkeypatch.setenv("GATEWAY_DATABASE_URL", os.getenv("GATEWAY_DATABASE_URL", "postgresql://gateway:gateway@127.0.0.1:5433/gateway"))
    assert unlock_admin.main(NAME) == 0 and unlock_admin.main("pytest-nobody") == 1
    assert s.login(NAME, "db-password").ok is True
    assert (False, "unlocked_by_owner") in events(conn)
