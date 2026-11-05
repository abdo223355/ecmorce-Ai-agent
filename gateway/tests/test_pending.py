"""Short-term memory, first slice: a pending clarification, the user's short answer ("2", "التاني", a product name), the
store in Redis, and a whole conversation of two turns. No network, no model, no real Redis (one test uses it if it is there)."""
import asyncio
import time
from datetime import datetime

import pytest

from app.agent import AgentContext, run_agent
from app.agent import pending as pend
from app.agent.clarify import MAX_ROUNDS, clarify_node
from app.agent.classify import classify_node
from app.agent.state import AgentState, Intent, Part, PartOutcome
from app.llm import client
from app.llm.fake import FakeAdapter
from app.memory import MemoryStore, key_for
from app.schemas import BackendReturnRow, OrderSummaryView, OrderView
from app.tools import ToolResult

NOW = datetime(2026, 10, 18, 12, 0)


def card(reason="which_return", intent="C3", round_=1, labels=("Silver Watch · 2026-10-18", "Red Shirt · 2026-10-17")):
    refs = ["R-500001", "R-500002"] if reason == "which_return" else ["NC-100001", "NC-100002"]
    return pend.card_from(intent, reason, round_, [{"label": l, "ref": r} for l, r in zip(labels, refs)])


# ---------- the short answer ----------
@pytest.mark.parametrize("message,expected", [
    ("2", 2), ("٢", 2), (" 2 ", 2), ("2.", 2), ("رقم 2", 2), ("number 2", 2), ("الاول", 1), ("الأول", 1), ("التاني", 2), ("التالت", 3),
    ("the first", 1), ("Second", 2), ("the second one", 2), ("1st", 1), ("12", 12),
    ("فين طلبي", None), ("2 orders", None), ("", None), ("اتنين", None), ("NC-100001", None),
])
def test_a_bare_number_or_ordinal_is_recognised_and_nothing_else(message, expected):
    assert pend.bare_number(message) == expected


@pytest.mark.parametrize("message,index", [
    ("1", 0), ("2", 1), ("التاني", 1), ("الأول", 0), ("the second", 1),
    ("Silver Watch", 0), ("silver watch please", 0), ("الـ Red Shirt", 1),
    ("3", None), ("0", None), ("7", None),                                   # out of range: a new request
    ("hello", None), ("فين طلبي بتاعي دلوقتي من فضلك يا باشا بسرعة", None),
])
def test_pick_chooses_by_position_or_by_a_unique_product_name(message, index):
    assert pend.pick(message, card()) == index


def test_a_product_name_in_two_choices_is_not_picked_and_a_long_message_is_a_new_request():
    twin = card(labels=("Silver Watch · 2026-10-18", "Silver Watch · 2026-10-10"))
    assert pend.pick("silver watch", twin) is None
    assert pend.pick("silver watch " + "x " * 8, card()) is None


def test_the_arguments_of_a_pick_and_the_order_refs_of_a_pending_which_order():
    orders = card("missing_order_id", "C1")
    assert pend.order_refs_for(orders) == {"order_ref_c1": "NC-100001", "order_ref_c2": "NC-100002"}
    assert pend.arguments_for(orders, 1) == {"order_ref": "order_ref_c2"}
    returns = card()
    assert pend.order_refs_for(returns) == {} and pend.order_refs_for(None) == {}
    assert pend.arguments_for(returns, 0) == {"return_id": "R-500001"}


def test_only_a_card_this_code_wrote_is_valid():
    assert pend.valid(card()) and pend.valid(card("missing_order_id", "C1"))
    for bad in (None, "x", {}, {"reason": "other", "intent": "C1", "round": 1, "choices": [{"label": "a", "ref": "b"}]},
                {**card(), "choices": []}, {**card(), "choices": [{"label": 1, "ref": "b"}]}, {**card(), "round": "1"},
                {**card(), "choices": [{"label": "a", "ref": "b"}] * 11}):
        assert not pend.valid(bad)


