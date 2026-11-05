"""Return eligibility (POL-RET-001 v2.1): the rules as pure code (with a fixed "today"), the plan row, and whole turns.
The verdict comes from the order the backend gives, never from the customer's words; the condition of the item is told as the
policy's condition and never decided here."""
import asyncio
import re
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from app.agent import AgentContext, run_agent
from app.agent import pending as pend
from app.agent.clarify import clarify_node
from app.agent.plan import plan_node
from app.agent.state import AgentState, Intent, Part
from app.llm import client
from app.llm.fake import FakeAdapter
from app.rules import returns as rules
from app.schemas import BackendItem, OrderSummaryView, OrderView
from app.tools import ToolResult
from app.tools.customer import check_eligibility

TODAY = date(2026, 11, 4)


def item(name="Cotton Polo Shirt", category="apparel", custom=False, sale="none"):
    return BackendItem(item_id=1, name=name, category=category, qty=1, sale_label=sale, custom_made=custom, pre_order=False)


def delivered_on(day: date, hour=14, tz=timezone.utc):
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=tz)


def order(*items, status="Delivered", delivered=date(2026, 10, 25), order_id="NC-100001"):
    return OrderView(order_id=order_id, order_date=datetime(2026, 10, 1), status=status,
                     delivered_at=delivered_on(delivered) if delivered and status == "Delivered" else None,
                     items=list(items) or [item()], returns=[], last_updated=datetime(2026, 11, 1))


def verdict(*items, today=TODAY, **kw):
    return rules.check_return(order(*items, **kw), today=today)


# ---------- the window: the policy's own examples and the edges ----------
def test_a_jacket_delivered_20_days_ago_is_inside_the_30_day_window():
    v = verdict(item("Leather Jacket"), delivered=TODAY - timedelta(days=20))
    assert v.kind == "items" and (v.items[0].kind, v.items[0].reason) == ("eligible", "standard")
    assert v.items[0].last_day == TODAY - timedelta(days=20) + timedelta(days=30)


@pytest.mark.parametrize("days_ago,kind", [(0, "eligible"), (29, "eligible"), (30, "eligible"), (31, "expired")])
def test_day_30_is_the_last_day_and_day_31_is_too_late_for_standard_goods(days_ago, kind):
    assert verdict(delivered=TODAY - timedelta(days=days_ago)).items[0].kind == kind


@pytest.mark.parametrize("days_ago,kind,reason", [
    (14, "eligible", "electronics"), (15, "eligible", "electronics"),
    (16, "defective_only", "electronics_window"), (30, "defective_only", "electronics_window"), (31, "expired", "electronics"),
])
def test_electronics_have_15_days_then_only_a_defective_or_wrong_item_until_day_30(days_ago, kind, reason):
    v = verdict(item("JBL Tune 520BT", "electronics"), delivered=TODAY - timedelta(days=days_ago)).items[0]
    assert (v.kind, v.reason) == (kind, reason)


def test_the_window_counts_the_cairo_calendar_day_not_utc():
    # delivered 2026-10-05 at 22:30 UTC = 2026-10-06 01:30 Cairo (UTC+3 before the end of October): the Cairo day counts.
    late = OrderView(order_id="NC-100001", order_date=datetime(2026, 9, 1), status="Delivered", items=[item()], returns=[],
                     delivered_at=datetime(2026, 10, 5, 22, 30, tzinfo=timezone.utc), last_updated=datetime(2026, 10, 6))
    v = rules.check_return(late, today=date(2026, 11, 5))
    assert v.delivered_date == date(2026, 10, 6) and v.items[0].last_day == date(2026, 11, 5) and v.items[0].kind == "eligible"
    assert rules.check_return(late, today=date(2026, 11, 6)).items[0].kind == "expired"


def test_a_time_with_no_zone_is_taken_as_cairo_time():
    naive = OrderView(order_id="NC-1", order_date=datetime(2026, 9, 1), status="Delivered", items=[item()], returns=[],
                      delivered_at=datetime(2026, 10, 25, 23, 30), last_updated=datetime(2026, 10, 26))
    assert rules.check_return(naive, today=TODAY).delivered_date == date(2026, 10, 25)


def test_beauty_is_30_days_and_the_condition_is_sealed_and_unopened():
    v = verdict(item("Argan Oil Shampoo", "beauty"), delivered=TODAY - timedelta(days=14)).items[0]
    assert (v.kind, v.reason) == ("eligible", "beauty")


