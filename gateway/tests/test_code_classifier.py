"""The code fast path of classify: exact matches skip the model, everything else goes to it."""
import asyncio
import time

import pytest

from app.agent import AgentContext
from app.agent.classify import classify_node
from app.agent.code_classifier import CodeClassifier
from app.agent.state import AgentState
from app.llm import client
from app.llm.fake import FakeAdapter

CC = CodeClassifier()


def ctx(message, role="customer", order_refs=None):
    return AgentContext(role=role, message=message, chat_id="c:s", deadline_at=time.monotonic() + 8,
                        order_refs=order_refs or {})


def intent_of(message, role="customer", order_refs=None):
    parts = CC.classify(ctx(message, role, order_refs))
    return None if parts is None else parts[0].intent


@pytest.mark.parametrize("message, role, want", [
    ("where is my order", "customer", "C1"),
    ("Where is my order?", "customer", "C1"),                 # case and edge punctuation do not matter
    ("  فين طلبي ؟ ", "customer", "C1"),
    ("feen talabi", "customer", "C1"),
    ("return status", "customer", "C3"),
    ("حالة المرتجع", "customer", "C3"),
    ("I want to talk to a human", "customer", "C6"),
    ("عايز اكلم موظف", "customer", "C6"),
    ("شحناتي النهارده", "worker", "W1"),
    ("my shipments today", "worker", "W1"),
])
def test_plain_messages_are_classified_by_code(message, role, want):
    assert intent_of(message, role).id == want


def test_a_code_match_is_a_safe_fast_path_part():
    part = CC.classify(ctx("where is my order"))[0]
    assert (part.index, part.safety, part.escalation_flags, part.needs_explanation) == (0, "SAFE", [], False)


@pytest.mark.parametrize("message", [
    "where is my order and why is it late",                  # extra words: the LLM decides
    "please where is my order",
    "where is my order and what is the return status",       # two intents
    "someone hacked my account where is my order",           # a danger word can not hide in a match
    "weather today",
    "",
    "   ",
])
def test_anything_not_an_exact_single_match_goes_to_the_llm(message):
    assert CC.classify(ctx(message)) is None


def test_the_role_decides_which_patterns_apply():
    assert CC.classify(ctx("شحناتي النهارده", "customer")) is None
    assert CC.classify(ctx("where is my order", "worker")) is None


def test_worker_request_for_a_human_is_not_on_the_code_path():
    assert CC.classify(ctx("I want to talk to a human", "worker")) is None       # W5 stays on the LLM


def test_a_reference_must_exist_in_the_request_map():
    refs = {"order_ref_1": "NC-100007"}
    assert intent_of("where is my order {order_ref_1}", order_refs=refs).arguments == {"order_ref": "order_ref_1"}
    assert intent_of("where is my order order_ref_1", order_refs=refs).arguments == {"order_ref": "order_ref_1"}
    assert intent_of("where is my order {order_ref_2}", order_refs=refs) is None
    assert intent_of("where is my order {order_ref_1}") is None                  # empty map


def test_the_model_is_not_called_on_a_code_match():
    adapter = FakeAdapter()
    client.set_adapter(adapter)
    try:
        r = asyncio.run(classify_node(AgentState(), ctx("شحناتي النهارده", "worker")))
    finally:
        client.set_adapter(None)
    assert adapter.calls == []
    assert r["classify_ok"] is True and r["english_query"] is None and r["parts"][0].intent.id == "W1"


def test_no_match_still_reaches_the_model():
    adapter = FakeAdapter({"parts": [], "english_query": None})
    client.set_adapter(adapter)
    try:
        asyncio.run(classify_node(AgentState(), ctx("where is my order and why is it late")))
    finally:
        client.set_adapter(None)
    assert len(adapter.calls) == 1


def test_only_the_four_agreed_intents_exist_on_the_code_path():
    from app.agent.code_classifier import RULES
    assert sorted(r.intent_id for r in RULES) == ["C1", "C3", "C6", "W1"]