def test_the_card_holds_labels_and_ids_only():
    c = pend.card_from("C3", "which_return", 1, [{"label": "Watch · 2026-10-18", "ref": "R-500001", "extra": "secret"}])
    assert set(c) == {"intent", "reason", "round", "choices"} and c["choices"] == [{"label": "Watch · 2026-10-18", "ref": "R-500001"}]


# ---------- classify: the code picks, or says the list is gone ----------
def ctx(message, pending=None, refs=None, role="customer"):
    return AgentContext(role=role, message=message, chat_id="c:s", deadline_at=time.monotonic() + 8,
                        order_refs=refs or {}, pending=pending)


@pytest.fixture
def fake():
    def install(*responses):
        f = FakeAdapter(*responses)
        client.set_adapter(f)
        return f
    yield install
    client.set_adapter(None)


def test_classify_continues_the_pending_intent_with_the_picked_return_and_calls_no_model(fake):
    f = fake()
    out = asyncio.run(classify_node(AgentState(), ctx("2", card())))
    part = out["parts"][0]
    assert f.calls == [] and out["classify_ok"] is True
    assert (part.intent.id, part.intent.arguments, part.safety) == ("C3", {"return_id": "R-500002"}, "SAFE")
    assert out["telemetry"]["classify"] == {"path": "memory", "status": "ok", "latency_s": 0.0}


def test_classify_continues_a_pending_which_order_with_a_mapped_order_ref(fake):
    f = fake()
    pending = card("missing_order_id", "C1")
    out = asyncio.run(classify_node(AgentState(), ctx("التاني", pending, refs=pend.order_refs_for(pending))))
    assert f.calls == [] and out["parts"][0].intent.arguments == {"order_ref": "order_ref_c2"}


def test_a_message_that_is_not_a_reference_is_a_new_request_even_with_a_pending_card(fake):
    f = fake({"parts": [{"safety": "SAFE", "escalation_flags": [], "p1_flag": None, "intent_id": "C6", "needs_explanation": False,
                         "args": {"order_ref": None, "item_clue": None, "return_id": None}}], "english_query": None})
    out = asyncio.run(classify_node(AgentState(), ctx("I want to talk to a person and also something long and unusual here", card())))
    assert len(f.calls) == 1 and out["parts"][0].intent.id == "C6"


def test_a_number_outside_the_list_goes_to_the_normal_path(fake):
    f = fake({"parts": [], "english_query": None})
    out = asyncio.run(classify_node(AgentState(), ctx("7", card())))
    assert len(f.calls) == 1 and out["parts"][0].outcome.kind == "chat"       # the friendly "I did not understand"


@pytest.mark.parametrize("message,starts", [("2", "مش فاكر"), ("التاني", "مش فاكر"), ("the second", "I do not have")])
def test_a_bare_reference_with_nothing_in_memory_asks_again_and_is_no_failed_attempt(fake, message, starts):
    f = fake()
    out = asyncio.run(classify_node(AgentState(), ctx(message)))
    part = out["parts"][0]
    assert f.calls == [] and part.outcome.kind == "chat" and part.outcome.text.startswith(starts)
    assert part.intent is None and out["telemetry"]["classify"]["lost_context"] is True


# ---------- clarify: the card and the round ----------
def ask_part(reason, intent, index=0):
    return Part(index=index, safety="SAFE", intent=Intent(id=intent), outcome=PartOutcome(kind="clarify", reason=reason))


def returns_records():
    rows = [BackendReturnRow(return_id=f"R-50000{i}", order_id=f"NC-10000{i}", status="Received", created_at=NOW, last_updated=NOW,
                             item=name) for i, name in ((1, "Silver Watch"), (2, "Red Shirt"))]
    from app.agent.state import ToolRecord
    return [ToolRecord(tool="my_returns", result=ToolResult("ok", data=rows))]


