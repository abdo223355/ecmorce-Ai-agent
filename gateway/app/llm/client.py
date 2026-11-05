"""The only thing the agent nodes need to import from llm/.

    from app.llm.client import ask
    result = await ask("classify", prompt, MySchema, remaining_s=ctx.remaining_s, system=SYSTEM_PROMPT)
    if not result.ok: ...   # timeout / rate_limited / bad_output / unavailable -> fallback chain
    result.data             # a MySchema instance
"""
from __future__ import annotations

import time
from dataclasses import replace
from functools import lru_cache

import httpx
from pydantic import BaseModel

from ..config import settings
from . import LLMAdapter, LLMResult
from .budget import ATTEMPT_CAP_S, MAX_ATTEMPTS, MAX_TOKENS, REASONING_EFFORT, timeout_for
from .errors import failure
from .openrouter import OpenRouterAdapter

_override: LLMAdapter | None = None   # tests and offline runs: set_adapter(FakeAdapter(...))


def set_adapter(adapter: LLMAdapter | None) -> None:
    global _override
    _override = adapter


@lru_cache(maxsize=1)
def _http() -> httpx.AsyncClient:
    # One shared connection pool. No httpx timeout: the deadline comes from budget.py through wait_for.
    return httpx.AsyncClient(timeout=None)


@lru_cache(maxsize=None)
def _adapter_for(node: str) -> LLMAdapter:
    return OpenRouterAdapter(model=settings.model_for(node), client=_http())


def get_llm(node: str) -> LLMAdapter:
    return _override or _adapter_for(node)


async def ask(node: str, prompt: str, schema: type[BaseModel], remaining_s: float,
              system: str | None = None, reserve_s: float = 0.0) -> LLMResult:
    """Pick the node's model, work out the timeout, and call it. A call that TIMES OUT is tried once more while the
    request still has time (the retry lives here, not in the adapter). Any other failure (rate limit, bad output,
    provider error) is returned at once: asking again would not help. details["attempts"] says how many calls were made."""
    left = remaining_s
    attempts = 0
    while True:
        timeout_s = timeout_for(node, left, reserve_s, cap_s=ATTEMPT_CAP_S[node])
        if timeout_s is None:
            if attempts == 0:
                return failure("timeout", "below_minimum_window")      # not enough time, so no call is made
            return replace(result, details={**result.details, "attempts": attempts})   # no time for another try
        started = time.monotonic()
        attempts += 1
        result = await get_llm(node).generate(prompt, schema, timeout_s, system, MAX_TOKENS.get(node),
                                              REASONING_EFFORT.get(node))
        left -= time.monotonic() - started
        if result.status != "timeout" or attempts >= MAX_ATTEMPTS:
            return replace(result, details={**result.details, "attempts": attempts}) if attempts > 1 else result
