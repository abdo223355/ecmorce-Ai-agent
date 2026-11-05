"""LLM adapter: the single place that talks to the model provider (OpenRouter).

It follows the same pattern as ToolResult. Failures we expect (timeout, rate limit, bad JSON) come back as
a typed result instead of an exception, so the agent never has to catch provider-specific errors.
Real bugs in our own code are still ordinary exceptions.

Rules this module sticks to (see docs/design, D27 / D71 / D92):
- The caller works out the timeout (remaining time minus a margin) and passes it in.
- No retry inside the adapter. A failure goes up and the fallback chain (template, handoff) takes over.
- Identity, tokens and customer or worker ids are never sent to the model.
- Prompt and reply text are never logged.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

LLMStatus = Literal["ok", "timeout", "rate_limited", "bad_output", "unavailable"]


@dataclass(frozen=True)
class LLMResult:
    status: LLMStatus
    data: Any = None                    # the validated `schema` instance when status == "ok"
    reason: str | None = None           # machine-readable code, e.g. "invalid_json"
    details: dict = field(default_factory=dict)   # e.g. {"latency_s": 0.8, "tokens_in": 120}

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class LLMAdapter(ABC):
    """What the agent nodes depend on. Both the OpenRouter adapter and the test fake implement it."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        schema: type[BaseModel],
        timeout_s: float,
        system: str | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMResult:
        """Ask the model for structured output.

        prompt     the user-side text (already scrubbed, user text sits inside delimiters)
        schema     pydantic model the answer must match; on success result.data is an instance of it
        timeout_s  hard limit for this one call
        system     optional system prompt
        max_tokens optional cap on the answer length (D59). An answer cut by the cap is a bad_output, never a
                   half-sentence passed on as if it were complete.
        reasoning_effort  optional OpenRouter reasoning effort ("none", "low", ...). A model that does not reason
                   ignores it. "none" turns the hidden thinking off (it cut reply time by half or more, night 76).

        Expected failures never raise: they return LLMResult(status != "ok", reason=...).
        """
