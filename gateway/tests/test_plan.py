"""Node 3 (plan), slice 1: C1, C3, W1, W2, W3. A fake Tools object counts every call; no network, no model."""
import asyncio
import time
from datetime import date, datetime

import pytest

from app.agent import AgentContext
from app.agent.plan import ALLOWED_TOOLS, plan_node
from app.agent.plan_rows import HANDOFF_ROWS, PLANS, RAG_ROWS, ROWS
from app.agent.plan_spec import FanOutStep, FromResult, SELECTORS, BUILDERS, ToolStep
from app.agent.state import AgentState, Intent, Part
from app.schemas import BackendReturn, OrderSummaryView, OrderView, ShipmentView, TodayView
from app.tools import ToolResult

NOW = datetime(2026, 10, 20, 12, 0)


def summary(order_id, *names, status="Shipped"):
    return OrderSummaryView(order_id=order_id, order_date=NOW, status=status, product_names=list(names), last_updated=NOW)


def order(order_id, *returns, status="Shipped"):
    return OrderView(order_id=order_id, order_date=NOW, status=status, delivered_at=None, items=[],
                     returns=list(returns), last_updated=NOW)


def ret(return_id, status="Requested"):
    return BackendReturn(return_id=return_id, status=status, created_at=NOW, last_updated=NOW, item="Watch")


class FakeTools:
    def __init__(self, recent=None, orders=None, today=None, shipment=None, raises=None, returns=None):
        self.recent, self.orders, self.today, self.shipment, self.raises = recent, orders or {}, today, shipment, raises
        self.returns = returns
        self.calls = []

    async def my_returns(self):
        self.calls.append(("my_returns",))
        if self.raises:
            raise self.raises
        return self.returns if isinstance(self.returns, ToolResult) else ToolResult("ok", data=self.returns or [])

    async def my_recent_orders(self):
        self.calls.append(("my_recent_orders",))
        if self.raises:
            raise self.raises
        return self.recent if isinstance(self.recent, ToolResult) else ToolResult("ok", data=self.recent or [])

    async def order_details(self, order_id):
        self.calls.append(("order_details", order_id))
        got = self.orders.get(order_id, ToolResult("denied", reason="not_found_or_not_yours"))
        return got if isinstance(got, ToolResult) else ToolResult("ok", data=got)

    async def my_shipments_today(self, query):
        self.calls.append(("my_shipments_today", query))
        return self.today or ToolResult("ok", data=TodayView(query=query, date=date(2026, 10, 20), count=0, rows=[]))

    async def shipment_details(self, shipment_id, requested_fields):
        self.calls.append(("shipment_details", shipment_id, list(requested_fields)))
        return self.shipment or ToolResult("denied", reason="not_found_or_not_yours")


def ctx(role="customer", refs=None):
    return AgentContext(role=role, message="x", chat_id="c:s", deadline_at=time.monotonic() + 8,
                        order_refs=refs or {})


def part(index, intent_id, explain=False, **arguments):
    return Part(index=index, safety="SAFE", intent=Intent(id=intent_id, arguments=arguments), needs_explanation=explain)


def plan(tools, parts, role="customer", refs=None):
    state = AgentState(classify_ok=True, parts=parts)
    update = asyncio.run(plan_node(state, ctx(role, refs), tools))
    return update


def outcome(update, index=0):
    return update["parts"][index].outcome


REFS = {"order_ref_1": "NC-100001"}


# ---------- C1 ----------
def test_c1_with_a_reference_uses_the_real_id_and_the_fast_path_template():
    tools = FakeTools(orders={"NC-100001": order("NC-100001")})
    u = plan(tools, [part(0, "C1", order_ref="order_ref_1")], refs=REFS)
    assert tools.calls == [("order_details", "NC-100001")]               # the real id, never the placeholder
    o = outcome(u)
    assert (o.kind, o.template_id) == ("template", 1) and o.render_values["order_status"] == "Shipped"
    assert [(r.tool, r.argument) for r in u["tool_results"]] == [("order_details", "NC-100001")]


def test_c1_that_asks_why_goes_to_the_reply_not_the_template():
    tools = FakeTools(orders={"NC-100001": order("NC-100001")})
    o = outcome(plan(tools, [part(0, "C1", explain=True, order_ref="order_ref_1")], refs=REFS))
    assert o.kind == "reply" and o.render_values["order_status"] == "Shipped"
    assert o.template_id == 1                                            # kept as the fallback if the reply fails