# ---------- items that are not returnable for a change of mind ----------
@pytest.mark.parametrize("it,reason", [(item(custom=True), "custom_made"), (item(sale="final_sale"), "final_sale"), (item(sale="clearance"), "final_sale")])
def test_custom_made_and_final_sale_are_returnable_only_if_defective_within_30_days(it, reason):
    v = verdict(it, delivered=TODAY - timedelta(days=10)).items[0]
    assert (v.kind, v.reason) == ("defective_only", reason) and v.last_day == TODAY - timedelta(days=10) + timedelta(days=30)
    assert verdict(it, delivered=TODAY - timedelta(days=40)).items[0].kind == "expired"


def test_the_policys_clearance_sandals_example_is_not_eligible_for_a_change_of_mind():
    assert verdict(item("Sandals", "apparel", sale="clearance")).items[0].kind == "defective_only"


def test_a_gift_card_is_never_returnable():
    v = verdict(item("NovaCart Gift Card 500 EGP", "gift_card")).items[0]
    assert (v.kind, v.reason, v.last_day) == ("not_returnable", "gift_card", None)


def test_an_unknown_category_is_a_review_never_a_guess():
    v = verdict(item("Mystery", "furniture")).items[0]
    assert (v.kind, v.reason) == ("review", "unknown_category") and rules.needs_person(verdict(item("Mystery", "furniture")))


# ---------- the holiday extension ----------
@pytest.mark.parametrize("delivered,today,kind", [
    (date(2026, 11, 15), date(2027, 1, 31), "eligible"), (date(2026, 11, 15), date(2027, 2, 1), "expired"),
    (date(2026, 12, 31), date(2027, 1, 31), "eligible"), (date(2026, 11, 14), date(2026, 12, 20), "expired"),
])
def test_orders_delivered_from_nov_15_to_dec_31_may_be_returned_until_jan_31(delivered, today, kind):
    assert verdict(delivered=delivered, today=today).items[0].kind == kind


def test_the_longer_of_the_two_windows_applies_and_the_holiday_section_is_cited():
    v = verdict(item("JBL", "electronics"), delivered=date(2026, 11, 20), today=date(2027, 1, 20))
    assert v.items[0].kind == "eligible" and v.items[0].last_day == date(2027, 1, 31)
    assert "§9" in v.sections and "§9" not in verdict().sections


# ---------- the order itself ----------
@pytest.mark.parametrize("status", ["Pending", "Confirmed", "Processing", "Packed", "Shipped", "Out for Delivery", "Cancelled"])
def test_an_order_that_is_not_delivered_can_not_be_returned_yet(status):
    v = rules.check_return(order(status=status), today=TODAY)
    assert (v.kind, v.reason, v.items) == ("not_delivered", status, ()) and v.cited == ["POL-RET-001 §3@2.1"]


def test_failed_delivery_and_a_missing_delivery_date_are_a_review():
    assert rules.check_return(order(status="Failed Delivery"), today=TODAY).kind == "review"
    undated = order().model_copy(update={"delivered_at": None})
    v = rules.check_return(undated, today=TODAY)
    assert (v.kind, v.reason) == ("review", "delivered_without_date") and rules.needs_person(v)


def test_an_item_clue_narrows_the_answer_to_that_item_only_when_exactly_one_matches():
    items = [item("Silver Watch", "apparel"), item("Red Shirt", "apparel")]
    assert [i.name for i in rules.check_return(order(*items), "watch", TODAY).items] == ["Silver Watch"]
    assert len(rules.check_return(order(*items), "pizza", TODAY).items) == 2
    assert len(rules.check_return(order(*items), "s", TODAY).items) == 2          # "s" matches both: no guess


def test_the_sections_cited_follow_what_was_used():
    assert verdict(delivered=TODAY - timedelta(days=5)).sections == ("§2",)
    assert verdict(item("JBL", "electronics"), delivered=TODAY - timedelta(days=5)).sections == ("§2", "§5")
    assert verdict(item(custom=True)).sections == ("§2", "§5")


def test_the_tool_of_the_design_answers_for_return():
    res = asyncio.run(check_eligibility("return", order(delivered=date.today() - timedelta(days=3))))
    assert res.ok and res.data.kind == "items"


