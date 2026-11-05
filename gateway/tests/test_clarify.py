"""Node 6 (clarify): code only. It reads outcomes and the tool_results the plan fetched; it calls nothing."""
import time
from datetime import datetime

import pytest

from app.agent import AgentContext
from app.agent.clarify import (CHOICE_SOURCES, MAX_CHOICES, MAX_ROUNDS, Choice, ClarifyPlanner, LanguageDetector,
                               QuestionBook, RecentOrdersChoices, ReturnChoices, clarify_node)
from app.agent.state import AgentState, Intent, Part, PartOutcome, ToolRecord
from app.schemas import BackendReturn, OrderSummaryView, OrderView
from app.tools import ToolResult

NOW = datetime(2026, 10, 18, 12, 0)


def summary(order_id, *names):
    return OrderSummaryView(order_id=order_id, order_date=NOW, status="Shipped", product_names=list(names), last_updated=NOW)


def recent(*orders):
    return ToolRecord(tool="my_recent_orders", result=ToolResult("ok", data=list(orders)))


def order_with_returns(order_id, *returns):
    view = OrderView(order_id=order_id, order_date=NOW, status="Delivered", delivered_at=NOW, items=[],
                     returns=list(returns), last_updated=NOW)
    return ToolRecord(tool="order_details", argument=order_id, result=ToolResult("ok", data=view))


def ret(return_id, item="Silver Watch"):
    return BackendReturn(return_id=return_id, status="Requested", created_at=NOW, last_updated=NOW, item=item)


def ask_part(index, reason="missing_order_id", intent_id="C1"):
    return Part(index=index, safety="SAFE", intent=Intent(id=intent_id),
                outcome=PartOutcome(kind="clarify", reason=reason))


def answered_part(index):
    return Part(index=index, safety="SAFE", intent=Intent(id="C3"),
                outcome=PartOutcome(kind="template", template_id=2, render_values={"return_id": "RT-1"}))


def ctx(message="فين الساعة اللي طلبتها؟", role="customer", clarify_round=0):
    return AgentContext(role=role, message=message, chat_id="c:s", deadline_at=time.monotonic() + 8,
                        clarify_round=clarify_round)


def run(parts, records=(), **kw):
    state = AgentState(classify_ok=True, parts=parts, tool_results=list(records))
    return clarify_node(state, ctx(**kw))


# ---------- when there is nothing to do ----------
def test_no_clarify_part_means_the_node_adds_nothing():
    assert run([answered_part(0)]) == {}
    assert run([Part(index=0, safety="SAFE")]) == {}


# ---------- the question ----------
def test_an_order_question_shows_the_recent_orders_numbered_newest_first():
    u = run([ask_part(0)], [recent(summary("NC-100002", "Silver Watch"), summary("NC-100001", "Classic Watch", "Strap"))])
    o = u["parts"][0].outcome
    assert o.kind == "clarify" and o.reason == "missing_order_id"
    assert "{choices_text}" in o.text and u["clarify_question"] == o.text
    assert o.render_values == {"choices_text": "1) Silver Watch · 2026-10-18\n2) Classic Watch, Strap · 2026-10-18"}


def test_the_question_holds_placeholders_only_and_no_real_id():
    u = run([ask_part(0)], [recent(summary("NC-100002", "Silver Watch"))])
    assert "NC-100002" not in u["clarify_question"] and "NC-100002" not in str(u["parts"][0].outcome.render_values)


def test_at_most_five_choices():
    records = [recent(*[summary(f"NC-10000{i}", f"Item {i}") for i in range(1, 9)])]
    o = run([ask_part(0)], records)["parts"][0].outcome
    assert o.render_values["choices_text"].count("\n") == MAX_CHOICES - 1


def test_which_return_lists_the_returns_inside_the_orders():
    records = [order_with_returns("NC-100001", ret("RT-500001", "Silver Watch")),
               order_with_returns("NC-100002", ret("RT-500002", "Red Shirt"), ret("RT-500001", "Silver Watch"))]
    o = run([ask_part(0, "which_return", "C3")], records)["parts"][0].outcome
    assert o.render_values["choices_text"] == "1) Silver Watch · 2026-10-18\n2) Red Shirt · 2026-10-18"   # no duplicates


@pytest.mark.parametrize("reason, records", [("missing_order_id", []), ("which_return", []),
                                              ("missing_shipment_id", []), ("invalid_format", []),
                                              ("nothing_found", []), ("something_new", [])])
def test_a_question_without_a_list_still_works_and_an_unknown_reason_is_generic(reason, records):
    u = run([ask_part(0, reason)], records)
    o = u["parts"][0].outcome
    assert o.text and "{choices_text}" not in o.text and o.render_values == {}


def test_a_failed_recent_orders_result_gives_no_list():
    bad = ToolRecord(tool="my_recent_orders", result=ToolResult("unavailable", reason="backend_unavailable"))
    assert run([ask_part(0)], [bad])["parts"][0].outcome.render_values == {}


