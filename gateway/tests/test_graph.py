"""The router and the two agents' graphs, end to end, with a fake model and fake tools: no network, no key."""
import asyncio
import time
from dataclasses import asdict
from datetime import date, datetime

import pytest

from app.agent import AgentContext, AgentRejected, run_agent
from app.agent.edges import decide_next
from app.agent.graph import AgentRuntime, build_system
from app.agent.spec import AGENTS, CUSTOMER_AGENT, WORKER_AGENT
from app.agent.state import AgentState
from app.llm import LLMResult, client
from app.llm.fake import FakeAdapter
from app.schemas import OrderSummaryView, OrderView, TodayView
from app.tools import ToolResult

NOW = datetime(2026, 10, 18, 12, 0)


def summary(order_id, *names):
    return OrderSummaryView(order_id=order_id, order_date=NOW, status="Shipped", product_names=list(names), last_updated=NOW)


class FakeTools:
    def __init__(self, recent=None, orders=None, chunks=None):
        self.recent, self.orders, self.chunks, self.calls = recent or [], orders or {}, chunks or [], []

    async def my_recent_orders(self):
        self.calls.append("my_recent_orders")
        return ToolResult("ok", data=self.recent)

    async def order_details(self, order_id):
        self.calls.append("order_details")
        got = self.orders.get(order_id)
        return ToolResult("ok", data=got) if got else ToolResult("denied", reason="not_found_or_not_yours")

    async def my_shipments_today(self, query):
        self.calls.append("my_shipments_today")
        return ToolResult("ok", data=TodayView(query=query, date=date(2026, 10, 18), count=0, rows=[]))

    async def policy_search(self, query, english_query=None):
        self.calls.append("policy_search")
        return ToolResult("ok", data=self.chunks)

    async def shipment_details(self, shipment_id, requested_fields):
        self.calls.append("shipment_details")
        return ToolResult("denied", reason="not_found_or_not_yours")


def order(order_id):
    return OrderView(order_id=order_id, order_date=NOW, status="Shipped", delivered_at=None, items=[], returns=[],
                     last_updated=NOW)


def ctx(role="customer", message="x", refs=None, clarify_round=0):
    return AgentContext(role=role, message=message, chat_id="c:s", deadline_at=time.monotonic() + 8,
                        order_refs=refs or {}, clarify_round=clarify_round)


def cpart(intent=None, safety="SAFE", p1_flag=None, expl=False, **args):
    a = {"order_ref": None, "item_clue": None, "return_id": None, **args}
    return {"safety": safety, "escalation_flags": [], "p1_flag": p1_flag, "intent_id": intent, "needs_explanation": expl, "args": a}


def classify_answer(*parts, english=None):
    return {"parts": list(parts), "english_query": english}


@pytest.fixture
def fake():
    def install(*responses):
        f = FakeAdapter(*responses)
        client.set_adapter(f)
        return f
    yield install
    client.set_adapter(None)


def run(context, tools):
    return asyncio.run(run_agent(context, tools))


async def _raw_trace(context, tools):
    """Every node that ran, in order, across the router, the agent graph, the supervisor and the workers."""
    names = []
    async for _, chunk in build_system().astream(AgentState(), context=AgentRuntime(context, tools),
                                                 config={"recursion_limit": 60}, stream_mode="updates", subgraphs=True):
        names.extend(chunk)
    return names


def raw_trace(context, tools):
    return asyncio.run(_raw_trace(context, tools))


PATTERN_NODES = {"router", "supervisor", "customer_agent", "delivery_agent"}


def trace(context, tools):
    """Only the stage nodes (the workers and the planner), by their short names."""
    return [("plan" if n == "planner" else n.removeprefix("worker_")) for n in raw_trace(context, tools) if n not in PATTERN_NODES]


def shape(result):
    return [(s.part_index, s.kind, s.template_id) for s in result.segments]


# ---------- the router ----------
def test_the_router_rejects_any_role_that_has_no_agent():
    for role in ("cs", "approver", "ops", "", "Customer"):
        with pytest.raises(AgentRejected):
            run(ctx(role=role), FakeTools())


