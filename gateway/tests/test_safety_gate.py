"""Node 2 (safety_gate): code only, so no fake model is needed."""
from app.agent.safety_gate import safety_gate_node
from app.agent.state import AgentState, Intent, Part


def part(index, safety="SAFE", intent_id="C1", flags=()):
    return Part(index=index, safety=safety, intent=Intent(id=intent_id) if intent_id else None,
                escalation_flags=list(flags))


def test_classify_failure_writes_nothing():
    assert safety_gate_node(AgentState(classify_ok=False)) == {}


def test_classify_failure_is_not_judged_safe_even_with_parts_left_over():
    assert safety_gate_node(AgentState(classify_ok=False, parts=[part(0)])) == {}


def test_all_safe_parts_give_safe():
    state = AgentState(classify_ok=True, parts=[part(0), part(1, intent_id="C3")])
    assert safety_gate_node(state) == {"safety_flag": "SAFE"}


def test_empty_parts_after_a_good_classify_give_safe():
    assert safety_gate_node(AgentState(classify_ok=True)) == {"safety_flag": "SAFE"}


def test_one_p1_part_gives_the_p1_path():
    state = AgentState(classify_ok=True, parts=[part(0, "P1", intent_id=None), part(1)])
    assert safety_gate_node(state) == {"safety_flag": "P1", "handoff_reason": "SAFE", "priority": "P1"}


def test_p1_on_a_later_part_still_stops_everything():
    state = AgentState(classify_ok=True, parts=[part(0), part(1), part(2), part(3, "P1", intent_id=None)])
    assert safety_gate_node(state)["safety_flag"] == "P1"


def test_escalation_flags_alone_do_not_make_p1():
    state = AgentState(classify_ok=True, parts=[part(0, flags=["f"])])
    assert safety_gate_node(state) == {"safety_flag": "SAFE"}


def test_the_gate_does_not_change_the_state_it_reads():
    state = AgentState(classify_ok=True, parts=[part(0, "P1", intent_id=None)])
    before = state.model_dump()
    safety_gate_node(state)
    assert state.model_dump() == before


def test_intent_c7_counts_as_p1_even_when_classify_said_safe():
    state = AgentState(classify_ok=True, parts=[part(0), part(1, "SAFE", intent_id="C7")])
    assert safety_gate_node(state) == {"safety_flag": "P1", "handoff_reason": "SAFE", "priority": "P1"}


def test_other_intents_do_not_count_as_p1():
    state = AgentState(classify_ok=True, parts=[part(0, intent_id="C10"), part(1, intent_id="W4")])
    assert safety_gate_node(state) == {"safety_flag": "SAFE"}
