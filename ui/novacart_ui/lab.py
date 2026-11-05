"""Logic of the Lab page: a place for the owner to try every part of the stack from one screen.

Service health, the seed accounts and ready scenarios, what the backend itself says about an account (the truth to
compare the agent's answer with), and read-only looks at the Gateway DB. Everything here only READS: nothing writes to
the backend or to a table (the only writes the Lab causes are the ones /chat already makes).
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import pandas as pd
import psycopg

SEED_CUSTOMERS = tuple(f"c-{100000 + i}" for i in range(1, 11))        # backend/SEED_SCENARIOS.md: c-100001 .. c-100010
SEED_WORKERS = tuple(f"w-{2000 + i}" for i in range(1, 6))             # w-2001 .. w-2005
SEED_ACCOUNTS = SEED_CUSTOMERS + SEED_WORKERS


def role_of(username: str) -> str:
    return "worker" if username.startswith("w-") else "customer"


@dataclass(frozen=True)
class Scenario:
    title: str
    account: str
    message: str


# Each one reaches something the agent already does, on an account whose seed data makes it interesting
# (backend/SEED_SCENARIOS.md). No expected answer is promised: you compare it with the backend's truth tab.
SCENARIOS = (
    Scenario("طلب غامض: عميل عنده 5 طلبات", "c-100005", "فين طلبي ؟"),
    Scenario("حالة مرتجع: 4 مرتجعات بحالات مختلفة", "c-100006", "حالة المرتجع بتاعي إيه؟"),
    Scenario("منتجين متشابهين (Samsung Galaxy A55)", "c-100009", "فين طلب Samsung Galaxy A55؟"),
    Scenario("طلب بيانات ناقصة (متسلّم من غير تاريخ تسليم)", "c-100007", "فين طلبي ؟"),
    Scenario("سؤال سياسة (RAG)", "c-100001", "ما هي سياسة الاسترجاع للإلكترونيات؟"),
    Scenario("مشكلة أمان (P1)", "c-100003", "حد دخل على حسابي من غير علمي"),
    Scenario("عايز موظف", "c-100002", "عايز أكلّم موظف"),
    Scenario("مندوب: شحنات النهارده", "w-2001", "شحناتي النهارده"),
    Scenario("مندوب: كلّم الـ dispatch", "w-2002", "عايز أكلّم الـ dispatch"),
)


# ---------- service health ----------
@dataclass(frozen=True)
class ServiceStatus:
    name: str
    ok: bool
    detail: str
    ms: int


def _timed(name: str, check) -> ServiceStatus:
    start = time.monotonic()
    try:
        detail = check()
        return ServiceStatus(name, True, detail, round((time.monotonic() - start) * 1000))
    except Exception as e:                                          # noqa: BLE001  a down service is a result, not a crash
        return ServiceStatus(name, False, (str(e) or type(e).__name__)[:80], round((time.monotonic() - start) * 1000))


def check_http(name: str, url: str, client: httpx.Client | None = None) -> ServiceStatus:
    def go() -> str:
        r = (client or httpx.Client(timeout=3.0)).get(url)
        if r.status_code != 200:
            raise RuntimeError(f"http {r.status_code}")
        return "200"
    return _timed(name, go)


def check_postgres(dsn: str) -> ServiceStatus:
    def go() -> str:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1").fetchone()
        return "SELECT 1"
    return _timed("postgres", go)


def check_redis(url: str) -> ServiceStatus:
    def go() -> str:
        parsed = urlparse(url)
        with socket.create_connection((parsed.hostname, parsed.port or 6379), timeout=3) as s:
            s.sendall(b"PING\r\n")
            if not s.recv(16).startswith(b"+PONG"):
                raise RuntimeError("no PONG")
        return "PONG"
    return _timed("redis", go)


def check_all(backend_url: str, gateway_url: str, dsn: str, redis_url: str) -> list[ServiceStatus]:
    return [check_http("backend", f"{backend_url.rstrip('/')}/health"), check_http("gateway", f"{gateway_url.rstrip('/')}/health"),
            check_postgres(dsn), check_redis(redis_url)]


# ---------- what the backend itself says (read-only) ----------
def backend_get(client: httpx.Client, backend_url: str, token: str, path: str) -> tuple[int, object]:
    """One GET to the backend with the account's own token. Returns (status, json or text)."""
    r = client.get(f"{backend_url.rstrip('/')}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def truth_paths(role: str) -> dict[str, str]:
    """The listing endpoint of a role, and the prefix of its detail endpoint."""
    return ({"list": "/customer/orders/recent", "detail": "/customer/orders/"} if role == "customer"
            else {"list": "/worker/shipments/today", "detail": "/worker/shipments/"})


# ---------- read-only looks at the Gateway DB ----------
def policy_overview(dsn: str) -> pd.DataFrame:
    """How many chunks each policy document version holds, and whether it is the active one."""
    sql = """SELECT v.doc_id, v.version, v.status, v.indexing_status, count(c.chunk_id) AS chunks
             FROM policy_versions v LEFT JOIN policy_chunks c ON c.version_id = v.version_id
             GROUP BY v.doc_id, v.version, v.status, v.indexing_status ORDER BY v.doc_id, v.version"""
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        cur = conn.execute(sql)
        return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


def latest_events(dsn: str, limit: int = 20) -> pd.DataFrame:
    from .metrics import COLUMNS            # the same columns the dashboard reads
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM events ORDER BY ts DESC LIMIT %s", (limit,)).fetchall()
    return pd.DataFrame(rows, columns=COLUMNS)
