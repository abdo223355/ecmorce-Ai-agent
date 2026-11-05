"""Node 5 (handoff): code only. The final handoff of the turn: reason, priority, one acknowledgement, the no-data
flag and a summary that holds labels and outcomes, never user text or real values."""
import json
import time

import pytest

from app.agent import AgentContext
from app.agent.handoff import handoff_node
from app.agent.state import AgentState, Intent, Part, PartOutcome, Section, ToolRecord
from app.tools import ToolResult


def ctx(role="customer", refs=None):
    return AgentContext(role=role, message="x", chat_id="c:s", deadline_at=time.monotonic() + 8,
                        order_refs=refs or {})


def part(index, intent_id="C1", outcome=None, safety="SAFE", p1_flag=None, **arguments):
    intent = Intent(id=intent_id, arguments=arguments) if intent_id is not None else None
    return Part(index=index, safety=safety, p1_flag=p1_flag, intent=intent, outcome=outcome)


def out(template=None, reason=None, priority=None, kind="template", **kw):
    return PartOutcome(kind=kind, template_id=template, handoff_reason=reason, priority=priority, **kw)


def run(parts, safety_flag=None, role="customer", records=(), refs=None):
    state = AgentState(classify_ok=True, parts=parts, safety_flag=safety_flag, tool_results=list(records))
    return handoff_node(state, ctx(role, refs))


# ---------- no handoff ----------
def test_no_handoff_source_means_the_node_adds_nothing():
    assert run([part(0, outcome=out(1))], "SAFE") == {}
    assert run([part(0)], None) == {}


# ---------- the reason and priority rule ----------
def test_the_most_urgent_priority_wins_and_none_counts_as_least_urgent():
    u = run([part(0, "C6", out(5, "PENDING_OWNER")), part(1, "C1", out(11, "BKD", "P3"))])
    assert (u["handoff"].reason, u["handoff"].priority) == ("BKD", "P3")
    assert (u["handoff_reason"], u["priority"]) == ("BKD", "P3")                  # the final values are written too


def test_a_tie_goes_to_the_earlier_part():
    u = run([part(0, "C10", out(5, "CMP")), part(1, "C6", out(5, "PENDING_OWNER"))])
    assert u["handoff"].reason == "CMP"
    u = run([part(0, "C8", out(10, "SCOPE", "P4")), part(1, "C1", out(11, "BKD", "P4"))])
    assert u["handoff"].reason == "SCOPE"


def test_a_p1_from_the_gate_beats_every_part():
    u = run([part(0, "C6", out(5, "PENDING_OWNER")), part(1, None, None, "P1", "takeover")], safety_flag="P1")
    assert (u["handoff"].reason, u["handoff"].priority) == ("SAFE", "P1")


# ---------- the acknowledgement ----------
def test_one_acknowledgement_for_the_turn_and_ack_only_parts_lose_their_template():
    u = run([part(0, "C6", out(5, "PENDING_OWNER")), part(1, "C10", out(5, "CMP")), part(2, "C1", out(11, "BKD", "P3"))])
    assert u["handoff"].acknowledgement_template == 5
    kinds = [(p.outcome.kind, p.outcome.template_id) for p in u["parts"]]
    assert kinds == [("handoff", None), ("handoff", None), ("template", 11)]       # 11 is a real answer, not an ack
    assert [p.outcome.handoff_reason for p in u["parts"]] == ["PENDING_OWNER", "CMP", "BKD"]


def test_the_acknowledgement_depends_on_the_role_and_p1():
    assert run([part(0, "C6", out(5, "PENDING_OWNER"))])["handoff"].acknowledgement_template == 5
    assert run([part(0, "W5", out(6, "PENDING_OWNER"))], role="worker")["handoff"].acknowledgement_template == 6
    assert run([part(0, None, None, "P1", "danger")], safety_flag="P1")["handoff"].acknowledgement_template == 8


# ---------- the no-data flag (CP-44, N1) ----------
@pytest.mark.parametrize("flag, blocked", [("takeover", True), ("exposure", True), ("danger", False), (None, True)])
def test_only_takeover_exposure_or_an_unflagged_p1_blocks_the_session_data(flag, blocked):
    u = run([part(0, None, None, "P1", flag)], safety_flag="P1")
    assert u["handoff"].block_session_data is blocked


def test_one_blocking_p1_among_several_blocks_and_c7_without_a_flag_blocks():
    u = run([part(0, None, None, "P1", "danger"), part(1, None, None, "P1", "exposure")], safety_flag="P1")
    assert u["handoff"].block_session_data is True
    u = run([part(0, "C7", None, "SAFE", None)], safety_flag="P1")                 # the gate made it P1 through C7
    assert u["handoff"].block_session_data is True


