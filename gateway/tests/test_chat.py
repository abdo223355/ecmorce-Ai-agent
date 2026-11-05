"""Small talk: a greeting, thanks, goodbye, "ok", "who are you", "help" are answered by code, and nothing else is swallowed."""
import asyncio
import re
import time

import pytest

from app.agent import AgentContext, run_agent
from app.agent.chat import CAPABILITIES, Talk, answer, match, normalize, part_for
from app.agent.classify import classify_node
from app.agent.state import AgentState
from app.llm import client
from app.llm.fake import FakeAdapter


def talk(message):
    t = match(message)
    return None if t is None else (t.kind, t.language)


# ---------- what counts as small talk ----------
@pytest.mark.parametrize("message,expected", [
    ("hi", ("greeting", "en")), ("Hello!", ("greeting", "en")), ("hiii", ("greeting", "en")), ("hey there", ("greeting", "en")),
    ("Good morning", ("greeting", "en")), ("هاي", ("greeting", "ar")), ("هااااي", ("greeting", "ar")), ("اهلا", ("greeting", "ar")),
    ("أهلاً بيك", ("greeting", "ar")), ("السلام عليكم", ("greeting", "ar")), ("السلام عليكم ورحمة الله وبركاته", ("greeting", "ar")),
    ("صباح الخير", ("greeting", "ar")), ("ازيك؟", ("greeting", "ar")), ("مساء النور", ("greeting", "ar")), ("ahlan", ("greeting", "ar")),
    ("salam alaikum", ("greeting", "ar")), ("👋 hi", ("greeting", "en")),
    ("thanks", ("thanks", "en")), ("Thank you so much!", ("thanks", "en")), ("شكرا", ("thanks", "ar")), ("شكراً ليك", ("thanks", "ar")),
    ("متشكر", ("thanks", "ar")), ("تسلم ايدك", ("thanks", "ar")), ("shokran", ("thanks", "ar")), ("تمام شكرا", ("thanks", "ar")),
    ("bye", ("bye", "en")), ("good night", ("bye", "en")), ("مع السلامة", ("bye", "ar")), ("باي باي", ("bye", "ar")),
    ("ok", ("ack", "en")), ("okay", ("ack", "en")), ("تمام", ("ack", "ar")), ("ماشي", ("ack", "ar")), ("طيب", ("ack", "ar")),
    ("who are you", ("identity", "en")), ("are you a bot?", ("identity", "en")), ("إنت مين؟", ("identity", "ar")), ("انت مين", ("identity", "ar")),
    ("help", ("help", "en")), ("I need help", ("help", "en")), ("what can you do", ("help", "en")), ("تقدر تعمل ايه؟", ("help", "ar")),
    ("محتاج مساعدة", ("help", "ar")), ("ساعدني", ("help", "ar")),
])
def test_small_talk_is_recognised_in_arabic_english_and_franco(message, expected):
    assert talk(message) == expected


@pytest.mark.parametrize("message", [
    "hi my account was hacked", "someone stole my card", "هاي فين طلبي", "اهلا عايز اكلم موظف", "hello where is my order",
    "شكرا بس الطلب لسه ماوصلش", "thanks but my order is late", "السلام عليكم حد دخل على حسابي", "help I was robbed",
    "فين طلبي", "ما هي سياسة الاسترجاع؟", "NC-100010", "1", "2", "asdf qwer", "", "   ", "!!!", "👋",
])
def test_anything_that_is_more_than_small_talk_is_left_to_the_classify(message):
    assert match(message) is None


def test_normalising_removes_accents_stretching_punctuation_and_emoji():
    assert normalize("  أهلاً!!!  👋 ") == "اهلا" and normalize("شكراً") == "شكرا" and normalize("السلامة") == "السلامه"


# ---------- the answers ----------
def test_every_kind_has_an_answer_for_each_role_and_language_with_no_placeholder():
    for kind in ("greeting", "thanks", "bye", "ack", "identity", "help", "unclear"):
        for role in ("customer", "worker"):
            for language in ("ar", "en"):
                text = answer(kind, role, language)
                assert text and "{" not in text and "None" not in text


def test_the_capabilities_name_only_what_each_role_really_has():
    customer, worker = CAPABILITIES[("customer", "en")], CAPABILITIES[("worker", "en")]
    assert "order status" in customer and "return status" in customer and "Customer Service" in customer and "dispatch" not in customer
    assert "today's shipments" in worker and "dispatch" in worker and "return" not in worker and "order status" not in worker
    assert "حالة طلبك" in CAPABILITIES[("customer", "ar")] and "dispatch" in CAPABILITIES[("worker", "ar")]


