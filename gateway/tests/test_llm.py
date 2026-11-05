"""LLM adapter tests: no network, no key. Run: pytest gateway/tests"""
import asyncio

import pytest

import httpx
from pydantic import BaseModel

from app.llm import LLMAdapter, LLMResult
from app.llm.fake import FakeAdapter
from app.llm.openrouter import OpenRouterAdapter


class Intent(BaseModel):
    intent: str
    confidence: float


def adapter(handler) -> OpenRouterAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenRouterAdapter(model="test/model", api_key="test-key", base_url="http://llm.test", client=client)


def reply(content: str, status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def run(coro):
    return asyncio.run(coro)


def gen(a, timeout=1.0):
    return run(a.generate("hi", Intent, timeout))


def test_ok_returns_validated_instance_and_tokens():
    r = gen(adapter(lambda req: reply('{"intent":"C2","confidence":0.9}')))
    assert r.ok and isinstance(r.data, Intent) and r.data.intent == "C2"
    assert r.details["tokens_in"] == 10


def test_request_has_schema_and_bearer_key_but_no_other_secrets():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        seen["body"] = req.read().decode()
        return reply('{"intent":"C1","confidence":1}')

    run(adapter(handler).generate("hello", Intent, 1.0, system="sys"))
    assert seen["auth"] == "Bearer test-key"
    assert '"json_schema"' in seen["body"] and '"sys"' in seen["body"]


def test_every_request_demands_a_no_retention_endpoint():
    import json
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.read())
        return reply('{"intent":"C1","confidence":1}')

    run(adapter(handler).generate("hello", Intent, 1.0))
    assert seen["body"]["provider"] == {"data_collection": "deny", "zdr": True}      # D111


def test_http_errors_map_to_statuses():
    assert gen(adapter(lambda r: httpx.Response(429))).status == "rate_limited"
    assert gen(adapter(lambda r: httpx.Response(401))).reason == "auth_failed"
    assert gen(adapter(lambda r: httpx.Response(500))).status == "unavailable"


def test_bad_json_and_schema_mismatch_are_bad_output():
    assert gen(adapter(lambda r: reply("not json"))).status == "bad_output"
    assert gen(adapter(lambda r: reply('{"intent":"C2"}'))).status == "bad_output"
    assert gen(adapter(lambda r: httpx.Response(200, json={"weird": 1}))).status == "bad_output"


def test_timeout_is_a_result_not_an_exception():
    async def slow(req):
        await asyncio.sleep(1)
        return reply('{"intent":"C1","confidence":1}')

    r = gen(adapter(slow), timeout=0.05)
    assert r.status == "timeout"


def test_network_error_is_unavailable():
    def boom(req):
        raise httpx.ConnectError("down")

    assert gen(adapter(boom)).status == "unavailable"


def test_no_retry_one_request_only():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500)

    gen(adapter(handler))
    assert len(calls) == 1          # D27: the adapter never re-sends


def test_missing_key_or_model_is_unavailable_without_calling_out():
    a = OpenRouterAdapter(model="", api_key="")
    assert run(a.generate("x", Intent, 1.0)).reason == "llm_not_configured"


def test_fake_and_real_share_the_interface():
    assert issubclass(FakeAdapter, LLMAdapter) and issubclass(OpenRouterAdapter, LLMAdapter)
    fake = FakeAdapter({"intent": "C3", "confidence": 0.5}, LLMResult("timeout", reason="x"))
    first, second = run(fake.generate("a", Intent, 1.0)), run(fake.generate("b", Intent, 1.0))
    assert first.ok and first.data.intent == "C3" and second.status == "timeout"
    assert [c["prompt"] for c in fake.calls] == ["a", "b"]


def test_model_per_node_precedence(monkeypatch):
    from dataclasses import replace
    from app.config import settings
    from app.llm.models import MODELS
    monkeypatch.delenv("LLM_MODEL_CLASSIFY", raising=False)
    s = replace(settings, llm_model="")
    assert s.model_for("classify") == MODELS["classify"]          # file default
    assert replace(s, llm_model="m/all").model_for("reply") == "m/all"   # LLM_MODEL beats the file
    monkeypatch.setenv("LLM_MODEL_CLASSIFY", "m/small")
    assert replace(s, llm_model="m/all").model_for("classify") == "m/small"  # per-node env beats both
    assert s.model_for("unknown_node") == ""


