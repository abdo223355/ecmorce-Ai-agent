"""Scripted adapter for tests and offline development: no network, no key."""
from __future__ import annotations

from pydantic import BaseModel

from . import LLMAdapter, LLMResult


class FakeAdapter(LLMAdapter):
    """Returns the queued responses in order. Each item is a dict (valid output), a ready LLMResult
    (to simulate a failure), or a BaseModel instance. Records every call in `.calls`."""

    def __init__(self, *responses: dict | BaseModel | LLMResult):
        self._queue = list(responses)
        self.calls: list[dict] = []

    async def generate(self, prompt, schema, timeout_s, system=None) -> LLMResult:
        self.calls.append({"prompt": prompt, "schema": schema, "timeout_s": timeout_s, "system": system})
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