def test_the_router_sends_each_role_to_its_own_agent_graph(fake):
    fake()
    customer = raw_trace(ctx(message="فين طلبي"), FakeTools(recent=[summary("NC-100001", "S")], orders={"NC-100001": order("NC-100001")}))
    delivery = raw_trace(ctx("worker", "شحناتي النهارده"), FakeTools())
    assert customer[0] == delivery[0] == "router"
    assert "customer_agent" in customer and "delivery_agent" not in customer
    assert "delivery_agent" in delivery and "customer_agent" not in delivery


def test_the_supervisor_runs_between_every_pair_of_workers_and_the_run_ends_after_assemble(fake):
    fake()
    names = raw_trace(ctx("worker", "شحناتي النهارده"), FakeTools())
    inner = [n for n in names if n not in {"router", "customer_agent", "delivery_agent"}]
    assert inner == ["supervisor", "worker_classify", "supervisor", "worker_safety_gate", "supervisor", "planner",
                     "supervisor", "worker_assemble", "supervisor"]


def test_the_two_agents_have_their_own_data():
    assert set(AGENTS) == {"customer", "worker"}
    assert all(i.startswith("C") for i in CUSTOMER_AGENT.catalog.intents) and all(i.startswith("W") for i in WORKER_AGENT.catalog.intents)
    assert all(i.startswith("C") for i in CUSTOMER_AGENT.plans) and all(i.startswith("W") for i in WORKER_AGENT.plans)
    assert set(CUSTOMER_AGENT.plans) <= set(CUSTOMER_AGENT.catalog.intents) and set(WORKER_AGENT.plans) <= set(WORKER_AGENT.catalog.intents)
    assert not CUSTOMER_AGENT.tools & WORKER_AGENT.tools                  # no tool is shared between the agents
    assert (CUSTOMER_AGENT.acknowledgement_template, WORKER_AGENT.acknowledgement_template) == (5, 6)


def test_a_plan_only_uses_tools_its_agent_may_use():
    for spec in AGENTS.values():
        for plan in spec.plans.values():
            for branch in plan.branches:
                for step in branch.steps:
                    assert step.tool in spec.tools


# ---------- the customer agent ----------
def test_a_plain_message_takes_the_code_path_with_no_model_call(fake):
    f = fake()
    tools = FakeTools(orders={"NC-100001": order("NC-100001")})
    r = run(ctx(message="فين طلبي {order_ref_1}", refs={"order_ref_1": "NC-100001"}), tools)
    assert shape(r) == [(0, "template", 1)] and f.calls == [] and tools.calls == ["order_details"]
    assert trace(ctx(message="فين طلبي", refs={}), FakeTools(recent=[summary("NC-100001", "Shirt")],
                                                                                orders={"NC-100001": order("NC-100001")})) \
        == ["classify", "safety_gate", "plan", "assemble"]


def test_a_p1_goes_to_the_handoff_with_no_tool_and_the_emergency_acknowledgement_first(fake):
    fake(classify_answer(cpart(None, safety="P1", p1_flag="takeover"), cpart("C1")))
    tools = FakeTools()
    r = run(ctx(message="someone hacked my account and I want to know my order"), tools)
    assert tools.calls == [] and shape(r) == [(-1, "template", 8)]        # the WHOLE result: the second part says nothing
    assert (r.handoff_reason, r.priority, r.block_session_data) == ("SAFE", "P1", True)
    fake(classify_answer(cpart(None, safety="P1", p1_flag="danger")))
    assert run(ctx(message="a man threatened me at the door"), FakeTools()).block_session_data is False
    fake(classify_answer(cpart(None, safety="P1", p1_flag="danger")))
    assert trace(ctx(message="a man threatened me"), FakeTools()) == ["classify", "safety_gate", "handoff", "assemble"]


