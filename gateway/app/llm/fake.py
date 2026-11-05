"""A scripted adapter for tests and offline work: no network, no API key."""
from __future__ import annotations

from pydantic import BaseModel

from . import LLMAdapter, LLMResult


class FakeAdapter(LLMAdapter):
    """Hands back the queued responses one by one.

    Each item can be a dict (valid output), a BaseModel instance, or a ready-made LLMResult when you
    want to simulate a failure. Every call is recorded in `.calls`.
    """

    def __init__(self, *responses: dict | BaseModel | LLMResult):
        self._queue = list(responses)
        self.calls: list[dict] = []

    async def generate(self, prompt, schema, timeout_s, system=None, max_tokens=None,
                       reasoning_effort=None) -> LLMResult:
        self.calls.append({"prompt": prompt, "schema": schema, "timeout_s": timeout_s, "system": system,
                           "max_tokens": max_tokens, "reasoning_effort": reasoning_effort})
        if not self._queue:
            return LLMResult("unavailable", reason="fake_queue_empty")
        item = self._queue.pop(0)
        if isinstance(item, LLMResult):
            return item
        try:
            data = item if isinstance(item, schema) else schema.model_validate(item)
        except ValueError:
            return LLMResult("bad_output", reason="schema_mismatch")
        return LLMResult("ok", data=data, details={"latency_s": 0.0})
