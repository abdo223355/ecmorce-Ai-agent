"""Cancellation eligibility (POL-CAN-001 v2.0): the rules as pure code, the plan row that uses them, and whole turns.
The verdict comes from the order's status and flags only, never from the customer's words; what the data cannot show is a review."""
import asyncio
import time
from datetime import datetime

import pytest

from app.agent import AgentContext, run_agent
from app.agent import pending as pend
from app.agent.plan import plan_node
from app.agent.state import AgentState, Intent, Part
from app.llm import client
from app.llm.fake import FakeAdapter
from app.rules import cancellation as rules
from app.schemas import BackendItem, OrderSummaryView, OrderView
from app.tools import ToolResult
from app.tools.customer import check_eligibility

NOW = datetime(2026, 11, 2, 12, 0)


def item(category="home", custom=False, pre=False, sale="none"):
    return BackendItem(item_id=1, name="Kitchen Knife Set", category=category, qty=1, sale_label=sale, custom_made=custom, pre_order=pre)


def order(status="Pending", *items, order_id="NC-100001"):
    return OrderView(order_id=order_id, order_date=NOW, status=status, delivered_at=NOW if status == "Delivered" else None,
                     items=list(items) or [item()], returns=[], last_updated=NOW)


# ---------- the rules ----------
@pytest.mark.parametrize("status,kind", [
    ("Pending", "eligible"), ("Confirmed", "eligible"), ("Processing", "review"),
    ("Packed", "not_eligible"), ("Shipped", "not_eligible"), ("Out for Delivery", "not_eligible"),
    ("Delivered", "return_instead"), ("Cancelled", "already_cancelled"), ("Failed Delivery", "review"),
])
def test_the_status_decides_as_the_policy_table_says(status, kind):
    v = rules.check_cancellation(order(status))
    assert (v.kind, v.reason) == (kind, status) and v.cited == "POL-CAN-001 §2@2.0"


@pytest.mark.parametrize("it,reason", [(item(custom=True), "custom_made"), (item(pre=True), "pre_order"), (item("gift_card"), "gift_card")])
@pytest.mark.parametrize("status", ["Pending", "Confirmed"])
def test_a_special_item_can_not_be_judged_from_the_data_so_a_person_decides(status, it, reason):
    v = rules.check_cancellation(order(status, item(), it))
    assert (v.kind, v.reason, v.cited) == ("review", reason, "POL-CAN-001 §4@2.0")


def test_special_items_do_not_change_a_status_that_is_already_a_no():
    assert rules.check_cancellation(order("Shipped", item(custom=True))).kind == "not_eligible"
    assert rules.check_cancellation(order("Delivered", item("gift_card"))).kind == "return_instead"


def test_an_unknown_status_is_a_review_never_a_guess():
    v = rules.check_cancellation(order("Pending").model_copy(update={"status": "Teleported"}))
    assert (v.kind, v.reason) == ("review", "unknown_status")


def test_every_verdict_has_words_in_both_languages_with_only_known_placeholders():
    import re
    known = {"order_id", "order_status", "window_hours"}
    for key in ("eligible", "not_eligible", "return_instead", "already_cancelled", "review_processing", "review_special", "review_other"):
        for lang in ("ar", "en"):
            text = rules.TEXTS[(key, lang)]
            assert set(re.findall(r"\{([a-z_]+)\}", text)) <= known and text


def test_the_tool_of_the_design_answers_for_cancel_and_not_yet_for_the_others():
    res = asyncio.run(check_eligibility("cancel", order("Confirmed")))
    assert res.ok and res.data.kind == "eligible"
    assert asyncio.run(check_eligibility("teleport", order("Delivered"))).status == "not_implemented"


# ---------- the plan row ----------
class FakeTools:
    def __init__(self, orders=None, recent=None):
        self.orders, self.recent, self.calls = orders or {}, recent or [], []

    async def my_recent_orders(self):
        self.calls.append("my_recent_orders")
        return ToolResult("ok", data=self.recent)

    async def order_details(self, order_id):
        self.calls.append(("order_details", order_id))
        got = self.orders.get(order_id)
        return ToolResult("ok", data=got) if got else ToolResult("denied", reason="not_found_or_not_yours")


def ctx(message="ينفع الغي الاوردر", refs=None, pending=None):
    return AgentContext(role="customer", message=message, chat_id="c:s", deadline_at=time.monotonic() + 8,
                        order_refs=refs or {}, pending=pending)


def run_plan(tools, message="ينفع الغي الاوردر", refs=None, **arguments):
    part = Part(index=0, safety="SAFE", intent=Intent(id="C9", arguments=arguments), needs_explanation=False)
    update = asyncio.run(plan_node(AgentState(parts=[part], classify_ok=True), ctx(message, refs), tools))
    return update["parts"][0].outcome


REFS = {"order_ref_1": "NC-100001"}