# ---------- the language ----------
@pytest.mark.parametrize("message, expected", [
    ("فين الساعة اللي طلبتها؟", "ar"), ("feen talabi el watch", "ar"), ("3ayez 7alet el mortaga3", "ar"),
    ("where is my watch order", "en"), ("Where is my order?", "en"), ("watch", "ar"), ("", "ar"),
    ("where is my order ana", "ar"),                       # an English message with a Franco word is Arabic
])
def test_language_detection(message, expected):
    assert LanguageDetector().detect(message) == expected


def test_the_question_follows_the_language_of_the_message():
    records = [recent(summary("NC-100002", "Silver Watch"))]
    en = run([ask_part(0)], records, message="where is my watch order")["parts"][0].outcome.text
    ar = run([ask_part(0)], records, message="feen talabi")["parts"][0].outcome.text
    assert en.startswith("Which order") and ar.startswith("أنهي طلب")


# ---------- one question per turn ----------
def test_only_the_earliest_part_is_asked_and_the_others_wait():
    u = run([ask_part(2, "which_return", "C3"), ask_part(0)], [recent(summary("NC-100001", "Watch"))])
    by_index = {p.index: p.outcome for p in u["parts"]}
    assert by_index[0].text and by_index[2].text is None            # part 0 asked, part 2 deferred
    assert "هسألك عن باقي" in u["clarify_question"]                  # tells the user the rest comes later


def test_a_single_clarify_part_gets_no_rest_sentence():
    assert "هسألك عن باقي" not in run([ask_part(0)])["clarify_question"]


def test_answered_parts_are_left_untouched():
    u = run([answered_part(0), ask_part(1)])
    assert u["parts"][0].outcome == answered_part(0).outcome


# ---------- the round limit ----------
@pytest.mark.parametrize("round_", [0, 1, 2])
def test_before_the_limit_it_asks(round_):
    u = run([ask_part(0)], clarify_round=round_)
    assert u["parts"][0].outcome.kind == "clarify" and "clarify_question" in u


@pytest.mark.parametrize("round_", [MAX_ROUNDS, MAX_ROUNDS + 1])
def test_at_the_limit_it_hands_off_with_pending_owner_and_asks_nothing(round_):
    u = run([ask_part(0), ask_part(1, "which_return", "C3"), answered_part(2)], clarify_round=round_)
    assert "clarify_question" not in u
    outs = [p.outcome for p in u["parts"]]
    assert [(o.kind, o.handoff_reason, o.priority) for o in outs[:2]] == [("handoff", "PENDING_OWNER", None)] * 2
    assert outs[2].kind == "template"                                # an answered part is not touched


# ---------- the node itself ----------
def test_the_planner_picks_the_earliest_part():
    assert ClarifyPlanner.decide([ask_part(3), ask_part(1)], 0).part.index == 1


def test_the_state_it_reads_is_not_changed_and_the_result_is_deterministic():
    state = AgentState(classify_ok=True, parts=[ask_part(0)], tool_results=[recent(summary("NC-100001", "Watch"))])
    before = state.model_dump()
    a = clarify_node(state, ctx())
    b = clarify_node(state, ctx())
    assert state.model_dump() == before and a["clarify_question"] == b["clarify_question"]


def test_a_new_choice_source_needs_no_change_in_the_node():
    class Colors:
        def build(self, records):
            return (Choice("red", "r1"), Choice("blue", "b1"))
    u = clarify_node(AgentState(classify_ok=True, parts=[ask_part(0, "pick_color")]), ctx(),
                     sources={**CHOICE_SOURCES, "pick_color": Colors()},
                     book=type("Book", (QuestionBook,), {"TEXTS": {**QuestionBook.TEXTS,
                               ("pick_color", "ar", True): "أنهي لون؟\n{choices_text}"}})())
    assert u["parts"][0].outcome.render_values == {"choices_text": "1) red\n2) blue"}
    assert u["clarify_question"].startswith("أنهي لون")


def test_the_default_sources_are_the_two_agreed_ones():
    assert set(CHOICE_SOURCES) == {"missing_order_id", "which_return"}
    assert isinstance(CHOICE_SOURCES["missing_order_id"], RecentOrdersChoices)
    assert isinstance(CHOICE_SOURCES["which_return"], ReturnChoices)


def test_which_return_also_lists_the_returns_of_the_my_returns_list():
    from app.schemas import BackendReturnRow
    rows = [BackendReturnRow(return_id="RT-500001", order_id="NC-100001", status="Received", created_at=NOW, last_updated=NOW, item="Silver Watch"),
            BackendReturnRow(return_id="RT-500002", order_id="NC-100002", status="Refunded", created_at=NOW, last_updated=NOW, item="Red Shirt")]
    records = [ToolRecord(tool="my_returns", result=ToolResult("ok", data=rows))]
    o = run([ask_part(0, "which_return", "C3")], records)["parts"][0].outcome
    assert o.render_values["choices_text"] == "1) Silver Watch · 2026-10-18\n2) Red Shirt · 2026-10-18"
