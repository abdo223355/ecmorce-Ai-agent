"""Exchange eligibility (POL-EXC-001 v1.1): the rules as pure code (with a fixed "today"), the plan row, and whole turns.
An exchange is not a return. The verdict comes from the order the backend gives; the replacement's stock, the "same product"
condition and whether an item is defective or wrong are told as the policy's conditions and never decided here."""
import asyncio
import re
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from app.agent import AgentContext, run_agent
from app.agent import pending as pend
from app.agent.plan import plan_node
from app.agent.state import AgentState, Intent, Part
from app.llm import client
from app.llm.fake import FakeAdapter
from app.rules import exchange as rules
from app.schemas import BackendItem, OrderSummaryView, OrderView
from app.tools import ToolResult
from app.tools.customer import check_eligibility

TODAY = date(2026, 11, 4)


def item(name="Cotton Polo Shirt", category="apparel", custom=False, sale="none"):
    return BackendItem(item_id=1, name=name, category=category, qty=1, sale_label=sale, custom_made=custom, pre_order=False)


def order(*items, status="Delivered", delivered=date(2026, 10, 25), order_id="NC-100001"):
    return OrderView(order_id=order_id, order_date=datetime(2026, 10, 1), status=status,
                     delivered_at=datetime(delivered.year, delivered.month, delivered.day, 14, 0, tzinfo=timezone.utc) if delivered and status == "Delivered" else None,
                     items=list(items) or [item()], returns=[], last_updated=datetime(2026, 11, 1))


def verdict(*items, today=TODAY, **kw):
    return rules.check_exchange(order(*items, **kw), today=today)


def ago(days):
    return TODAY - timedelta(days=days)


# ---------- the 14-day window and the 30-day wrong item ----------
def test_the_policys_shirt_delivered_8_days_ago_is_an_eligible_exchange():
    v = verdict(item("Shirt"), delivered=ago(8)).items[0]
    assert (v.kind, v.reason) == ("eligible", "standard") and v.last_day == ago(8) + timedelta(days=14) and v.second_day == ago(8) + timedelta(days=30)


def test_the_policys_shirt_delivered_20_days_ago_is_outside_the_14_day_window_and_only_a_wrong_item_is_exchanged():
    v = verdict(item("Shirt"), delivered=ago(20)).items[0]
    assert (v.kind, v.last_day) == ("wrong_item_only", ago(20) + timedelta(days=30))


@pytest.mark.parametrize("days_ago,kind", [(0, "eligible"), (14, "eligible"), (15, "wrong_item_only"), (30, "wrong_item_only"), (31, "expired")])
def test_day_14_is_the_last_day_of_the_exchange_window_and_day_30_of_the_wrong_item_exception(days_ago, kind):
    assert verdict(delivered=ago(days_ago)).items[0].kind == kind


def test_the_window_counts_the_cairo_calendar_day():
    late = OrderView(order_id="NC-1", order_date=datetime(2026, 9, 1), status="Delivered", items=[item()], returns=[], last_updated=datetime(2026, 10, 6),
                     delivered_at=datetime(2026, 10, 5, 22, 30, tzinfo=timezone.utc))          # 2026-10-06 01:30 in Cairo
    v = rules.check_exchange(late, today=date(2026, 10, 20))
    assert v.delivered_date == date(2026, 10, 6) and v.items[0].last_day == date(2026, 10, 20) and v.items[0].kind == "eligible"
    assert rules.check_exchange(late, today=date(2026, 10, 21)).items[0].kind == "wrong_item_only"


# ---------- what cannot be exchanged ----------
def test_gift_cards_are_never_exchangeable():
    v = verdict(item("Card", "gift_card"), delivered=ago(3)).items[0]
    assert (v.kind, v.reason, v.last_day) == ("not_exchangeable", "gift_card", None)


@pytest.mark.parametrize("it,reason", [(item("Shampoo", "beauty"), "beauty"), (item(custom=True), "custom_made")])
@pytest.mark.parametrize("days_ago,kind", [(3, "wrong_item_only"), (30, "wrong_item_only"), (31, "expired")])
def test_beauty_and_custom_made_are_not_exchanged_for_a_size_but_a_wrong_item_is_exchanged_within_30_days(it, reason, days_ago, kind):
    # a decision taken under delegation (see docs/ELIGIBILITY_DECISIONS.md) (sections 3 and 6 can be read both ways)
    v = verdict(it, delivered=ago(days_ago)).items[0]
    assert (v.kind, v.reason) == (kind, reason) and v.last_day == ago(days_ago) + timedelta(days=30)


@pytest.mark.parametrize("days_ago,kind", [(10, "defective_only"), (30, "defective_only"), (31, "expired")])
def test_electronics_are_exchanged_only_if_defective_like_for_like_or_wrong_within_30_days(days_ago, kind):
    v = verdict(item("JBL", "electronics"), delivered=ago(days_ago)).items[0]
    assert (v.kind, v.reason) == (kind, "electronics" if kind == "defective_only" else "electronics")
    assert v.last_day == ago(days_ago) + timedelta(days=30)