def test_a_policy_question_goes_plan_then_reply_and_cites_its_sections(fake):
    chunk = {"cited": "POL-RET-001 §2@2.1", "text": "Returns are accepted within 30 days."}
    fake(classify_answer(cpart("C4", expl=True), english="return window"),
         {"segments": [{"part_index": 0, "text": "Within the window.", "cited": ["POL-RET-001 §2@2.1"]}]})
    r = run(ctx(message="what is the return window for a shirt"), FakeTools(chunks=[chunk]))
    assert shape(r) == [(0, "text", None)] and r.cited == ["POL-RET-001 §2@2.1"]
    fake(classify_answer(cpart("C4", expl=True), english="x"),
         {"segments": [{"part_index": 0, "text": "Within the window.", "cited": ["POL-RET-001 §2@2.1"]}]})
    assert trace(ctx(message="what is the return window for a shirt"), FakeTools(chunks=[chunk])) \
        == ["classify", "safety_gate", "plan", "reply", "assemble"]


def test_an_ambiguous_order_goes_to_clarify_and_the_question_lists_the_recent_orders(fake):
    fake(classify_answer(cpart("C1", item_clue="watch")))
    tools = FakeTools(recent=[summary("NC-100002", "Silver Watch"), summary("NC-100001", "Classic Watch")])
    r = run(ctx(message="where is my watch order today please"), tools)
    assert shape(r) == [(0, "clarify", None)] and "Silver Watch" in r.segments[0].render_values["choices_text"]
    assert r.handoff_reason is None
    fake(classify_answer(cpart("C1", item_clue="watch")))
    assert trace(ctx(message="where is my watch order today please"), tools) \
        == ["classify", "safety_gate", "plan", "clarify", "assemble"]


def test_the_third_clarification_round_ends_in_a_pending_owner_handoff(fake):
    fake(classify_answer(cpart("C1", item_clue="watch")))
    tools = FakeTools(recent=[summary("NC-100002", "Silver Watch"), summary("NC-100001", "Classic Watch")])
    r = run(ctx(message="where is my watch order today please", clarify_round=3), tools)
    assert r.handoff_reason == "PENDING_OWNER" and [s.kind for s in r.segments] == ["template"] and r.segments[0].template_id == 5
    fake(classify_answer(cpart("C1", item_clue="watch")))
    assert trace(ctx(message="where is my watch order today please", clarify_round=3), tools) \
        == ["classify", "safety_gate", "plan", "clarify", "handoff", "assemble"]


def test_a_classify_failure_never_reaches_the_plan_and_a_customer_gets_template_15(fake):
    fake(LLMResult("timeout", reason="deadline_exceeded"))
    tools = FakeTools()
    r = run(ctx(message="where is my order and why is it late"), tools)
    assert tools.calls == [] and shape(r) == [(0, "template", 15)] and r.handoff_reason is None
    fake(LLMResult("timeout", reason="deadline_exceeded"))
    assert trace(ctx(message="where is my order and why is it late"), FakeTools()) \
        == ["classify", "safety_gate", "classify_failed", "assemble"]       # no handoff: template 15 carries none


# ---------- the worker agent ----------
def test_the_worker_plain_message_uses_the_worker_graph_and_tools(fake):
    f = fake()
    tools = FakeTools()
    r = run(ctx("worker", "شحناتي النهارده"), tools)
    assert shape(r) == [(0, "template", 3)] and tools.calls == ["my_shipments_today"] and f.calls == []


def test_a_worker_classify_failure_is_template_6_with_a_pending_owner_handoff(fake):
    fake(LLMResult("unavailable", reason="x"))
    r = run(ctx("worker", "العنوان مش واضح"), FakeTools())
    assert (r.handoff_reason, r.priority) == ("PENDING_OWNER", None) and shape(r) == [(1, "template", 6)]


def test_the_worker_model_sees_the_worker_catalog_only(fake):
    f = fake(classify_answer())
    run(ctx("worker", "give me the address and phone for shipment S-700001"), FakeTools())
    assert "W1:" in f.calls[0]["system"] and "C1:" not in f.calls[0]["system"]