def test_c1_finds_the_order_by_an_item_clue():
    tools = FakeTools(recent=[summary("NC-100001", "Red Shirt"), summary("NC-100002", "Silver Watch")],
                      orders={"NC-100002": order("NC-100002")})
    o = outcome(plan(tools, [part(0, "C1", item_clue="watch")]))
    assert tools.calls == [("my_recent_orders",), ("order_details", "NC-100002")] and o.template_id == 1


def test_c1_asks_when_the_clue_matches_none_or_several():
    for recent in ([summary("NC-100001", "Red Shirt")], [summary("NC-100001", "Watch A"), summary("NC-100002", "Watch B")]):
        tools = FakeTools(recent=recent)
        o = outcome(plan(tools, [part(0, "C1", item_clue="watch")]))
        assert (o.kind, o.reason) == ("clarify", "missing_order_id")
        assert tools.calls == [("my_recent_orders",)]                    # no order_details without a chosen order


def test_c1_with_no_arguments_and_one_order_answers_it_from_the_list_without_order_details():
    tools = FakeTools(recent=[summary("NC-100001", "Shirt", status="Delivered")])
    o = outcome(plan(tools, [part(0, "C1")]))
    assert o.template_id == 1 and o.render_values["order_id"] == "NC-100001"
    assert tools.calls == [("my_recent_orders",)]                        # one call, no order_details


def test_c1_with_no_arguments_and_one_order_on_the_way_answers_that_one():
    tools = FakeTools(recent=[summary("NC-100001", "Shirt", status="Delivered"), summary("NC-100002", "Hat", status="Out for Delivery"),
                              summary("NC-100003", "Cap", status="Processing")])
    o = outcome(plan(tools, [part(0, "C1")]))
    assert (o.template_id, o.render_values["order_id"], o.render_values["order_status"]) == (1, "NC-100002", "Out for Delivery")
    assert tools.calls == [("my_recent_orders",)]


def test_c1_with_several_orders_on_the_way_lists_them_with_no_question_and_real_values_only_in_render_values():
    tools = FakeTools(recent=[summary("NC-100001", "Shirt", status="Shipped"), summary("NC-100002", "Hat", "Cap", status="Out for Delivery"),
                              summary("NC-100003", "Bag", status="Packed")])
    o = outcome(plan(tools, [part(0, "C1")]))
    assert o.kind == "chat" and o.render_values["count"] == "2" and "{o1_product}" in o.text and "{o2_status}" in o.text
    assert o.render_values["o1_id"] == "NC-100001" and o.render_values["o2_product"] == "Hat, Cap"
    assert "NC-100001" not in o.text and "Shirt" not in o.text and "{o3_id}" not in o.text      # the Packed order is not listed
    assert "{count}" in o.text and tools.calls == [("my_recent_orders",)]


def test_c1_list_follows_the_language_of_the_message_and_never_lists_more_than_five():
    from app.agent.plan_registry import MAX_LISTED
    recent = [summary(f"NC-10000{i}", f"Item {i}", status="Shipped") for i in range(1, 9)]
    ar = outcome(plan(FakeTools(recent=recent), [part(0, "C1")]))
    assert ar.text.startswith("{count}") is False and "\u0639\u0646\u062f\u0643" in ar.text and ar.render_values["count"] == "8"
    assert len([k for k in ar.render_values if k.endswith("_id")]) == MAX_LISTED


def test_c1_with_no_orders_on_the_way_and_several_recent_orders_asks_for_the_number():
    tools = FakeTools(recent=[summary("NC-100001", "Shirt", status="Delivered"), summary("NC-100002", "Hat", status="Processing")])
    o = outcome(plan(tools, [part(0, "C1")]))
    assert (o.kind, o.reason) == ("clarify", "missing_order_id")
    assert outcome(plan(FakeTools(recent=[]), [part(0, "C1")])).kind == "clarify"

def test_c1_denied_is_template_14_and_nothing_else_is_recorded():
    tools = FakeTools()                                                  # the order is not found
    u = plan(tools, [part(0, "C1", order_ref="order_ref_1")], refs=REFS)
    assert (outcome(u).kind, outcome(u).template_id) == ("template", 14)
    assert "handoff_reason" not in u