def test_no_blocking_without_a_p1():
    assert run([part(0, "C6", out(5, "PENDING_OWNER"))])["handoff"].block_session_data is False


# ---------- the summary ----------
def test_the_summary_has_labels_outcomes_clues_errors_and_policies():
    records = [ToolRecord(tool="order_details", argument="NC-100001", result=ToolResult("unavailable", reason="backend_unavailable"))]
    parts = [part(0, "C1", out(11, "BKD", "P3"), item_clue="watch"),
             part(1, "C4", out(None, kind="reply", cited=["POL-RET-001 §2@2.1"], sections=[Section(cited="POL-RET-001 §2@2.1", text="t")])),
             part(2, "C13", out(9))]
    s = run(parts, records=records)["handoff"].summary
    assert [(p.part_index, p.intent, p.label, p.outcome) for p in s.parts] == [
        (0, "C1", "Order status", "information_unavailable"), (1, "C4", "Policy or definition question", "policy_answer"),
        (2, "C13", "Topic outside scope (no policy, no tool)", "out_of_scope")]
    assert s.parts[0].clue == "watch" and s.parts[1].clue is None
    assert s.error_codes == ["order_details:unavailable:backend_unavailable"] and s.policies == ["POL-RET-001 §2@2.1"]


@pytest.mark.parametrize("clue", ["call me on 01012345678", "x" * 41, "me@mail.com", "see http://x.y", "", "   "])
def test_an_unsafe_or_empty_clue_is_dropped(clue):
    s = run([part(0, "C1", out(11, "BKD", "P3"), item_clue=clue)])["handoff"].summary
    assert s.parts[0].clue is None


def test_an_order_id_is_shown_only_when_a_tool_confirmed_it_is_the_users():
    refs = {"order_ref_1": "NC-100001", "order_ref_2": "NC-100002"}
    records = [ToolRecord(tool="order_details", argument="NC-100001", result=ToolResult("ok", data="d")),
               ToolRecord(tool="order_details", argument="NC-100002", result=ToolResult("denied", reason="not_found_or_not_yours")),
               ToolRecord(tool="order_details", argument="NC-100003", result=ToolResult("ok", data="d"))]   # not mentioned
    parts = [part(0, "C1", out(5, "CMP"), order_ref="order_ref_1"), part(1, "C1", out(5, "CMP"), order_ref="order_ref_2")]
    s = run(parts, records=records, refs=refs)["handoff"].summary
    assert s.verified_order_ids == ["NC-100001"] and s.order_number_mentioned_unverified is True


def test_no_mention_means_no_unverified_flag():
    s = run([part(0, "C6", out(5, "PENDING_OWNER"))])["handoff"].summary
    assert s.verified_order_ids == [] and s.order_number_mentioned_unverified is False


def test_a_part_the_plan_never_ran_is_not_processed_and_a_p1_part_is_a_safety_report():
    u = run([part(0, "C2", None), part(1, None, None, "P1", "exposure")], safety_flag="P1")
    assert [p.outcome for p in u["handoff"].summary.parts] == ["not_processed", "safety_report"]


def test_the_summary_never_holds_a_real_value_a_message_or_a_section_text():
    render = {"order_id": "NC-100001", "customer_name": "Sara Ali", "customer_phone": "01012345678", "address": "12 Nile St"}
    sections = [Section(cited="POL-RET-001 §2@2.1", text="SECRET policy wording")]
    parts = [part(0, "C1", out(11, "BKD", "P3", render_values=render, text="Hello Sara Ali, call 01012345678")),
             part(1, "C4", out(None, kind="reply", sections=sections, cited=["POL-RET-001 §2@2.1"]))]
    dumped = json.dumps(run(parts)["handoff"].summary.model_dump(), ensure_ascii=False)
    for secret in ["NC-100001", "Sara Ali", "01012345678", "12 Nile St", "SECRET policy wording", "Hello"]:
        assert secret not in dumped


# ---------- the node itself ----------
def test_the_same_input_gives_the_same_output():
    parts = [part(0, "C6", out(5, "PENDING_OWNER")), part(1, "C1", out(11, "BKD", "P3"))]
    assert run(parts)["handoff"].model_dump() == run(parts)["handoff"].model_dump()


def test_the_state_it_reads_is_not_changed():
    state = AgentState(classify_ok=True, parts=[part(0, "C6", out(5, "PENDING_OWNER"))])
    before = state.model_dump()
    handoff_node(state, ctx())
    assert state.model_dump() == before


def test_the_final_handoff_replaces_the_template_of_ack_only_parts_for_the_worker_too():
    u = run([part(0, "W5", out(6, "PENDING_OWNER"))], role="worker")
    assert (u["parts"][0].outcome.kind, u["parts"][0].outcome.template_id) == ("handoff", None)
