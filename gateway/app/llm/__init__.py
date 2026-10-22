"""Model adapter (D27 / D100) — the ONLY place that talks to the LLM provider (OpenRouter).

Same pattern as ToolResult: expected LLM failures come back as a typed result, never as a raw
exception to the agent. Real bugs in our own code stay normal exceptions.

Design rules (docs/design/Phase4_Step8_Model_Cost.md D71, Phase 5 D92):
- The timeout is remaining time - margin. The CALLER computes it and passes it in.
- The adapter NEVER re-sends a request (D27 "no live retry"). A failure goes up; the fallback chain
  (template / handoff) is the retry.
- No identity, token, customer_id or worker_id is ever sent to the model (D2, D27).
- Never log prompt or reply text (D108).
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
    """The interface every node depends on. The OpenRouter adapter and the test fake both implement it."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        schema: type[BaseModel],
        timeout_s: float,
        system: str | None = None,
    ) -> LLMResult:
        """Ask the model for structured output.

        prompt     user-side text (already scrubbed; user text sits inside delimiters, D56)
        schema     pydantic model the answer must match; on success result.data is an instance of it
        timeout_s  hard limit for this one call (remaining time - margin, D92)
        system     optional system prompt
        Never raises for expected failures: returns LLMResult(status != "ok", reason=...).
        """