def test_the_clarify_node_leaves_a_card_with_the_choices_and_round_1():
    state = AgentState(parts=[ask_part("which_return", "C3")], tool_results=returns_records())
    out = clarify_node(state, ctx("حالة المرتجع"))
    assert out["pending"] == {"intent": "C3", "reason": "which_return", "round": 1,
                              "choices": [{"label": "Silver Watch · 2026-10-18", "ref": "R-500001"},
                                          {"label": "Red Shirt · 2026-10-18", "ref": "R-500002"}]}


def test_a_question_asked_again_counts_its_rounds_and_ends_in_a_handoff_after_the_limit():
    state = AgentState(parts=[ask_part("which_return", "C3")], tool_results=returns_records())
    out = clarify_node(state, ctx("hmm", card(round_=2)))
    assert out["pending"]["round"] == 3
    out = clarify_node(state, ctx("hmm", card(round_=MAX_ROUNDS)))
    assert "pending" not in out and out["parts"][0].outcome.handoff_reason == "PENDING_OWNER"


def test_the_round_of_a_different_question_is_not_counted():
    state = AgentState(parts=[ask_part("which_return", "C3")], tool_results=returns_records())
    other = card("missing_order_id", "C1", round_=MAX_ROUNDS)
    out = clarify_node(state, ctx("hmm", other))
    assert out["pending"]["round"] == 1


def test_a_question_with_no_list_leaves_no_card():
    out = clarify_node(AgentState(parts=[ask_part("missing_shipment_id", "W2")]), ctx("x"))
    assert "pending" not in out


# ---------- two turns, the whole agent ----------
class FakeTools:
    def __init__(self, recent=None, orders=None, returns=None):
        self.recent, self.orders, self.returns, self.calls = recent or [], orders or {}, returns or [], []

    async def my_recent_orders(self):
        self.calls.append("my_recent_orders")
        return ToolResult("ok", data=self.recent)

    async def my_returns(self):
        self.calls.append("my_returns")
        return ToolResult("ok", data=self.returns)

    async def order_details(self, order_id):
        self.calls.append(("order_details", order_id))
        got = self.orders.get(order_id)
        return ToolResult("ok", data=got) if got else ToolResult("denied", reason="not_found_or_not_yours")


def row(i, status):
    return BackendReturnRow(return_id=f"R-50000{i}", order_id=f"NC-10000{i}", status=status, created_at=NOW, last_updated=NOW, item="Watch")


def test_which_return_then_2_gives_the_second_return_without_any_model_call(fake):
    f = fake()
    tools = FakeTools(returns=[row(1, "Approved"), row(2, "Refunded")])
    first = asyncio.run(run_agent(ctx("حالة المرتجع"), tools))
    assert [s.kind for s in first.segments] == ["clarify"] and first.memory["pending"]["reason"] == "which_return"
    second = asyncio.run(run_agent(ctx("2", first.memory["pending"]), tools))
    assert [(s.kind, s.template_id) for s in second.segments] == [("template", 2)]
    assert second.segments[0].render_values["return_status"] == "Refunded" and second.memory == {}
    assert f.calls == []                                                       # classify, plan, render: all code


def summary(i, status="Delivered"):
    return OrderSummaryView(order_id=f"NC-10000{i}", order_date=NOW, status=status, product_names=[f"Item {i}"], last_updated=NOW)


def order(i):
    return OrderView(order_id=f"NC-10000{i}", order_date=NOW, status="Delivered", delivered_at=NOW, items=[], returns=[], last_updated=NOW)


