"""The handoffs table: the row of a turn, the promise written before the answer, and the case rules kept in the database.

Unit tests need nothing. The integration tests need the Gateway PostgreSQL (the OWNER login of the gateway) and skip if it
is down; they use rows with the role 'pytest' and remove them.
"""
import asyncio

import pytest

from app.agent import AgentResult, Segment
from app.handoffs import COULD_NOT_FINISH, HandoffStore, build_row, keep_the_promise, without_promise

SUMMARY = {"parts": [{"part_index": 0, "intent": "C6", "label": "Talk to a human", "outcome": "handed_over"}],
           "error_codes": [], "policies": [], "verified_order_ids": ["NC-100007"], "order_number_mentioned_unverified": False}


def handed(reason="PENDING_OWNER", priority="P3", ack=5, **kw) -> AgentResult:
    return AgentResult(segments=[Segment(0, "template", template_id=ack)], handoff_reason=reason, priority=priority,
                       handoff_summary=SUMMARY, telemetry={"classify": {"path": "llm", "status": "ok"}}, **kw)


# ---------- the row (pure) ----------
def test_a_turn_without_a_handoff_makes_no_row():
    assert build_row("customer", "C-100003", AgentResult(segments=[Segment(0, "template", template_id=1)])) is None


def test_the_row_carries_the_verified_id_the_reason_the_priority_and_the_summary():
    row = build_row("customer", "C-100003", handed("CMP", "P2"))
    assert row == {"role": "customer", "subject_id": "C-100003", "reason": "CMP", "priority": "P2", "ack_template": 5,
                   "block_session_data": False, "summary": SUMMARY}


def test_the_acknowledgement_is_the_one_the_user_saw_and_p1_blocks_session_data():
    row = build_row("customer", "C-100003", handed("SAFE", "P1", ack=8, block_session_data=True))
    assert row["ack_template"] == 8 and row["block_session_data"] is True and row["priority"] == "P1"
    assert build_row("worker", "W-2001", AgentResult(segments=[], handoff_reason="POL", handoff_summary={}))["ack_template"] == 6


def test_the_row_holds_no_user_text_only_what_the_code_built():
    row = build_row("customer", "C-100003", AgentResult(segments=[Segment(0, "text", text="MY WORDS NC-1", template_id=5)],
                                                          handoff_reason="POL", handoff_summary=SUMMARY))
    assert "MY WORDS" not in str(row) and set(row) == {"role", "subject_id", "reason", "priority", "ack_template",
                                                       "block_session_data", "summary"}


def test_without_a_promise_the_user_gets_the_could_not_finish_template_and_no_handoff_fields():
    out = without_promise(handed("SAFE", "P1", ack=8, block_session_data=True))
    assert [(s.kind, s.template_id) for s in out.segments] == [("text", COULD_NOT_FINISH)]      # the static text; 18 is its fallback
    assert out.segments[0].text and "الطوارئ" in out.segments[0].text                            # a P1 gets the emergency line
    assert (out.handoff_reason, out.priority, out.block_session_data, out.handoff_summary) == (None, None, False, None)
    assert out.telemetry == {"classify": {"path": "llm", "status": "ok"}}          # what was measured stays


# ---------- the promise (a fake store) ----------
class FakeStore:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    async def create(self, row):
        if self.fail:
            raise RuntimeError("database down")
        self.rows.append(row)
        return "id"


def run(coro):
    return asyncio.run(coro)


def test_no_handoff_means_no_write_and_the_same_result():
    store, result = FakeStore(), AgentResult(segments=[Segment(0, "template", template_id=1)])
    assert run(keep_the_promise(store, "customer", "C-1", result)) is result and store.rows == []


def test_the_handoff_is_written_before_the_answer_is_released():
    store, result = FakeStore(), handed()
    assert run(keep_the_promise(store, "customer", "C-100003", result)) is result
    assert [r["subject_id"] for r in store.rows] == ["C-100003"]