def test_every_wording_exists_in_both_languages_with_known_placeholders_only():
    known = {"order_id", "order_status", "delivered_date", "electronics_days"}
    for table in rules.HEADER.values():
        for text in table.values():
            assert set(re.findall(r"\{([a-z_0-9]+)\}", text)) <= known
    for entry in rules.LINE.values():
        for lang, text in entry.items():
            shaped = text.format(i=1)
            assert set(re.findall(r"\{([a-z_0-9]+)\}", shaped)) <= known | {"i1_name", "i1_end_date", "i1_defect_date"}
    assert set(rules.FOOTER) == {"ar", "en"}


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


def ctx(message="ينفع ارجع المنتج", refs=None, pending=None):
    return AgentContext(role="customer", message=message, chat_id="c:s", deadline_at=time.monotonic() + 8,
                        order_refs=refs or {}, pending=pending)


def summary(i, status="Delivered", name="Item"):
    return OrderSummaryView(order_id=f"NC-10000{i}", order_date=datetime(2026, 10, 1), status=status, product_names=[f"{name} {i}"],
                            last_updated=datetime(2026, 11, 1))


def run_plan(tools, message="ينفع ارجع المنتج", refs=None, **arguments):
    part = Part(index=0, safety="SAFE", intent=Intent(id="C2", arguments=arguments), needs_explanation=False)
    update = asyncio.run(plan_node(AgentState(parts=[part], classify_ok=True), ctx(message, refs), tools))
    return update["parts"][0].outcome


REFS = {"order_ref_1": "NC-100001"}
RECENT_DELIVERED = date.today() - timedelta(days=5)


def test_the_plan_answers_with_code_chosen_words_and_real_values_only_in_render_values():
    tools = FakeTools(orders={"NC-100001": order(item("Cotton Polo Shirt"), delivered=RECENT_DELIVERED)})
    o = run_plan(tools, refs=REFS, order_ref="order_ref_1")
    assert o.kind == "chat" and o.handoff_reason is None and o.cited == ["POL-RET-001 §2@2.1"]
    assert "{i1_name}" in o.text and "{i1_end_date}" in o.text and "{delivered_date}" in o.text
    assert o.render_values["i1_name"] == "Cotton Polo Shirt" and o.render_values["order_id"] == "NC-100001"
    assert o.render_values["delivered_date"] == RECENT_DELIVERED.isoformat() and "NC-100001" not in o.text
    assert tools.calls == [("order_details", "NC-100001")]


def test_an_order_with_several_items_gets_a_line_for_each_and_no_question():
    items = [item("Silver Watch", "electronics"), item("Red Shirt", "apparel"), item("Gift", "gift_card")]
    tools = FakeTools(orders={"NC-100001": order(*items, delivered=RECENT_DELIVERED)})
    o = run_plan(tools, refs=REFS, order_ref="order_ref_1")
    assert o.kind == "chat" and [o.render_values[f"i{n}_name"] for n in (1, 2, 3)] == ["Silver Watch", "Red Shirt", "Gift"]
    assert "electronics_days" in o.render_values and o.render_values["electronics_days"] == "15"
    assert "i3_end_date" not in o.render_values and "i1_defect_date" in o.render_values


def test_an_item_clue_picks_the_order_and_the_item():
    tools = FakeTools(orders={"NC-100001": order(item("Silver Watch"), item("Red Shirt"), delivered=RECENT_DELIVERED)},
                      recent=[summary(1, name="Silver Watch")])
    o = run_plan(tools, item_clue="watch")
    assert o.kind == "chat" and o.render_values["i1_name"] == "Silver Watch" and "i2_name" not in o.render_values


def test_a_review_verdict_hands_off_and_a_not_delivered_order_does_not():
    shipped = run_plan(FakeTools(orders={"NC-100001": order(status="Shipped")}), refs=REFS, order_ref="order_ref_1")
    assert shipped.handoff_reason is None and "{order_status}" in shipped.text
    failed = run_plan(FakeTools(orders={"NC-100001": order(status="Failed Delivery")}), refs=REFS, order_ref="order_ref_1")
    assert failed.handoff_reason == "PENDING_OWNER"
    odd = run_plan(FakeTools(orders={"NC-100001": order(item("X", "furniture"), delivered=RECENT_DELIVERED)}), refs=REFS, order_ref="order_ref_1")
    assert odd.handoff_reason == "PENDING_OWNER"


