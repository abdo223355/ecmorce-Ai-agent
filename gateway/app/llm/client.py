"""The ONLY thing the agent nodes import from llm/.

    from app.llm.client import ask
    result = await ask("classify", prompt, MySchema, remaining_s=ctx.remaining_s, system=SYSTEM_PROMPT)
    if not result.ok: ...   # timeout / rate_limited / bad_output / unavailable -> fallback chain (D27)
    result.data             # a MySchema instance
"""
from __future__ import annotations

from functools import lru_cache

import httpx
from pydantic import BaseModel

from ..config import settings
from . import LLMAdapter, LLMResult
from .budget import timeout_for
from .errors import failure
from .openrouter import OpenRouterAdapter

_override: LLMAdapter | None = None   # tests / offline runs: set_adapter(FakeAdapter(...))


def set_adapter(adapter: LLMAdapter | None) -> None:
    global _override
    _override = adapter


@lru_cache(maxsize=1)
def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=None)   # one shared connection pool; deadlines come from budget.py via wait_for


@lru_cache(maxsize=None)
def _adapter_for(node: str) -> LLMAdapter:
    return OpenRouterAdapter(model=settings.model_for(node), client=_http())


def get_llm(node: str) -> LLMAdapter:
    return _override or _adapter_for(node)


async def ask(node: str, prompt: str, schema: type[BaseModel], remaining_s: float,
              system: str | None = None, reserve_s: float = 0.0) -> LLMResult:
    """Pick the node's model, compute the timeout (D92), call once (no retry, D27)."""
    timeout_s = timeout_for(node, remaining_s, reserve_s)
    if timeout_s is None:
        return failure("timeout", "below_minimum_window")      # no call made
    return await get_llm(node).generate(prompt, schema, timeout_s, system)
