"""The handoffs table (the outbox, D14): a promise made to the user, kept in the Gateway DB.

When the agent hands a turn over to a person, the row is written BEFORE the user is told "I passed it" (D14, 9 of the
design: never say "registered" before the handoff is in the Gateway DB). If the write fails the user is NOT promised
anything: they get the "could not finish" template instead, and the failure is logged.

What a row holds (D26, PRC-HOF-001 section 3, D62): the verified user id, the role, the reason code, the priority and the
summary the code built (labels and outcomes, never the user's words), plus the status of the case. The staff console
changes a case only through two database functions, claim_handoff and resolve_handoff, so the rules live in the database:
a case is claimed only from PENDING; resolving it ERASES the verified user id and the verified order ids (his decision,
D-night 110): the closed row stays for statistics (reason, priority, times) without knowing whose it was.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .agent import AgentResult, Segment
from .config import settings
from .fallback import Phones, detect_language, static_fallback
from .rag.store import plain_dsn

log = logging.getLogger("gateway.handoffs")

COULD_NOT_FINISH = 18                  # D68: what the user gets when the promise cannot be kept
STATUSES = ("PENDING", "CLAIMED", "RESOLVED")

DDL = """
CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    role                  TEXT NOT NULL,
    subject_id            TEXT,                 -- the verified user id; ERASED when the case is resolved
    reason                TEXT NOT NULL,        -- D70 reason code: SAFE, POL, BKD, CMP, SCOPE ...
    priority              TEXT,                 -- P1..P4, NULL while the owner has not answered the priority question
    ack_template          INT NOT NULL,         -- the acknowledgement the user saw (5, 6 or 8)
    block_session_data    BOOLEAN NOT NULL DEFAULT false,
    summary               JSONB NOT NULL,       -- built by code (D62): labels and outcomes, never user text
    status                TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'CLAIMED', 'RESOLVED')),
    claimed_by            TEXT,
    claimed_at            TIMESTAMPTZ,
    resolved_by           TEXT,
    resolved_at           TIMESTAMPTZ,
    note                  TEXT CHECK (char_length(note) <= 1000)
);
CREATE INDEX IF NOT EXISTS handoffs_open ON handoffs (status, priority, created_at);

CREATE OR REPLACE FUNCTION claim_handoff(p_id UUID, p_user TEXT) RETURNS BOOLEAN
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    WITH changed AS (
        UPDATE handoffs SET status = 'CLAIMED', claimed_by = p_user, claimed_at = now()
        WHERE handoff_id = p_id AND status = 'PENDING' RETURNING 1)
    SELECT EXISTS (SELECT 1 FROM changed)
$$;

CREATE OR REPLACE FUNCTION resolve_handoff(p_id UUID, p_user TEXT, p_note TEXT) RETURNS BOOLEAN
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    WITH changed AS (
        UPDATE handoffs SET status = 'RESOLVED', resolved_by = p_user, resolved_at = now(),
               note = left(p_note, 1000), subject_id = NULL,
               summary = jsonb_set(summary, '{verified_order_ids}', '[]'::jsonb)
        WHERE handoff_id = p_id AND status IN ('PENDING', 'CLAIMED') RETURNING 1)
    SELECT EXISTS (SELECT 1 FROM changed)
$$;

REVOKE ALL ON FUNCTION claim_handoff(UUID, TEXT), resolve_handoff(UUID, TEXT, TEXT) FROM PUBLIC;
"""

INSERT = """
INSERT INTO handoffs (role, subject_id, reason, priority, ack_template, block_session_data, summary)
VALUES (%(role)s, %(subject_id)s, %(reason)s, %(priority)s, %(ack_template)s, %(block_session_data)s, %(summary)s)
RETURNING handoff_id
"""


def build_row(role: str, subject_id: str, result: AgentResult) -> dict | None:
    """The row for a turn that ends in a handoff, or None when the turn has none. Pure: no database, no clock."""
    if result.handoff_reason is None:
        return None
    ack = next((s.template_id for s in result.segments if s.kind == "template" and s.template_id in (5, 6, 8)), None)
    return {"role": role, "subject_id": subject_id, "reason": result.handoff_reason, "priority": result.priority,
            "ack_template": ack or (6 if role == "worker" else 5), "block_session_data": result.block_session_data,
            "summary": result.handoff_summary or {}}


def without_promise(result: AgentResult, role: str = "customer", language: str = "ar", phones: Phones | None = None) -> AgentResult:
    """What the user gets when the handoff could not be written: no acknowledgement, no promise, no handoff fields, and the
    static text (app/fallback.py) that tells them where to go themselves. Template 18 stays as its fallback."""
    text = static_fallback(role, result.priority == "P1", language, phones or Phones())
    return replace(result, segments=[Segment(0, "text", template_id=COULD_NOT_FINISH, text=text)], handoff_reason=None,
                   priority=None, block_session_data=False, handoff_summary=None)


class HandoffStore:
    def __init__(self, dsn: str | None = None, max_size: int = 3):
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

    async def create(self, row: dict) -> str:
        """Write one case as PENDING and return its id. Raises when the database cannot take it."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(INSERT, {**row, "summary": Jsonb(row["summary"])})
            return str((await cur.fetchone())[0])


def configured_phones() -> Phones:
    return Phones(settings.cs_phone, settings.emergency_phone, settings.dispatch_phone)


async def keep_the_promise(store: HandoffStore, role: str, subject_id: str, result: AgentResult,
                           message: str = "") -> AgentResult:
    """Write the handoff of this turn (if there is one) BEFORE the answer goes out. On failure the answer loses its promise."""
    row = build_row(role, subject_id, result)
    if row is None:
        return result
    try:
        await store.create(row)
    except Exception as e:                                           # noqa: BLE001  any failure means: do not promise
        log.error(json.dumps({"event": "handoff_write_failed", "error": type(e).__name__, "reason": row["reason"]}))
        return without_promise(result, role, detect_language(message), configured_phones())
    return result