@pytest.mark.parametrize("days_ago,kind", [(10, "defective_only"), (20, "wrong_item_only"), (31, "expired")])
@pytest.mark.parametrize("label", ["final_sale", "clearance"])
def test_a_final_sale_item_is_exchanged_only_if_defective_or_wrong(label, days_ago, kind):
    v = verdict(item("Sandals", sale=label), delivered=ago(days_ago)).items[0]
    assert (v.kind, v.reason) == (kind, "final_sale")
    if kind == "defective_only":
        assert v.last_day == ago(10) + timedelta(days=14) and v.second_day == ago(10) + timedelta(days=30)


def test_an_unknown_category_is_a_review_never_a_guess():
    v = verdict(item("Mystery", "furniture")).items[0]
    assert (v.kind, v.reason) == ("review", "unknown_category") and rules.needs_person(verdict(item("Mystery", "furniture")))


# ---------- the holiday window ----------
@pytest.mark.parametrize("delivered,today,kind", [
    (date(2026, 11, 20), date(2027, 1, 15), "eligible"), (date(2026, 11, 20), date(2027, 1, 16), "expired"),
    (date(2026, 11, 14), date(2026, 12, 20), "expired"), (date(2026, 12, 31), date(2027, 1, 20), "wrong_item_only"),
])
def test_orders_delivered_in_the_holiday_period_may_be_exchanged_until_jan_15(delivered, today, kind):
    assert verdict(delivered=delivered, today=today).items[0].kind == kind


# ---------- the order itself ----------
@pytest.mark.parametrize("status", ["Pending", "Confirmed", "Processing", "Packed", "Shipped", "Out for Delivery", "Cancelled"])
def test_an_order_that_is_not_delivered_can_not_be_exchanged_yet(status):
    v = rules.check_exchange(order(status=status), today=TODAY)
    assert (v.kind, v.reason, v.items) == ("not_delivered", status, ()) and v.cited == ["POL-EXC-001 §2@1.1"]


def test_failed_delivery_and_a_missing_date_are_a_review():
    assert rules.check_exchange(order(status="Failed Delivery"), today=TODAY).kind == "review"
    v = rules.check_exchange(order().model_copy(update={"delivered_at": None}), today=TODAY)
    assert (v.kind, v.reason) == ("review", "delivered_without_date") and rules.needs_person(v)


def test_an_item_clue_narrows_the_answer_only_when_exactly_one_item_matches():
    items = [item("Silver Watch"), item("Red Shirt")]
    assert [i.name for i in rules.check_exchange(order(*items), "watch", TODAY).items] == ["Silver Watch"]
    assert len(rules.check_exchange(order(*items), "s", TODAY).items) == 2


def test_the_sections_cited_follow_what_was_used():
    assert verdict(delivered=ago(5)).sections == ("§2", "§6", "§4")
    assert "§3" in verdict(item("Card", "gift_card"), delivered=ago(5)).sections
    assert verdict(item("Card", "gift_card"), delivered=ago(5)).sections == ("§2", "§3")


def test_the_tool_of_the_design_answers_for_exchange():
    res = asyncio.run(check_eligibility("exchange", order(delivered=date.today() - timedelta(days=3))))
    assert res.ok and res.data.kind == "items" and res.data.cited[0].startswith("POL-EXC-001")


def test_every_wording_exists_in_both_languages_with_known_placeholders_only():
    known = {"order_id", "order_status", "delivered_date", "waiting_days"}
    for table in rules.HEADER.values():
        for text in table.values():
            assert set(re.findall(r"\{([a-z_0-9]+)\}", text)) <= known
    for entry in rules.LINE.values():
        for text in entry.values():
            assert set(re.findall(r"\{([a-z_0-9]+)\}", text.format(i=1))) <= {"i1_name", "i1_end_date", "i1_wrong_date"}
    for text in rules.CONDITIONS.values():
        assert set(re.findall(r"\{([a-z_0-9]+)\}", text)) <= known
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


def ctx(message="ينفع استبدل المنتج", refs=None, pending=None):
    return AgentContext(role="customer", message=message, chat_id="c:s", deadline_at=time.monotonic() + 8, order_refs=refs or {}, pending=pending)


def summary(i, status="Delivered", name="Item"):
    return OrderSummaryView(order_id=f"NC-10000{i}", order_date=datetime(2026, 10, 1), status=status, product_names=[f"{name} {i}"], last_updated=datetime(2026, 11, 1))


def run_plan(tools, message="ينفع استبدل المنتج", refs=None, **arguments):
    part = Part(index=0, safety="SAFE", intent=Intent(id="C5", arguments=arguments), needs_explanation=False)
    update = asyncio.run(plan_node(AgentState(parts=[part], classify_ok=True), ctx(message, refs), tools))
    return update["parts"][0].outcome


REFS = {"order_ref_1": "NC-100001"}
RECENT_DELIVERED = date.today() - timedelta(days=5)