def test_when_the_write_fails_the_acknowledgement_is_never_shown():
    out = run(keep_the_promise(FakeStore(fail=True), "customer", "C-100003", handed("SAFE", "P1", ack=8), "حد دخل على حسابي"))
    assert [s.template_id for s in out.segments] == [COULD_NOT_FINISH] and out.handoff_reason is None
    assert out.segments[0].kind == "text" and "الطوارئ" in out.segments[0].text


# ---------- the database ----------
@pytest.fixture
def store():
    loop = asyncio.new_event_loop()                                  # the connection pool belongs to ONE loop: use it for every call
    s = HandoffStore()
    s.loop = loop

    async def up():
        await s.open()
        await s.ensure_schema()
        async with s._pool.connection() as conn:
            await conn.execute("DELETE FROM handoffs WHERE role = 'pytest'")
    try:
        loop.run_until_complete(up())
    except Exception as e:                                           # noqa: BLE001  no database in this run
        loop.close()
        pytest.skip(f"gateway database not reachable: {type(e).__name__}")
    yield s

    async def down():
        async with s._pool.connection() as conn:
            await conn.execute("DELETE FROM handoffs WHERE role = 'pytest'")
        await s.close()
    loop.run_until_complete(down())
    loop.close()


def one(store, sql, *args):
    async def go():
        async with store._pool.connection() as conn:
            cur = await conn.execute(sql, args)
            return await cur.fetchone()
    return store.loop.run_until_complete(go())


def make(store, **kw):
    return store.loop.run_until_complete(store.create({**build_row("pytest", "C-100003", handed(**kw)), "role": "pytest"}))


def test_a_new_case_is_pending_and_the_schema_can_be_made_twice(store):
    store.loop.run_until_complete(store.ensure_schema())
    hid = make(store)
    assert one(store, "SELECT status, subject_id, reason, summary->'verified_order_ids' FROM handoffs WHERE handoff_id = %s", hid) \
        == ("PENDING", "C-100003", "PENDING_OWNER", ["NC-100007"])


def test_a_case_is_claimed_once_and_only_from_pending(store):
    hid = make(store)
    assert one(store, "SELECT claim_handoff(%s, 'support-1')", hid) == (True,)
    assert one(store, "SELECT claim_handoff(%s, 'support-2')", hid) == (False,)               # already taken
    assert one(store, "SELECT status, claimed_by FROM handoffs WHERE handoff_id = %s", hid) == ("CLAIMED", "support-1")


def test_resolving_erases_the_verified_id_and_the_order_ids_and_keeps_the_rest(store):
    hid = make(store, reason="CMP", priority="P2")
    assert one(store, "SELECT resolve_handoff(%s, 'support-1', 'called the customer')", hid) == (True,)
    assert one(store, "SELECT status, subject_id, resolved_by, note, reason, priority, summary->'verified_order_ids', "
                      "resolved_at IS NOT NULL FROM handoffs WHERE handoff_id = %s", hid) \
        == ("RESOLVED", None, "support-1", "called the customer", "CMP", "P2", [], True)
    assert one(store, "SELECT summary->'parts'->0->>'label' FROM handoffs WHERE handoff_id = %s", hid) == ("Talk to a human",)


def test_a_resolved_case_cannot_be_resolved_or_claimed_again(store):
    hid = make(store)
    one(store, "SELECT resolve_handoff(%s, 'support-1', 'done')", hid)
    assert one(store, "SELECT resolve_handoff(%s, 'support-2', 'again')", hid) == (False,)
    assert one(store, "SELECT claim_handoff(%s, 'support-2')", hid) == (False,)
    assert one(store, "SELECT resolved_by, note FROM handoffs WHERE handoff_id = %s", hid) == ("support-1", "done")


def test_a_long_note_is_cut_to_1000_characters(store):
    hid = make(store)
    one(store, "SELECT resolve_handoff(%s, 'support-1', %s)", hid, "x" * 5000)
    assert one(store, "SELECT char_length(note) FROM handoffs WHERE handoff_id = %s", hid) == (1000,)
