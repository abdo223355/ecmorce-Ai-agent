"""Node 7 (assemble): code only. It turns the parts and the handoff into the AgentResult the Gateway receives."""
import json
import time
from dataclasses import asdict

import pytest

from app.agent import AgentContext
from app.agent.assemble import ACK_BEFORE, COULD_NOT_FINISH, assemble_node
from app.agent.handoff import handoff_node
from app.agent.state import AgentState, Intent, Part, PartOutcome, Section


def ctx(role="customer"):
    return AgentContext(role=role, message="my private message", chat_id="c:s", deadline_at=time.monotonic() + 8)


def part(index, outcome=None, intent_id="C1", safety="SAFE", p1_flag=None):
    intent = Intent(id=intent_id) if intent_id else None
    return Part(index=index, safety=safety, p1_flag=p1_flag, intent=intent, outcome=outcome)


def assemble(parts, handoff_from_node=False, safety_flag=None, role="customer"):
    state = AgentState(classify_ok=True, parts=parts, safety_flag=safety_flag)
    if handoff_from_node:
        state = state.model_copy(update=handoff_node(state, ctx(role)))
    return assemble_node(state, ctx(role))["result"]


def out(kind="template", template=None, **kw):
    return PartOutcome(kind=kind, template_id=template, **kw)


def summary(result):
    return [(s.part_index, s.kind, s.template_id) for s in result.segments]


# ---------- one segment per part ----------
def test_a_template_part_becomes_a_template_segment_with_its_render_values():
    r = assemble([part(0, out(template=1, render_values={"order_status": "Shipped"}))])
    s = r.segments[0]
    assert (s.kind, s.template_id, s.render_values) == ("template", 1, {"order_status": "Shipped"})


def test_a_reply_with_words_becomes_a_text_segment_keeping_the_fallback_and_the_citations():
    o = out("reply", 1, text="Order {order_id} is Shipped.", render_values={"order_id": "NC-1"}, cited=["POL-RET-001 §2@2.1"],
            sections=[Section(cited="POL-RET-001 §2@2.1", text="policy text")], llm_facts={"order_status": "Shipped"})
    r = assemble([part(0, o)])
    s = r.segments[0]
    assert (s.kind, s.text, s.template_id, s.cited) == ("text", "Order {order_id} is Shipped.", 1, ["POL-RET-001 §2@2.1"])
    assert r.cited == ["POL-RET-001 §2@2.1"]


def test_a_reply_that_never_got_words_falls_back_to_its_template_else_18():
    assert summary(assemble([part(0, out("reply", 2))])) == [(0, "template", 2)]
    assert summary(assemble([part(0, out("reply", None))])) == [(0, "template", COULD_NOT_FINISH)]


def test_a_clarify_part_becomes_a_clarify_segment_and_a_deferred_one_has_no_segment():
    asked = out("clarify", text="Which order?\n{choices_text}", render_values={"choices_text": "1) Watch"}, reason="missing_order_id")
    deferred = out("clarify", reason="which_return")
    r = assemble([part(0, asked), part(1, deferred, "C3")])
    assert summary(r) == [(0, "clarify", None)] and r.segments[0].render_values == {"choices_text": "1) Watch"}


def test_a_handoff_kind_part_has_no_segment_of_its_own():
    r = assemble([part(0, out("handoff", handoff_reason="PENDING_OWNER"))])
    assert summary(r) == [(0, "template", COULD_NOT_FINISH)]            # nothing else to send: never silence


def test_an_intent_with_no_outcome_gets_the_interim_18_and_a_part_with_no_intent_says_nothing():
    assert summary(assemble([part(0, None, "C2")])) == [(0, "template", COULD_NOT_FINISH)]
    r = assemble([part(0, out(template=1)), part(1, None, None)])
    assert summary(r) == [(0, "template", 1)]


def test_segments_come_in_written_order():
    r = assemble([part(2, out(template=3), "W1"), part(0, out(template=1)), part(1, out(template=2), "C3")])
    assert [s.part_index for s in r.segments] == [0, 1, 2]