def test_c1_backend_down_is_template_11_with_a_bkd_handoff():
    tools = FakeTools(orders={"NC-100001": ToolResult("unavailable", reason="backend_unavailable")})
    u = plan(tools, [part(0, "C1", order_ref="order_ref_1")], refs=REFS)
    o = outcome(u)
    assert (o.template_id, o.handoff_reason, o.priority) == (11, "BKD", "P3")
    assert "handoff_reason" not in u                                     # the final handoff is the handoff node's job


def test_c1_data_issue_ignores_the_data_that_came_with_it():
    bad = ToolResult("data_issue", data=order("NC-100001"), reason="status_conflict")
    o = outcome(plan(FakeTools(orders={"NC-100001": bad}), [part(0, "C1", order_ref="order_ref_1")], refs=REFS))
    assert o.template_id == 11 and o.render_values == {}


def test_a_reference_that_is_not_in_the_map_counts_as_absent_and_the_recent_orders_are_fetched():
    tools = FakeTools(recent=[summary("NC-100001", "Shirt", status="Delivered"), summary("NC-100002", "Hat", status="Delivered")])
    u = plan(tools, [part(0, "C1", order_ref="order_ref_9")], refs=REFS)
    o = outcome(u)
    assert (o.kind, o.reason) == ("clarify", "missing_order_id")
    assert tools.calls == [("my_recent_orders",)]                        # the list exists for the question to show
    assert [r.tool for r in u["tool_results"]] == ["my_recent_orders"]
    # with exactly one recent order the plan simply answers
    tools = FakeTools(recent=[summary("NC-100001", "Shirt")], orders={"NC-100001": order("NC-100001")})
    assert outcome(plan(tools, [part(0, "C1", order_ref="order_ref_9")], refs=REFS)).template_id == 1


# ---------- C3 ----------
def row(return_id, status="Requested", order_id="NC-100001"):
    from app.schemas import BackendReturnRow
    return BackendReturnRow(return_id=return_id, order_id=order_id, status=status, created_at=NOW, last_updated=NOW, item="Watch")


def test_c3_reads_the_customers_own_list_of_returns_in_one_call():
    tools = FakeTools(returns=[row("RT-500002", "Refunded", "NC-100009"), row("RT-500001", "Approved")])
    o = outcome(plan(tools, [part(0, "C3", return_id="rt-500001")]))
    assert (o.template_id, o.render_values["return_status"]) == (2, "Approved")
    assert tools.calls == [("my_returns",)]                        # no walk through the orders any more


def test_c3_finds_a_return_that_is_not_on_a_recent_order():
    tools = FakeTools(recent=[summary("NC-100001")], orders={"NC-100001": order("NC-100001")},
                      returns=[row("RT-500009", "Received", "NC-100099")])
    o = outcome(plan(tools, [part(0, "C3")]))
    assert (o.template_id, o.render_values["return_status"]) == (2, "Received")


def test_c3_with_an_order_reference_reads_that_order_only():
    tools = FakeTools(orders={"NC-100001": order("NC-100001", ret("RT-500001"))})
    o = outcome(plan(tools, [part(0, "C3", order_ref="order_ref_1")], refs=REFS))
    assert tools.calls == [("order_details", "NC-100001")] and o.template_id == 2


def test_c3_not_found_and_ambiguous_cases():
    assert outcome(plan(FakeTools(returns=[]), [part(0, "C3")])).template_id == 14           # really no return
    assert outcome(plan(FakeTools(returns=[row("RT-500001")]), [part(0, "C3", return_id="RT-999999")])).template_id == 14
    tools = FakeTools(returns=[row("RT-500001"), row("RT-500002")])
    o = outcome(plan(tools, [part(0, "C3")]))
    assert (o.kind, o.reason) == ("clarify", "which_return")


def test_c3_a_failing_list_maps_the_failure():
    assert outcome(plan(FakeTools(returns=ToolResult("unavailable")), [part(0, "C3")])).template_id == 11


