"""Node 3 (plan), slice 2: handoff-only intents. No tool may be called for any of them."""
import asyncio
import time

import pytest

from app.agent import AgentContext
from app.agent.plan import plan_node
from app.agent.state import AgentState, Intent, Part


class NoTools:
    """Any tool call fails the test."""
    def __getattr__(self, name):
        raise AssertionError(f"a handoff-only intent must not call {name}")


def run(role, parts):
    ctx = AgentContext(role=role, message="x", chat_id="c:s", deadline_at=time.monotonic() + 8)
    return asyncio.run(plan_node(AgentState(classify_ok=True, parts=parts), ctx, NoTools()))


def part(index, intent_id, **arguments):
    return Part(index=index, safety="SAFE", intent=Intent(id=intent_id, arguments=arguments))


@pytest.mark.parametrize("role, intent, template, reason, priority", [
    ("customer", "C6", 5, "PENDING_OWNER", None),
    ("customer", "C7", 8, "SAFE", "P1"),
    ("customer", "C8", 10, "SCOPE", "P4"),
    ("customer", "C10", 5, "CMP", None),
    ("customer", "C12", 5, "PENDING_OWNER", None),
    ("worker", "W5", 6, "PENDING_OWNER", None),
])
def test_handoff_intents_give_a_template_and_a_handoff_without_calling_tools(role, intent, template, reason, priority):
    u = run(role, [part(0, intent)])
    o = u["parts"][0].outcome
    assert (o.kind, o.template_id, o.handoff_reason, o.priority) == ("template", template, reason, priority)
    assert "handoff_reason" not in u                                                # derived once, by the handoff node
    assert u["tool_results"] == []


@pytest.mark.parametrize("intent, arguments, template", [
    ("W4", {"requested_fields": ["email"]}, 17),
    ("W4", {"shipment_id": "S-700009"}, 16),
    ("W4", {}, 17),
    ("W9", {}, 9),
])
def test_worker_neutral_replies_have_no_handoff(intent, arguments, template):
    u = run("worker", [part(0, intent, **arguments)])
    o = u["parts"][0].outcome
    assert (o.kind, o.template_id, o.handoff_reason) == ("template", template, None)
    assert "handoff_reason" not in u


def test_a_customer_cannot_reach_a_worker_row():
    assert run("customer", [part(0, "W5")])["parts"][0].outcome is None


def test_c13_is_a_neutral_reply_with_no_handoff():
    u = run("customer", [part(0, "C13")])
    o = u["parts"][0].outcome
    assert (o.kind, o.template_id, o.handoff_reason) == ("template", 9, None)
    assert "handoff_reason" not in u and u["tool_results"] == []