# ---------- the handoff and the acknowledgement ----------
def test_the_acknowledgement_is_last_for_a_normal_handoff_and_there_is_one():
    parts = [part(0, out(template=11, handoff_reason="BKD", priority="P3")),
             part(1, out(template=5, handoff_reason="CMP"), "C10"), part(2, out(template=5, handoff_reason="PENDING_OWNER"), "C6")]
    r = assemble(parts, handoff_from_node=True)
    assert summary(r) == [(0, "template", 11), (3, "template", 5)]       # the two ack-only parts lost their template
    assert (r.handoff_reason, r.priority) == ("BKD", "P3")


def test_a_p1_acknowledgement_comes_first_and_blocks_data_when_needed():
    r = assemble([part(0, None, None, "P1", "takeover"), part(1, None, "C1")], handoff_from_node=True, safety_flag="P1")
    assert r.segments[0].part_index == ACK_BEFORE and r.segments[0].template_id == 8
    assert (r.handoff_reason, r.priority, r.block_session_data) == ("SAFE", "P1", True)


def test_danger_does_not_block_the_session_data():
    r = assemble([part(0, None, None, "P1", "danger")], handoff_from_node=True, safety_flag="P1")
    assert r.block_session_data is False and r.segments[0].template_id == 8


def test_the_worker_acknowledgement_is_template_6():
    r = assemble([part(0, out(template=6, handoff_reason="PENDING_OWNER"), "W5")], handoff_from_node=True, role="worker")
    assert summary(r) == [(1, "template", 6)] and r.handoff_reason == "PENDING_OWNER"


def test_the_summary_travels_as_plain_data_with_no_user_text():
    r = assemble([part(0, out(template=11, handoff_reason="BKD", priority="P3", render_values={"order_id": "NC-1"}))],
                 handoff_from_node=True)
    assert isinstance(r.handoff_summary, dict) and r.handoff_summary["parts"][0]["outcome"] == "information_unavailable"
    assert "my private message" not in json.dumps(asdict(r), ensure_ascii=False)


# ---------- what must never leave the agent ----------
def test_no_llm_facts_section_text_or_message_is_in_the_result():
    o = out("reply", 1, text="Done.", llm_facts={"secret_fact": "LLMONLY"}, sections=[Section(cited="POL-X §1@1", text="SECTIONTEXT")],
            cited=["POL-X §1@1"])
    dumped = json.dumps(asdict(assemble([part(0, o)])), ensure_ascii=False)
    assert "LLMONLY" not in dumped and "SECTIONTEXT" not in dumped and "my private message" not in dumped


# ---------- never silence, never a mutation ----------
def test_an_empty_turn_still_sends_template_18():
    assert summary(assemble([])) == [(0, "template", COULD_NOT_FINISH)]
    assert summary(assemble([part(0, None, None)])) == [(0, "template", COULD_NOT_FINISH)]


def test_the_result_is_deterministic_json_ready_and_the_state_is_not_changed():
    state = AgentState(classify_ok=True, parts=[part(0, out(template=1, render_values={"a": "b"}))])
    before = state.model_dump()
    a, b = assemble_node(state, ctx())["result"], assemble_node(state, ctx())["result"]
    assert state.model_dump() == before and asdict(a) == asdict(b)
    json.dumps(asdict(a))


@pytest.mark.parametrize("kind", ["template", "reply", "clarify", "handoff"])
def test_every_outcome_kind_is_handled_without_an_error(kind):
    assemble([part(0, out(kind, 1))])


def test_a_p1_stops_every_part_so_parts_the_plan_never_ran_say_nothing():
    r = assemble([part(0, None, None, "P1", "takeover"), part(1, None, "C1"), part(2, None, "C3")],
                 handoff_from_node=True, safety_flag="P1")
    assert summary(r) == [(ACK_BEFORE, "template", 8)]                     # only the emergency acknowledgement


def test_without_a_p1_an_intent_with_no_outcome_still_gets_the_interim_18():
    r = assemble([part(0, out(template=1)), part(1, None, "C2")], safety_flag="SAFE")
    assert summary(r) == [(0, "template", 1), (1, "template", COULD_NOT_FINISH)]
