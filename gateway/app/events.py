"""One row per chat request, for the admin dashboard that watches the agent (his decision: option 1, one row per request).

What a row holds: when, the role, how classify ran (code or the model) and its status and time, how reply ran and its
status and time, the whole request time, the kind and template id of every answer part, the handoff reason and
priority, and whether it was a P1. What it never holds: the user's message, the reply text, and any customer or worker
id (D108). The dashboard watches the agent, not the people.

The row is written AFTER the answer has gone out (a background task), and a failed write only logs a warning: the
user's answer never depends on this table.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .agent import AgentResult
from .config import settings
from .rag.store import plain_dsn

log = logging.getLogger("gateway.events")

DDL = """
CREATE TABLE IF NOT EXISTS events (
    id                 BIGSERIAL PRIMARY KEY,
    ts                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    role               TEXT NOT NULL,
    classify_path      TEXT,              -- 'code' (no model call) or 'llm'; NULL if classify never ran
    classify_status    TEXT,              -- ok | timeout | rate_limited | bad_output | unavailable | rejected
    classify_reason    TEXT,
    classify_latency_s REAL,
    reply_status       TEXT,              -- same values; NULL when no part needed the reply model
    reply_reason       TEXT,
    reply_latency_s    REAL,
    total_latency_s    REAL NOT NULL,
    outcomes           JSONB NOT NULL,    -- [{"kind": "template", "template_id": 18}, ...] one per answer part
    handoff_reason     TEXT,
    priority           TEXT,
    p1                 BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts DESC);
"""

INSERT = """
INSERT INTO events (role, classify_path, classify_status, classify_reason, classify_latency_s,
                    reply_status, reply_reason, reply_latency_s, total_latency_s, outcomes,
                    handoff_reason, priority, p1)
VALUES (%(role)s, %(classify_path)s, %(classify_status)s, %(classify_reason)s, %(classify_latency_s)s,
        %(reply_status)s, %(reply_reason)s, %(reply_latency_s)s, %(total_latency_s)s, %(outcomes)s,
        %(handoff_reason)s, %(priority)s, %(p1)s)
"""


def public_answer(result: AgentResult) -> dict:
    """The result as the user's screen gets it: the measurements are for the events table, not for the user."""
    answer = asdict(result)
    answer.pop("telemetry")
    answer.pop("memory", None)
    return answer


def build_event(role: str, result: AgentResult, total_latency_s: float) -> dict:
    """The row for one request, from the agent's result. Pure: no database, no clock, no text."""
    classify = result.telemetry.get("classify", {})
    reply = result.telemetry.get("reply", {})
    return {
        "role": role,
        "classify_path": classify.get("path"), "classify_status": classify.get("status"),
        "classify_reason": classify.get("reason"), "classify_latency_s": classify.get("latency_s"),
        "reply_status": reply.get("status"), "reply_reason": reply.get("reason"),
        "reply_latency_s": reply.get("latency_s"),
        "total_latency_s": round(total_latency_s, 3),
        "outcomes": [{"kind": s.kind, "template_id": s.template_id} for s in result.segments],
        "handoff_reason": result.handoff_reason, "priority": result.priority,
        "p1": result.priority == "P1" and result.handoff_reason == "SAFE",
    }


class EventStore:
    def __init__(self, dsn: str | None = None, max_size: int = 2):
        # Its own small pool, so a slow write never waits behind (or in front of) retrieval.
        self._pool = AsyncConnectionPool(
            plain_dsn(dsn or settings.gateway_database_url), min_size=1, max_size=max_size, open=False,
            kwargs={"options": "-c statement_timeout=2000", "autocommit": True})

    async def open(self) -> None:
        await self._pool.open(wait=False)

    async def close(self) -> None:
        await self._pool.close()

    async def ensure_schema(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(DDL)

    async def record(self, event: dict) -> None:
        """Write one row. Never raises: a lost row is a warning, not a failed request."""
        try:
            async with self._pool.connection() as conn:
                await conn.execute(INSERT, {**event, "outcomes": Jsonb(event["outcomes"])})
        except Exception as e:                                           # noqa: BLE001 (any failure must stay silent for the user)
            log.warning(json.dumps({"event": "write_failed", "error": type(e).__name__}))