def test_budget_caps_margin_and_minimum_window():
    from app.llm.budget import timeout_for
    assert timeout_for("classify", 8.0) == 3.0                  # cap (amended from 1.0, night 80)
    assert timeout_for("reply", 8.0) == 2.5                  # cap (amended from 2.0, night 98)
    assert timeout_for("reply", 2.2) == pytest.approx(1.7)      # remaining - 0.5 margin
    assert timeout_for("reply", 1.9) is None                    # 1.4 < 1.5 minimum
    assert timeout_for("classify", 2.9, reserve_s=1.7) is None  # 0.7 < 0.8 minimum


def test_ask_uses_timeout_from_budget_and_skips_call_below_minimum():
    from app.llm import client
    fake = FakeAdapter({"intent": "C2", "confidence": 0.8})
    client.set_adapter(fake)
    try:
        r = run(client.ask("classify", "hi", Intent, remaining_s=8.0))
        assert r.ok and fake.calls[0]["timeout_s"] == 2.4
        low = run(client.ask("reply", "hi", Intent, remaining_s=1.0))
        assert low.status == "timeout" and low.reason == "below_minimum_window"
        assert len(fake.calls) == 1                     # the second call never reached the adapter
    finally:
        client.set_adapter(None)


def test_max_tokens_goes_in_the_request_only_when_given_and_a_cut_answer_is_never_used():
    import json
    seen = []

    def handler(req):
        seen.append(json.loads(req.read()))
        return httpx.Response(200, json={"choices": [{"finish_reason": "length",
                                                       "message": {"content": '{"intent":"C1","confidence":0.'}}]})

    cut = run(adapter(handler).generate("hi", Intent, 1.0, None, 50))
    assert seen[0]["max_tokens"] == 50 and cut.status == "bad_output" and cut.reason == "truncated"
    run(adapter(lambda r: seen.append(json.loads(r.read())) or reply('{"intent":"C1","confidence":1}')).generate("hi", Intent, 1.0))
    assert "max_tokens" not in seen[1]


def test_ask_applies_the_node_token_cap():
    from app.llm import budget, client
    f = FakeAdapter({"intent": "C1", "confidence": 1.0}, {"intent": "C1", "confidence": 1.0})
    client.set_adapter(f)
    saved = dict(budget.MAX_TOKENS)
    budget.MAX_TOKENS["reply"] = 123
    try:
        run(client.ask("reply", "p", Intent, remaining_s=8.0))
        run(client.ask("classify", "p", Intent, remaining_s=8.0))
    finally:
        budget.MAX_TOKENS.update(saved)
        client.set_adapter(None)
    assert f.calls[0]["max_tokens"] == 123 and f.calls[1]["max_tokens"] is None


def test_no_node_is_capped_by_default():
    from app.llm import budget
    assert budget.MAX_TOKENS == {"classify": None, "reply": None}       # see the comment in budget.py


def test_the_reasoning_effort_is_sent_only_when_given():
    import json
    seen = []

    def handler(req):
        seen.append(json.loads(req.read()))
        return reply('{"intent":"C1","confidence":1}')

    run(adapter(handler).generate("hi", Intent, 1.0, None, None, "none"))
    run(adapter(handler).generate("hi", Intent, 1.0))
    assert seen[0]["reasoning"] == {"effort": "none"} and "reasoning" not in seen[1]


def test_ask_passes_each_nodes_reasoning_effort_and_the_defaults_are_pinned():
    from app.llm import budget, client
    f = FakeAdapter({"intent": "C1", "confidence": 1.0}, {"intent": "C1", "confidence": 1.0})
    client.set_adapter(f)
    try:
        run(client.ask("reply", "p", Intent, remaining_s=8.0))
        run(client.ask("classify", "p", Intent, remaining_s=8.0))
    finally:
        client.set_adapter(None)
    assert f.calls[0]["reasoning_effort"] == "none" and f.calls[1]["reasoning_effort"] == "none"
    assert budget.REASONING_EFFORT == {"classify": "none", "reply": "none"}