def test_the_plan_answers_with_code_chosen_words_and_real_values_only_in_render_values():
    tools = FakeTools(orders={"NC-100001": order(item("Cotton Polo Shirt"), delivered=RECENT_DELIVERED)})
    o = run_plan(tools, refs=REFS, order_ref="order_ref_1")
    assert o.kind == "chat" and o.handoff_reason is None and o.cited[0] == "POL-EXC-001 §2@1.1"
    assert "{i1_name}" in o.text and "{i1_end_date}" in o.text and "{i1_wrong_date}" in o.text and "{waiting_days}" in o.text
    assert o.render_values["i1_name"] == "Cotton Polo Shirt" and o.render_values["waiting_days"] == "7" and "NC-100001" not in o.text
    assert o.render_values["i1_end_date"] == (RECENT_DELIVERED + timedelta(days=14)).isoformat()
    assert tools.calls == [("order_details", "NC-100001")]


def test_the_stock_price_and_unavailable_text_appears_only_when_an_exchange_can_go_ahead():
    ok = run_plan(FakeTools(orders={"NC-100001": order(delivered=RECENT_DELIVERED)}), refs=REFS, order_ref="order_ref_1")
    assert "{waiting_days}" in ok.text and "رصيد في المتجر" in ok.text
    none = run_plan(FakeTools(orders={"NC-100001": order(item("Card", "gift_card"), delivered=RECENT_DELIVERED)}), refs=REFS, order_ref="order_ref_1")
    assert "{waiting_days}" not in none.text and "رصيد" not in none.text


def test_the_answer_says_an_exchange_is_not_a_return():
    o = run_plan(FakeTools(orders={"NC-100001": order(delivered=RECENT_DELIVERED)}), refs=REFS, order_ref="order_ref_1")
    assert "غير الإرجاع" in o.text
    en = run_plan(FakeTools(orders={"NC-100001": order(delivered=RECENT_DELIVERED)}), message="can I exchange order NC-100001", refs=REFS, order_ref="order_ref_1")
    assert "this is not a return" in en.text and en.text.startswith("Your order {order_id} was delivered")


def test_an_order_with_several_items_gets_a_line_for_each():
    items = [item("Silver Watch", "electronics"), item("Red Shirt"), item("Card", "gift_card")]
    o = run_plan(FakeTools(orders={"NC-100001": order(*items, delivered=RECENT_DELIVERED)}), refs=REFS, order_ref="order_ref_1")
    assert [o.render_values[f"i{n}_name"] for n in (1, 2, 3)] == ["Silver Watch", "Red Shirt", "Card"]
    assert "i3_end_date" not in o.render_values and "i2_wrong_date" in o.render_values and "i1_wrong_date" not in o.render_values


def test_a_review_verdict_hands_off_and_a_not_delivered_order_does_not():
    assert run_plan(FakeTools(orders={"NC-100001": order(status="Shipped")}), refs=REFS, order_ref="order_ref_1").handoff_reason is None
    assert run_plan(FakeTools(orders={"NC-100001": order(status="Failed Delivery")}), refs=REFS, order_ref="order_ref_1").handoff_reason == "PENDING_OWNER"
    odd = run_plan(FakeTools(orders={"NC-100001": order(item("X", "furniture"), delivered=RECENT_DELIVERED)}), refs=REFS, order_ref="order_ref_1")
    assert odd.handoff_reason == "PENDING_OWNER"


def test_with_several_delivered_orders_the_agent_asks_which_and_with_one_it_is_that_one():
    assert run_plan(FakeTools(recent=[summary(1, "Shipped"), summary(2), summary(4)])).reason == "missing_order_id"
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


def c5_answer(**args):
    return {"parts": [{"safety": "SAFE", "escalation_flags": [], "p1_flag": None, "intent_id": "C5", "needs_explanation": False,
                       "args": {"order_ref": None, "item_clue": None, "return_id": None, **args}}], "english_query": None}


def test_a_whole_turn_gives_the_text_with_its_citations(fake):
    fake(c5_answer(order_ref="order_ref_1"))
    tools = FakeTools(orders={"NC-100001": order(delivered=RECENT_DELIVERED)})
    r = asyncio.run(run_agent(ctx("can I exchange order NC-100001 for a bigger size please", REFS), tools))
    assert [s.kind for s in r.segments] == ["text"] and r.handoff_reason is None
    assert r.segments[0].cited[0] == "POL-EXC-001 §2@1.1"


def test_which_order_then_2_gives_the_exchange_verdict_for_the_second_delivered_order(fake):
    fake(c5_answer())
    recent = [summary(1, "Shipped"), summary(2), summary(4)]
    tools = FakeTools(orders={"NC-100002": order(item("Two"), delivered=RECENT_DELIVERED, order_id="NC-100002"),
                              "NC-100004": order(item("Four"), delivered=RECENT_DELIVERED, order_id="NC-100004")}, recent=recent)
    first = asyncio.run(run_agent(ctx("can I exchange something please, the size is wrong"), tools))
    pending = first.memory["pending"]
    assert pending["intent"] == "C5" and [c["ref"] for c in pending["choices"]] == ["NC-100002", "NC-100004"]
    second = asyncio.run(run_agent(ctx("2", refs=pend.order_refs_for(pending), pending=pending), tools))
    assert second.segments[0].render_values["order_id"] == "NC-100004" and second.segments[0].render_values["i1_name"] == "Four"