# ---------- worker ----------
def test_w1_defaults_to_the_list_and_passes_the_query_type():
    tools = FakeTools()
    o = outcome(plan(tools, [part(0, "W1")], "worker"))
    assert tools.calls == [("my_shipments_today", "list")] and (o.kind, o.template_id) == ("template", 3)
    assert o.render_values["count"] == "0"
    tools = FakeTools()
    plan(tools, [part(0, "W1", query_type="pending")], "worker")
    assert tools.calls == [("my_shipments_today", "pending")]


def test_w2_passes_the_fields_and_sends_the_data_to_the_reply():
    sh = ToolResult("ok", data=ShipmentView(shipment_id="S-700001", order_id="NC-100001", status="Shipped",
                                           fields={"address": "x"}))
    tools = FakeTools(shipment=sh)
    o = outcome(plan(tools, [part(0, "W2", shipment_id="S-700001", requested_fields=["address"])], "worker"))
    assert tools.calls == [("shipment_details", "S-700001", ["address"])] and o.kind == "reply"
    assert o.template_id is None                                         # W2 has no template: nothing to fall back to


def test_w2_without_a_shipment_id_asks():
    tools = FakeTools()
    o = outcome(plan(tools, [part(0, "W2")], "worker"))
    assert (o.kind, o.reason) == ("clarify", "missing_argument") and tools.calls == []


def test_w3_always_asks_for_the_scheduled_date():
    tools = FakeTools()
    plan(tools, [part(0, "W3", shipment_id="S-700001")], "worker")
    assert tools.calls == [("shipment_details", "S-700001", ["scheduled_delivery_date"])]


@pytest.mark.parametrize("result, template", [
    (ToolResult("denied", reason="field_not_allowed"), 17),
    (ToolResult("denied", reason="not_found_or_not_yours"), 16),
    (ToolResult("ok", data=ShipmentView(shipment_id="S-700001", order_id="NC-1", status="Delivered", fields={},
                                        window_closed=True), reason="access_window_closed"), 17),
])
def test_worker_denials_and_a_closed_window_have_their_own_templates(result, template):
    o = outcome(plan(FakeTools(shipment=result), [part(0, "W2", shipment_id="S-700001")], "worker"))
    assert (o.kind, o.template_id) == ("template", template)


# ---------- the node as a whole ----------
def test_two_parts_asking_the_same_thing_share_one_call():
    tools = FakeTools(orders={"NC-100001": order("NC-100001")})
    u = plan(tools, [part(0, "C1", order_ref="order_ref_1"), part(1, "C1", order_ref="order_ref_1")], refs=REFS)
    assert tools.calls == [("order_details", "NC-100001")] and len(u["tool_results"]) == 1
    assert outcome(u, 0).template_id == outcome(u, 1).template_id == 1


def test_parts_can_end_differently():
    tools = FakeTools(orders={"NC-100001": order("NC-100001")})
    u = plan(tools, [part(0, "C1", order_ref="order_ref_1"), part(1, "C1", order_ref="order_ref_2")],
             refs={**REFS, "order_ref_2": "NC-100002"})
    assert (outcome(u, 0).template_id, outcome(u, 1).template_id) == (1, 14)


def test_a_tool_that_raises_becomes_unavailable():
    tools = FakeTools(raises=RuntimeError("boom"), recent=[])
    o = outcome(plan(tools, [part(0, "C1", item_clue="watch")]))
    assert o.template_id == 11 and o.handoff_reason == "BKD"


def test_intents_without_a_row_and_parts_without_an_intent_are_left_alone():
    tools = FakeTools()
    parts = [part(0, "C99"), Part(index=1, safety="SAFE")]
    u = plan(tools, parts)
    assert [p.outcome for p in u["parts"]] == [None, None] and tools.calls == []


def test_the_state_it_reads_is_not_changed():
    state = AgentState(classify_ok=True, parts=[part(0, "C1", order_ref="order_ref_1")])
    before = state.model_dump()
    asyncio.run(plan_node(state, ctx(refs=REFS), FakeTools()))
    assert state.model_dump() == before