def test_the_words_follow_the_language_of_the_message():
    tools = FakeTools(orders={"NC-100001": order(delivered=RECENT_DELIVERED)})
    o = run_plan(tools, message="can I return order NC-100001", refs=REFS, order_ref="order_ref_1")
    assert o.text.startswith("Your order {order_id} was delivered on {delivered_date}")


def test_with_one_delivered_order_it_is_the_one_and_with_several_the_agent_asks_listing_only_delivered_orders():
    recent = [summary(1, "Shipped"), summary(2), summary(3, "Processing"), summary(4)]
    tools = FakeTools(recent=recent)
    o = run_plan(tools)
    assert (o.kind, o.reason) == ("clarify", "missing_order_id")
    state = AgentState(parts=[Part(index=0, safety="SAFE", intent=Intent(id="C2"), outcome=o)],
                       tool_results=[__import__("app.agent.state", fromlist=["ToolRecord"]).ToolRecord(tool="my_recent_orders", result=ToolResult("ok", data=recent))])
    asked = clarify_node(state, ctx())
    assert asked["pending"]["intent"] == "C2" and [c["ref"] for c in asked["pending"]["choices"]] == ["NC-100002", "NC-100004"]
    only = FakeTools(orders={"NC-100002": order(delivered=RECENT_DELIVERED, order_id="NC-100002")}, recent=[summary(1, "Shipped"), summary(2)])
    assert run_plan(only).render_values["order_id"] == "NC-100002"


def test_an_order_that_is_not_the_customers_is_not_found():
    o = run_plan(FakeTools(), refs={"order_ref_1": "NC-999999"}, order_ref="order_ref_1")
    assert o.kind == "template" and o.template_id == 14


# ---------- whole turns ----------
@pytest.fixture
def fake():
    def install(*responses):
        f = FakeAdapter(*responses)
        client.set_adapter(f)
        return f
    yield install
    client.set_adapter(None)


def c2_answer(**args):
    return {"parts": [{"safety": "SAFE", "escalation_flags": [], "p1_flag": None, "intent_id": "C2", "needs_explanation": False,
                       "args": {"order_ref": None, "item_clue": None, "return_id": None, **args}}], "english_query": None}


def test_a_whole_turn_gives_a_text_with_its_citations_and_no_handoff_when_it_is_decided(fake):
    fake(c2_answer(order_ref="order_ref_1"))
    tools = FakeTools(orders={"NC-100001": order(delivered=RECENT_DELIVERED)})
    r = asyncio.run(run_agent(ctx("can I return order NC-100001 please, it does not fit me", REFS), tools))
    assert [s.kind for s in r.segments] == ["text"] and r.handoff_reason is None and r.segments[0].cited == ["POL-RET-001 §2@2.1"]


def test_a_whole_turn_with_a_review_ends_with_the_acknowledgement(fake):
    fake(c2_answer(order_ref="order_ref_1"))
    tools = FakeTools(orders={"NC-100001": order(status="Failed Delivery")})
    r = asyncio.run(run_agent(ctx("can I return order NC-100001 please, it does not fit me", REFS), tools))
    assert [(s.kind, s.template_id) for s in r.segments] == [("text", None), ("template", 5)] and r.handoff_reason == "PENDING_OWNER"


def test_which_order_then_the_answer_2_gives_the_return_verdict_for_the_second_delivered_order(fake):
    fake(c2_answer())
    recent = [summary(1, "Shipped"), summary(2), summary(4)]
    tools = FakeTools(orders={"NC-100002": order(item("Two"), delivered=RECENT_DELIVERED, order_id="NC-100002"),
                              "NC-100004": order(item("Four"), delivered=RECENT_DELIVERED, order_id="NC-100004")}, recent=recent)
    first = asyncio.run(run_agent(ctx("can I return something please, it does not fit"), tools))
    pending = first.memory["pending"]
    assert [s.kind for s in first.segments] == ["clarify"] and [c["ref"] for c in pending["choices"]] == ["NC-100002", "NC-100004"]
    second = asyncio.run(run_agent(ctx("2", refs=pend.order_refs_for(pending), pending=pending), tools))
    assert second.segments[0].render_values["order_id"] == "NC-100004" and second.segments[0].render_values["i1_name"] == "Four"