def test_which_order_then_a_product_name_gives_that_order(fake):
    f = fake()
    tools = FakeTools(recent=[summary(1), summary(2)], orders={"NC-100001": order(1), "NC-100002": order(2)})
    first = asyncio.run(run_agent(ctx("فين طلبي؟"), tools))
    pending = first.memory["pending"]
    assert [s.kind for s in first.segments] == ["clarify"] and pending["reason"] == "missing_order_id"
    second = asyncio.run(run_agent(ctx("item 2", pending, refs=pend.order_refs_for(pending)), tools))
    assert second.segments[0].render_values["order_id"] == "NC-100002" and ("order_details", "NC-100002") in tools.calls
    assert f.calls == []


def test_an_answer_that_is_not_in_the_list_is_handled_as_a_new_message_and_the_old_card_is_dropped(fake):
    f = fake({"parts": [], "english_query": None})                            # the model finds no request in "9"
    tools = FakeTools(recent=[summary(1), summary(2)], orders={})
    first = asyncio.run(run_agent(ctx("فين طلبي؟"), tools))
    pending = first.memory["pending"]
    again = asyncio.run(run_agent(ctx("9", pending, refs=pend.order_refs_for(pending)), tools))
    assert len(f.calls) == 1 and again.segments[0].kind == "text" and again.memory == {}     # friendly answer, card gone


# ---------- the store ----------
class FakeRedis:
    def __init__(self, delay=0.0, fail=False):
        self.data, self.ttls, self.delay, self.fail = {}, {}, delay, fail

    async def get(self, key):
        await self._wait()
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        await self._wait()
        self.data[key], self.ttls[key] = value, ex

    async def delete(self, key):
        await self._wait()
        self.data.pop(key, None)

    async def _wait(self):
        if self.fail:
            raise ConnectionError("redis is down")
        if self.delay:
            await asyncio.sleep(self.delay)


def test_the_key_is_a_hash_and_shows_no_owner_id():
    key = key_for("C-100005:session-1")
    assert key.startswith("mem:") and "C-100005" not in key and "session" not in key and key == key_for("C-100005:session-1")
    assert key != key_for("C-100005:session-2")                                # a new login is a new chat


def test_put_get_delete_with_a_thirty_minute_ttl_that_is_reset_on_each_write():
    r = FakeRedis()
    store = MemoryStore("redis://x", client=r)
    asyncio.run(store.put("c:s", {"pending": card()}))
    assert r.ttls[key_for("c:s")] == 30 * 60
    assert asyncio.run(store.get("c:s")) == {"pending": card()}
    asyncio.run(store.put("c:s", None))
    assert asyncio.run(store.get("c:s")) is None


def test_the_stored_value_holds_no_message_text_only_the_card():
    r = FakeRedis()
    asyncio.run(MemoryStore("redis://x", client=r).put("c:s", {"pending": card()}))
    stored = next(iter(r.data.values()))
    assert "فين" not in stored and "token" not in stored and "C-100005" not in stored


def test_redis_down_is_a_fresh_start_not_an_error():
    store = MemoryStore("redis://x", client=FakeRedis(fail=True))
    assert asyncio.run(store.get("c:s")) is None
    asyncio.run(store.put("c:s", {"pending": card()}))                          # nothing raised


def test_a_slow_redis_does_not_hold_the_request():
    store = MemoryStore("redis://x", client=FakeRedis(delay=2.0))
    t0 = time.monotonic()
    assert asyncio.run(store.get("c:s")) is None
    assert time.monotonic() - t0 < 1.0


def test_memory_is_off_when_there_is_no_url():
    store = MemoryStore("")
    assert asyncio.run(store.get("c:s")) is None
    asyncio.run(store.put("c:s", {"pending": card()}))


def test_the_real_redis_round_trip_when_one_is_reachable():
    pytest.importorskip("redis")
    store = MemoryStore("redis://redis:6379/15")

    async def go():
        await store.put("test:chat", {"pending": card()})
        got = await store.get("test:chat")
        await store.put("test:chat", None)
        return got, await store.get("test:chat")
    got, after = asyncio.run(go())
    if got is None:
        pytest.skip("no Redis reachable at redis:6379")
    assert got == {"pending": card()} and after is None
