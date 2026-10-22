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
    assert timeout_for("classify", 8.0) == 1.0                  # cap
    assert timeout_for("reply", 8.0) == 2.0
    assert timeout_for("reply", 2.2) == pytest.approx(1.7)      # remaining - 0.5 margin
    assert timeout_for("reply", 1.9) is None                    # 1.4 < 1.5 minimum
    assert timeout_for("classify", 2.9, reserve_s=1.7) is None  # 0.7 < 0.8 minimum


def test_ask_uses_timeout_from_budget_and_skips_call_below_minimum():
    from app.llm import client
    fake = FakeAdapter({"intent": "C2", "confidence": 0.8})
    client.set_adapter(fake)
    try:
        r = run(client.ask("classify", "hi", Intent, remaining_s=8.0))
        assert r.ok and fake.calls[0]["timeout_s"] == 1.0
        low = run(client.ask("reply", "hi", Intent, remaining_s=1.0))
        assert low.status == "timeout" and low.reason == "below_minimum_window"
        assert len(fake.calls) == 1                     # the second call never reached the adapter
    finally:
        client.set_adapter(None)
