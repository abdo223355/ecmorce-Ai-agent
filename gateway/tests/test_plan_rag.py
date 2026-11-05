"""Node 3 (plan), slice 3: C4, W8, C14 answered from the policy documents. A fake Tools object counts every call."""
import asyncio
import time

import pytest

from app.agent import AgentContext
from app.agent.plan import plan_node
from app.agent.plan_spec import FromCtx, FromEnv, StepEnv
from app.agent.state import AgentState, Intent, Part
from app.tools import ToolResult


def chunk(cited="POL-RET-001 §2@2.1", text="Returns are accepted within the window."):
    return {"doc_id": cited.split()[0], "version": "2.1", "section": "2", "part": 1, "title": "Return Window",
            "text": text, "score": 0.5, "vector_score": 0.7, "cited": cited}


class FakeTools:
    def __init__(self, result=None):
        self.result = result if result is not None else ToolResult("ok", data=[chunk()])
        self.calls = []

    async def policy_search(self, query, english_query=None):
        self.calls.append(("policy_search", query, english_query))
        return self.result

    async def procedure_search(self, query, english_query=None):
        self.calls.append(("procedure_search", query, english_query))
        return self.result


def ctx(role="customer", message="what is the return window"):
    return AgentContext(role=role, message=message, chat_id="c:s", deadline_at=time.monotonic() + 8)


def part(index, intent_id, explain=False):
    return Part(index=index, safety="SAFE", intent=Intent(id=intent_id), needs_explanation=explain)


def plan(tools, parts, role="customer", message="what is the return window", english="return window"):
    state = AgentState(classify_ok=True, parts=parts, english_query=english)
    return asyncio.run(plan_node(state, ctx(role, message), tools))


def outcome(update, index=0):
    return update["parts"][index].outcome


def test_c4_sends_the_message_and_the_english_query_and_goes_to_the_reply_with_its_sections():
    tools = FakeTools()
    u = plan(tools, [part(0, "C4")])
    assert tools.calls == [("policy_search", "what is the return window", "return window")]
    o = outcome(u)
    assert o.kind == "reply" and o.template_id is None                 # a policy explanation has no template
    assert [(s.cited, s.text) for s in o.sections] == [("POL-RET-001 §2@2.1", "Returns are accepted within the window.")]
    assert o.llm_facts == {} and o.render_values == {}


def test_c4_goes_to_the_reply_even_when_the_part_does_not_ask_for_an_explanation():
    assert outcome(plan(FakeTools(), [part(0, "C4", explain=False)])).kind == "reply"


def test_a_missing_english_query_is_passed_as_empty():
    tools = FakeTools()
    plan(tools, [part(0, "C4")], english=None)
    assert tools.calls == [("policy_search", "what is the return window", "")]


def test_w8_uses_the_worker_search():
    tools = FakeTools()
    o = outcome(plan(tools, [part(0, "W8")], "worker"))
    assert tools.calls[0][0] == "procedure_search" and o.kind == "reply" and o.sections


@pytest.mark.parametrize("result", [ToolResult("ok", data=[]), ToolResult("ok", data=[{"cited": "", "text": ""}])])
@pytest.mark.parametrize("role, intent, priority", [("customer", "C4", None), ("worker", "W8", None),
                                                    ("customer", "C14", "P3")])
def test_a_silent_policy_is_template_12_and_a_pol_handoff(result, role, intent, priority):
    u = plan(FakeTools(result), [part(0, intent)], role)
    o = outcome(u)
    assert (o.kind, o.template_id, o.handoff_reason, o.priority) == ("template", 12, "POL", priority)
    assert o.sections == []
    assert "handoff_reason" not in u


def test_a_search_that_cannot_run_is_template_11_with_a_bkd_handoff():
    u = plan(FakeTools(ToolResult("unavailable", reason="no_time_for_retrieval")), [part(0, "C4")])
    o = outcome(u)
    assert (o.template_id, o.handoff_reason, o.priority) == (11, "BKD", "P3")


def test_at_most_eight_sections_and_chunks_without_text_or_citation_are_skipped():
    chunks = [chunk(f"POL-RET-001 §{i}@2.1", f"text {i}") for i in range(1, 11)] + [{"cited": "", "text": "x"}]
    o = outcome(plan(FakeTools(ToolResult("ok", data=chunks)), [part(0, "C4")]))
    assert len(o.sections) == 8 and o.sections[0].cited == "POL-RET-001 §1@2.1"


def test_two_policy_parts_share_one_search():
    tools = FakeTools()
    u = plan(tools, [part(0, "C4"), part(1, "C14")])
    assert len(tools.calls) == 1 and len(u["tool_results"]) == 1
    assert outcome(u, 0).sections == outcome(u, 1).sections


def test_the_record_keeps_a_digest_of_a_long_message_not_the_message():
    long_message = "what is the return window for a watch that arrived damaged " * 4
    u = plan(FakeTools(), [part(0, "C4")], message=long_message)
    argument = u["tool_results"][0].argument
    assert argument.endswith("|" + argument.split("|")[1]) and argument.split("|")[1].startswith("sha1:")
    assert "damaged" not in argument                                    # the english query is short and kept as is
    again = plan(FakeTools(), [part(0, "C4")], message=long_message)
    assert again["tool_results"][0].argument == argument                # same text, same key


def test_the_sections_hold_policy_text_only_nothing_from_the_user():
    o = outcome(plan(FakeTools(), [part(0, "C4")], message="my phone is 01012345678, what is the return window"))
    assert "01012345678" not in " ".join(s.text for s in o.sections)


def test_the_new_argument_sources_read_only_what_they_are_allowed_to():
    env = StepEnv(ctx(message="hello"), Intent(id="C4"), english_query="eq")
    assert FromCtx("message").resolve(env) == "hello"
    assert FromEnv("english_query", default="").resolve(env) == "eq"
    assert FromEnv("english_query", default="").resolve(StepEnv(ctx(), Intent(id="C4"))) == ""
    with pytest.raises(ValueError):
        FromCtx("chat_id").resolve(env)
    with pytest.raises(ValueError):
        FromEnv("parts").resolve(env)