# ---------- the table itself ----------
def test_every_row_names_only_things_that_exist():
    assert {(r.role, r.intent_id) for r in ROWS} == {("customer", "C1"), ("customer", "C2"), ("customer", "C3"), ("customer", "C5"), ("customer", "C9"), ("worker", "W1"),
                                                      ("worker", "W2"), ("worker", "W3")}
    assert {(r.role, r.intent_id) for r in HANDOFF_ROWS} == {
        ("customer", "C6"), ("customer", "C7"), ("customer", "C8"), ("customer", "C10"), ("customer", "C12"),
        ("customer", "C13"), ("customer", "C11"),
        ("worker", "W4"), ("worker", "W5"), ("worker", "W6"), ("worker", "W7"), ("worker", "W9")}
    assert {(r.role, r.intent_id) for r in RAG_ROWS} == {("customer", "C4"), ("worker", "W8"), ("customer", "C14")}
    for row in ROWS + HANDOFF_ROWS + RAG_ROWS:
        assert row.builder is None or row.builder in BUILDERS
        for template in (row.template_id, row.not_found_template):
            assert template is None or 1 <= template <= 19
        for branch in row.branches:
            for step in branch.steps:
                assert step.tool in ALLOWED_TOOLS
                if isinstance(step, FanOutStep):
                    assert step.over in SELECTORS
                if isinstance(step, ToolStep):
                    for _, source in step.args:
                        assert not isinstance(source, FromResult) or source.selector in SELECTORS
    assert PLANS["customer"]["C1"] is next(r for r in ROWS if r.intent_id == "C1")


def test_every_intent_of_both_roles_has_a_row_so_no_part_ends_as_could_not_finish():
    from app.agent.classify import CUSTOMER, WORKER
    assert set(PLANS["customer"]) == set(CUSTOMER.intents) and set(PLANS["worker"]) == set(WORKER.intents)


@pytest.mark.parametrize("role,intent,template", [("customer", i, 5) for i in ("C11",)]
                         + [("worker", i, 6) for i in ("W6", "W7")])
def test_the_intents_without_a_decision_yet_hand_off_honestly_and_call_no_tool(role, intent, template):
    tools = FakeTools()
    o = outcome(plan(tools, [part(0, intent)], role=role))
    assert o.template_id == template and o.handoff_reason == "PENDING_OWNER" and o.priority is None
    assert tools.calls == []


# ---------- privacy (D60-A1): what the reply LLM may see ----------
PERSONAL = ["NC-100001", "RT-500001", "Sara Ali", "01012345678", "12 Nile St", "S-700001", "250.00"]


def _scenarios():
    today = ToolResult("ok", data=TodayView(query="list", date=date(2026, 10, 20), count=1, rows=[
        {"order_id": "NC-100001", "customer_name": "Sara Ali", "customer_phone": "01012345678",
         "address": "12 Nile St"}]))
    return [
        ("customer", FakeTools(orders={"NC-100001": order("NC-100001", ret("RT-500001", "Approved"))}),
         part(0, "C1", explain=True, order_ref="order_ref_1")),
        ("customer", FakeTools(orders={"NC-100001": order("NC-100001", ret("RT-500001", "Approved"))}),
         part(0, "C3", explain=True, order_ref="order_ref_1")),
        ("worker", FakeTools(today=today), part(0, "W1", explain=True)),
    ]


@pytest.mark.parametrize("role, tools, p", _scenarios())
def test_the_llm_never_sees_a_personal_value_only_typed_placeholders(role, tools, p):
    o = outcome(plan(tools, [p], role, REFS))
    assert o.kind == "reply" and o.llm_facts
    seen = " ".join(o.llm_facts.values())
    assert not any(value in seen for value in PERSONAL)
    # the real values are still there for code to render
    assert any(value in " ".join(o.render_values.values()) for value in PERSONAL)
    for key in ("order_id", "return_id", "rows_text", "count", "date", "last_updated"):
        if key in o.llm_facts:
            assert o.llm_facts[key] == "{" + key + "}"          # a number, date or personal value is a placeholder


def test_a_template_outcome_carries_no_llm_facts():
    tools = FakeTools(orders={"NC-100001": order("NC-100001")})
    o = outcome(plan(tools, [part(0, "C1", order_ref="order_ref_1")], refs=REFS))
    assert o.kind == "template" and o.llm_facts == {} and o.render_values["order_id"] == "NC-100001"


def test_fixed_outcomes_have_nothing_for_the_llm():
    assert outcome(plan(FakeTools(), [part(0, "C13")])).llm_facts == {}
