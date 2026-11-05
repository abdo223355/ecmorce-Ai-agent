"""The events table: one row per request for the admin dashboard.

Unit tests need nothing. The integration test needs the Gateway PostgreSQL and skips if it is down.
"""
import asyncio
import json

import pytest

from app.agent import AgentContext, AgentResult, Segment
from app.agent.assemble import assemble_node
from app.agent.classify import classify_node
from app.agent.state import AgentState, add_telemetry
from app.events import EventStore, build_event, public_answer
from app.llm.client import set_adapter
from app.llm.fake import FakeAdapter


def result(segments=None, telemetry=None, reason=None, priority=None):
    return AgentResult(segments=segments or [Segment(0, "template", template_id=1)], handoff_reason=reason,
                       priority=priority, telemetry=telemetry or {})


# ---------- build_event (pure) ----------
def test_an_event_holds_the_measurements_the_outcomes_and_the_handoff():
    telemetry = {"classify": {"path": "llm", "status": "ok", "latency_s": 1.4},
                 "reply": {"status": "timeout", "reason": "deadline_exceeded", "latency_s": 2.5, "written": 0}}
    event = build_event("customer", result([Segment(0, "template", template_id=18)], telemetry, "BKD", "P3"), 4.1234)
    assert event == {"role": "customer", "classify_path": "llm", "classify_status": "ok", "classify_reason": None,
                     "classify_latency_s": 1.4, "reply_status": "timeout", "reply_reason": "deadline_exceeded",
                     "reply_latency_s": 2.5, "total_latency_s": 4.123,
                     "outcomes": [{"kind": "template", "template_id": 18}],
                     "handoff_reason": "BKD", "priority": "P3", "p1": False}


def test_a_request_with_no_measurements_still_makes_a_valid_event():
    event = build_event("worker", result(), 0.2)
    assert event["classify_status"] is None and event["reply_status"] is None and event["p1"] is False


def test_p1_is_a_safety_handoff_with_priority_p1():
    assert build_event("customer", result(reason="SAFE", priority="P1"), 1.0)["p1"] is True
    assert build_event("customer", result(reason="POL", priority="P1"), 1.0)["p1"] is False


def test_an_event_never_carries_text_or_a_person_id():
    r = AgentResult(segments=[Segment(0, "text", text="Your order NC-100001 is shipped", template_id=1,
                                      render_values={"order_id": "NC-100001"})],
                    handoff_summary={"order": "NC-100001"})
    event = build_event("customer", r, 1.0)
    blob = json.dumps(event)
    assert "NC-100001" not in blob and "shipped" not in blob
    assert not {"text", "message", "customer_id", "worker_id", "subject", "sub"} & set(event)


def test_the_answer_for_the_user_leaves_the_measurements_out():
    answer = public_answer(result(telemetry={"classify": {"status": "ok"}}))
    assert "telemetry" not in answer and answer["segments"][0]["template_id"] == 1


# ---------- the nodes write their entries ----------
def test_add_telemetry_keeps_the_entries_already_there():
    state = AgentState(telemetry={"classify": {"status": "ok"}})
    assert add_telemetry(state, "reply", status="ok") == {"telemetry": {"classify": {"status": "ok"}, "reply": {"status": "ok"}}}


def ctx(message="hello there", role="customer"):
    return AgentContext(role=role, message=message, chat_id="c", deadline_at=10**12)


def test_classify_reports_the_code_path_without_a_model_call():
    fake = FakeAdapter()
    set_adapter(fake)                                        # no network in a unit test, whatever the environment holds
    try:
        out = asyncio.run(classify_node(AgentState(), ctx("فين طلبي ؟")))
    finally:
        set_adapter(None)
    assert out["classify_ok"] is True and fake.calls == []
    assert out["telemetry"]["classify"] == {"path": "code", "status": "ok", "latency_s": 0.0}


def test_classify_reports_a_failed_model_call_with_its_status():
    set_adapter(FakeAdapter())                               # an empty queue answers "unavailable"
    try:
        out = asyncio.run(classify_node(AgentState(), ctx("a long unusual question about my parcel and more")))
    finally:
        set_adapter(None)
    entry = out["telemetry"]["classify"]
    assert out["classify_ok"] is False and entry["path"] == "llm" and entry["status"] == "unavailable"
    assert entry["reason"] == "fake_queue_empty"


def test_assemble_copies_the_measurements_into_the_result():
    state = AgentState(telemetry={"classify": {"path": "code", "status": "ok", "latency_s": 0.0}})
    out = assemble_node(state, ctx())
    assert out["result"].telemetry == {"classify": {"path": "code", "status": "ok", "latency_s": 0.0}}


# ---------- the store ----------
def test_writing_an_event_never_raises_even_when_the_database_is_down():
    store = EventStore(dsn="postgresql://gateway:gateway@127.0.0.1:1/gateway")     # nothing listens on port 1

    async def go():
        await store.open()
        try:
            await store.record(build_event("customer", result(), 1.0))
        finally:
            await store.close()
    asyncio.run(go())                                        # the assertion is that no exception comes out


def test_an_event_is_written_and_read_back():
    store = EventStore()

    async def go():
        await store.open()
        try:
            await store.ensure_schema()
            async with store._pool.connection() as conn:
                await conn.execute("DELETE FROM events WHERE role = 'pytest'")
            await store.record(build_event("pytest", result(telemetry={"reply": {"status": "ok", "latency_s": 1.2}}), 2.0))
            async with store._pool.connection() as conn:
                cur = await conn.execute("SELECT role, reply_status, reply_latency_s, outcomes FROM events WHERE role = 'pytest'")
                rows = await cur.fetchall()
                await conn.execute("DELETE FROM events WHERE role = 'pytest'")
            return rows
        finally:
            await store.close()
    try:
        rows = asyncio.run(go())
    except Exception as e:                                   # noqa: BLE001  no database in this run
        pytest.skip(f"gateway database not reachable: {type(e).__name__}")
    assert rows == [("pytest", "ok", pytest.approx(1.2), [{"kind": "template", "template_id": 1}])]