def test_the_chosen_models_and_the_full_path_budget_are_pinned():
    from app.llm import budget
    from app.llm.models import MODELS
    assert MODELS["classify"] == "anthropic/claude-haiku-5.5" and MODELS["reply"] == "deepseek/deepseek-v4.1-flash"
    assert budget.CAP_S == {"classify": 3.0, "reply": 2.5}
    # classify cap + reply cap + validate (0.2) + the safety margin must leave real room for the backend and the rest.
    # Lowered from 2.0 s to 1.5 s with the reply cap at 2.5 s (his decision, night 98): the measured whole request was
    # p95 3.8 s and max 4.15 s, so the backend and the tools use well under a second.
    left = 8.0 - budget.CAP_S["classify"] - budget.CAP_S["reply"] - 0.2 - budget.MARGIN_S
    assert left >= 1.5, left
    # Worst case with the retry (night 119): two classify attempts, the plan (0.3 s), one reply attempt, the margin.
    worst = (budget.MAX_ATTEMPTS * budget.ATTEMPT_CAP_S["classify"] + 0.3 + budget.ATTEMPT_CAP_S["reply"]
             + budget.MARGIN_S)
    assert budget.ATTEMPT_CAP_S == {"classify": 2.4, "reply": 2.0} and budget.MAX_ATTEMPTS == 2 and worst <= 8.0, worst


# ---------- one retry after a timeout (night 119) ----------
class SlowThenGood:
    """Each queued item is (seconds the call "takes" on a fake clock, response)."""
    def __init__(self, clock, *steps):
        self.clock, self.steps, self.calls = clock, list(steps), []

    async def generate(self, prompt, schema, timeout_s, system=None, max_tokens=None, reasoning_effort=None):
        self.calls.append(timeout_s)
        seconds, response = self.steps.pop(0)
        self.clock[0] += seconds
        return response


@pytest.fixture
def clock(monkeypatch):
    from app.llm import client
    now = [100.0]
    monkeypatch.setattr(client.time, "monotonic", lambda: now[0])
    yield now
    client.set_adapter(None)


def _timeout():
    return LLMResult("timeout", reason="deadline_exceeded", details={"latency_s": 2.4})


def _good():
    return LLMResult("ok", data=Intent(intent="C2", confidence=0.8), details={"latency_s": 1.0})


def test_a_timeout_is_tried_once_more_and_the_second_answer_is_used(clock):
    from app.llm import client
    adapter = SlowThenGood(clock, (2.4, _timeout()), (1.0, _good()))
    client.set_adapter(adapter)
    r = run(client.ask("classify", "x", Intent, remaining_s=8.0))
    assert r.ok and r.details["attempts"] == 2 and adapter.calls == [2.4, 2.4]


def test_two_timeouts_end_as_a_timeout_after_two_attempts(clock):
    from app.llm import client
    adapter = SlowThenGood(clock, (2.4, _timeout()), (2.4, _timeout()))
    client.set_adapter(adapter)
    r = run(client.ask("classify", "x", Intent, remaining_s=8.0))
    assert r.status == "timeout" and r.details["attempts"] == 2 and len(adapter.calls) == 2


def test_no_retry_when_the_time_left_is_too_short(clock):
    from app.llm import client
    adapter = SlowThenGood(clock, (2.4, _timeout()), (1.0, _good()))
    client.set_adapter(adapter)
    r = run(client.ask("classify", "x", Intent, remaining_s=3.5, reserve_s=0.0))     # 3.5 - 2.4 = 1.1 left, minus 0.5 margin = 0.6 < 0.8
    assert r.status == "timeout" and len(adapter.calls) == 1


@pytest.mark.parametrize("status", ["rate_limited", "bad_output", "unavailable"])
def test_only_a_timeout_is_retried(clock, status):
    from app.llm import client
    adapter = SlowThenGood(clock, (0.5, LLMResult(status, reason="x")), (1.0, _good()))
    client.set_adapter(adapter)
    r = run(client.ask("classify", "x", Intent, remaining_s=8.0))
    assert r.status == status and len(adapter.calls) == 1 and "attempts" not in r.details


def test_a_first_try_that_works_makes_one_call_and_adds_no_attempts_key(clock):
    from app.llm import client
    adapter = SlowThenGood(clock, (1.0, _good()))
    client.set_adapter(adapter)
    r = run(client.ask("reply", "x", Intent, remaining_s=8.0))
    assert r.ok and "attempts" not in r.details and adapter.calls == [2.0]