# ---------- the graphs as a whole ----------
def test_every_node_runs_at_most_once_on_every_path(fake):
    chunk = {"cited": "POL-RET-001 §2@2.1", "text": "t"}
    cases = [(CUSTOMER_AGENT, ctx(message="فين طلبي"), FakeTools(recent=[summary("NC-100001", "S")], orders={"NC-100001": order("NC-100001")}), None),
             (CUSTOMER_AGENT, ctx(message="a long message about a hacked account"), FakeTools(), classify_answer(cpart(None, "P1", "takeover"))),
             (CUSTOMER_AGENT, ctx(message="what is the return window"), FakeTools(chunks=[chunk]), None),
             (WORKER_AGENT, ctx("worker", "شحناتي"), FakeTools(), None)]
    for spec, context, tools, answer in cases:
        if answer:
            fake(answer)
        elif "return window" in context.message:
            fake(classify_answer(cpart("C4", expl=True), english="x"), {"segments": [{"part_index": 0, "text": "ok", "cited": ["POL-RET-001 §2@2.1"]}]})
        else:
            fake()
        nodes = trace(context, tools)
        assert len(nodes) == len(set(nodes)) and nodes[0] == "classify" and nodes[-1] == "assemble"


def test_the_result_is_plain_data_that_the_gateway_can_send(fake):
    import json
    fake()
    r = run(ctx(message="فين طلبي"), FakeTools(recent=[summary("NC-100001", "S")], orders={"NC-100001": order("NC-100001")}))
    json.dumps(asdict(r))


# ---------- the supervisor's rule, on its own ----------
from app.agent.state import Intent, Part, PartOutcome  # noqa: E402
from langgraph.graph import END  # noqa: E402


def _state(done, classify_ok=True, safety=None, outcomes=()):
    parts = [Part(index=i, safety="SAFE", intent=Intent(id="C1"), outcome=o) for i, o in enumerate(outcomes)]
    return AgentState(classify_ok=classify_ok, safety_flag=safety, parts=parts, stages_done=list(done))


@pytest.mark.parametrize("state, expected", [
    (_state([]), "worker_classify"),
    (_state(["classify"]), "worker_safety_gate"),
    (_state(["classify", "safety_gate"]), "planner"),                                          # a normal request goes to the planner
    (_state(["classify", "safety_gate"], safety="P1"), "worker_handoff"),                      # a P1 skips the planner
    (_state(["classify", "safety_gate"], classify_ok=False), "worker_classify_failed"),       # a failure skips the planner
    (_state(["classify", "safety_gate", "planner"], outcomes=[PartOutcome(kind="template", template_id=1)]), "worker_assemble"),
    (_state(["classify", "safety_gate", "planner"], outcomes=[PartOutcome(kind="reply")]), "worker_reply"),
    (_state(["classify", "safety_gate", "planner", "reply"], outcomes=[PartOutcome(kind="clarify", reason="r")]), "worker_clarify"),
    (_state(["classify", "safety_gate", "planner", "clarify"], outcomes=[PartOutcome(kind="handoff", handoff_reason="PENDING_OWNER")]), "worker_handoff"),
    (_state(["classify", "safety_gate", "planner", "handoff"], outcomes=[PartOutcome(kind="handoff", handoff_reason="CMP")]), "worker_assemble"),
    (_state(["classify", "safety_gate", "planner", "assemble"]), END),
])
def test_the_supervisor_rule(state, expected):
    assert decide_next(state) == expected


def test_the_supervisor_never_picks_a_worker_twice():
    for done in (["classify"], ["classify", "safety_gate", "planner", "reply", "clarify", "handoff"]):
        assert _worker_name_not_in(done)


def _worker_name_not_in(done):
    chosen = decide_next(_state(done, outcomes=[PartOutcome(kind="reply"), PartOutcome(kind="clarify", reason="r"),
                                                PartOutcome(kind="handoff", handoff_reason="CMP")]))
    stage = "planner" if chosen == "planner" else str(chosen).removeprefix("worker_")
    return stage not in done