def test_a_greeting_greets_and_a_thanks_does_not_repeat_the_menu():
    assert answer("greeting", "customer", "ar").startswith("أهلًا") and CAPABILITIES[("customer", "ar")] in answer("greeting", "customer", "ar")
    assert answer("thanks", "customer", "en") == "You're welcome! If you need anything else, I'm here."
    assert answer("identity", "customer", "en").startswith("I am NovaCart's AI assistant")      # it says it is not a person


def test_the_part_has_no_intent_no_template_and_the_words_are_already_there():
    part = part_for(Talk("greeting", "en"), "customer")
    assert part.intent is None and part.safety == "SAFE" and part.outcome.kind == "chat" and part.outcome.template_id is None
    assert part.outcome.text == answer("greeting", "customer", "en")


# ---------- in the agent ----------
def ctx(message, role="customer"):
    return AgentContext(role=role, message=message, chat_id="c:s", deadline_at=time.monotonic() + 8)


@pytest.fixture
def fake():
    def install(*responses):
        f = FakeAdapter(*responses)
        client.set_adapter(f)
        return f
    yield install
    client.set_adapter(None)


def test_classify_answers_small_talk_without_a_model_call_and_says_so_in_its_telemetry(fake):
    f = fake()
    out = asyncio.run(classify_node(AgentState(), ctx("hi")))
    assert f.calls == [] and out["classify_ok"] is True and out["parts"][0].outcome.kind == "chat"
    assert out["telemetry"]["classify"] == {"path": "code", "status": "ok", "latency_s": 0.0, "small_talk": "greeting"}


def test_the_whole_agent_answers_hi_with_one_text_segment_and_no_handoff_or_template(fake):
    f = fake()
    for role, message in (("customer", "hi"), ("worker", "هاي"), ("customer", "شكرا"), ("customer", "who are you")):
        result = asyncio.run(run_agent(ctx(message, role), object()))                      # no tool is touched
        assert [(s.kind, s.template_id) for s in result.segments] == [("text", None)], message
        assert result.handoff_reason is None and result.priority is None and result.segments[0].text
    assert f.calls == []


def test_the_worker_gets_the_worker_menu_and_the_customer_the_customer_menu(fake):
    fake()
    worker = asyncio.run(run_agent(ctx("hi", "worker"), object())).segments[0].text
    customer = asyncio.run(run_agent(ctx("hi", "customer"), object())).segments[0].text
    assert CAPABILITIES[("worker", "en")] in worker and CAPABILITIES[("customer", "en")] in customer


def test_a_greeting_with_a_request_still_goes_to_the_classify(fake):
    f = fake({"parts": [{"safety": "SAFE", "escalation_flags": [], "p1_flag": None, "intent_id": "C6", "needs_explanation": False,
                         "args": {"order_ref": None, "item_clue": None, "return_id": None}}], "english_query": None})
    result = asyncio.run(run_agent(ctx("hi I want to talk to a person"), object()))
    assert len(f.calls) == 1 and [s.template_id for s in result.segments] == [5] and result.handoff_reason == "PENDING_OWNER"


def test_a_safety_message_that_starts_like_a_greeting_is_never_swallowed(fake):
    f = fake({"parts": [{"safety": "P1", "escalation_flags": [], "p1_flag": "takeover", "intent_id": "C7", "needs_explanation": False,
                         "args": {"order_ref": None, "item_clue": None, "return_id": None}}], "english_query": None})
    result = asyncio.run(run_agent(ctx("hi my account was hacked"), object()))
    assert len(f.calls) == 1 and result.priority == "P1" and [s.template_id for s in result.segments] == [8]


def test_a_model_answer_with_no_parts_is_a_friendly_not_understood_not_template_18(fake):
    fake({"parts": [], "english_query": None})
    result = asyncio.run(run_agent(ctx("what is the weather"), object()))
    assert [(s.kind, s.template_id) for s in result.segments] == [("text", None)]
    text = result.segments[0].text
    assert text.startswith("I did not quite understand") and CAPABILITIES[("customer", "en")] in text


def test_the_unclear_answer_follows_the_users_language(fake):
    fake({"parts": [], "english_query": None})
    text = asyncio.run(run_agent(ctx("بسبسبس لولو"), object())).segments[0].text
    assert text.startswith("مفهمتش") and CAPABILITIES[("customer", "ar")] in text