@pytest.mark.parametrize("status,starts,handoff", [
    ("Pending", "طلبك NC", None), ("Processing", "طلبك", "PENDING_OWNER"), ("Shipped", "طلبك", None),
    ("Delivered", "طلبك", None), ("Cancelled", "طلبك", None), ("Failed Delivery", "طلبك", "PENDING_OWNER"),
])
def test_the_plan_answers_with_code_chosen_words_and_hands_off_only_for_a_review(status, starts, handoff):
    tools = FakeTools(orders={"NC-100001": order(status)})
    o = run_plan(tools, refs=REFS, order_ref="order_ref_1")
    assert o.kind == "chat" and o.handoff_reason == handoff and o.cited[0].startswith("POL-CAN-001")
    assert o.render_values["order_id"] == "NC-100001" and o.render_values["order_status"] == status
    assert "{order_id}" in o.text and "NC-100001" not in o.text            # the real id only in render_values (D60-A1)
    assert tools.calls == [("order_details", "NC-100001")]


def test_processing_says_the_window_as_a_placeholder_filled_from_the_rule():
    o = run_plan(FakeTools(orders={"NC-100001": order("Processing")}), refs=REFS, order_ref="order_ref_1")
    assert "{window_hours}" in o.text and o.render_values["window_hours"] == "4"


def test_a_special_item_gives_the_special_words_and_a_handoff():
    tools = FakeTools(orders={"NC-100001": order("Confirmed", item(pre=True))})
    o = run_plan(tools, refs=REFS, order_ref="order_ref_1")
    assert o.handoff_reason == "PENDING_OWNER" and "حجز مسبق" in o.text and o.cited == ["POL-CAN-001 §4@2.0"]


def test_the_words_follow_the_language_of_the_message():
    tools = FakeTools(orders={"NC-100001": order("Pending")})
    o = run_plan(tools, message="can I cancel order NC-100001", refs=REFS, order_ref="order_ref_1")
    assert o.text.startswith("Your order {order_id} ({order_status}) can be cancelled")


def test_an_order_that_is_not_the_customers_is_not_found_not_a_verdict():
    o = run_plan(FakeTools(), refs={"order_ref_1": "NC-999999"}, order_ref="order_ref_1")
    assert o.kind == "template" and o.template_id == 14


def test_with_no_order_reference_and_several_orders_the_agent_asks_which_one():
    tools = FakeTools(recent=[OrderSummaryView(order_id=f"NC-10000{i}", order_date=NOW, status="Pending", product_names=["x"], last_updated=NOW)
                              for i in (1, 2)])
    o = run_plan(tools)
    assert (o.kind, o.reason) == ("clarify", "missing_order_id") and tools.calls == ["my_recent_orders"]


def test_with_one_order_only_it_is_the_one():
    tools = FakeTools(orders={"NC-100001": order("Shipped")},
                      recent=[OrderSummaryView(order_id="NC-100001", order_date=NOW, status="Shipped", product_names=["x"], last_updated=NOW)])
    o = run_plan(tools)
    assert o.kind == "chat" and o.render_values["order_status"] == "Shipped"


# ---------- whole turns ----------
@pytest.fixture
def fake():
    def install(*responses):
        f = FakeAdapter(*responses)
        client.set_adapter(f)
        return f
    yield install
    client.set_adapter(None)


def c9_answer(**args):
    return {"parts": [{"safety": "SAFE", "escalation_flags": [], "p1_flag": None, "intent_id": "C9", "needs_explanation": False,
                       "args": {"order_ref": None, "item_clue": None, "return_id": None, **args}}], "english_query": None}


def test_a_whole_turn_for_a_shipped_order_gives_the_refusal_and_no_handoff(fake):
    fake(c9_answer(order_ref="order_ref_1"))
    tools = FakeTools(orders={"NC-100001": order("Shipped")})
    r = asyncio.run(run_agent(ctx("can I cancel order NC-100001 now please, it is urgent", REFS), tools))
    assert [s.kind for s in r.segments] == ["text"] and r.handoff_reason is None
    assert r.segments[0].cited == ["POL-CAN-001 §2@2.0"] and r.segments[0].render_values["order_status"] == "Shipped"


def test_a_whole_turn_for_a_processing_order_gives_the_review_words_then_the_acknowledgement(fake):
    fake(c9_answer(order_ref="order_ref_1"))
    tools = FakeTools(orders={"NC-100001": order("Processing")})
    r = asyncio.run(run_agent(ctx("can I cancel order NC-100001 now please, it is urgent", REFS), tools))
    assert [(s.kind, s.template_id) for s in r.segments] == [("text", None), ("template", 5)]
    assert r.handoff_reason == "PENDING_OWNER" and r.priority is None


def test_which_order_then_the_answer_2_gives_the_verdict_for_the_second_order(fake):
    f = fake()
    tools = FakeTools(orders={"NC-100001": order("Pending", order_id="NC-100001"), "NC-100002": order("Shipped", order_id="NC-100002")},
                      recent=[OrderSummaryView(order_id=f"NC-10000{i}", order_date=NOW, status="Pending", product_names=[f"Item {i}"], last_updated=NOW)
                              for i in (1, 2)])
    f2 = fake(c9_answer())                                                     # turn 1: the model says C9 with no reference
    first = asyncio.run(run_agent(ctx("can I cancel my order please, it is urgent"), tools))
    pending = first.memory["pending"]
    assert [s.kind for s in first.segments] == ["clarify"] and pending["intent"] == "C9"
    second = asyncio.run(run_agent(ctx("2", refs=pend.order_refs_for(pending), pending=pending), tools))
    assert second.segments[0].render_values["order_id"] == "NC-100002" and second.segments[0].render_values["order_status"] == "Shipped"
    assert len(f2.calls) == 1                                                  # turn 2 needed no model call
