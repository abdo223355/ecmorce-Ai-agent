"""⑦ AI module — OWNER'S PART: agents, LangGraph state / nodes / edges, routing.

This file only fixes the CONTRACT between the Gateway and your agent, so both sides can be built
independently. Build the real thing step by step with Claude Code (docs/AGENT_ROADMAP.md).

Non-negotiables from the design (details in docs/design/):
- The agent never sees identity, token, customer_id or worker_id (D2, D38). It gets an AgentContext.
- Tools are called by CODE (the plan executor), not by a free LLM tool loop (D37).
- Eligibility / access decisions come from tools (code), never from the LLM (D6).
- Numbers in replies are placeholders rendered by code (D60-A1); user text is data in delimiters (D56).
- The reply passes the 9 validate checks (D66) before it is sent. If it fails → handoff / template.
- Budget: the whole request has 8 s; reply LLM ≤ 2.0 s; classify ≤ 3.0 s (D91, D92; amended from 1.0 s, see llm/budget.py).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..tools import ToolResult


@dataclass(frozen=True)
class AgentContext:
    """Everything the Gateway fixes before the agent starts. Read-only: nodes read it, none can change it."""

    role: Literal["customer", "worker"]
    message: str                     # already scrubbed at ingress (D107) — PII → placeholders
    chat_id: str                     # owner + login session (D65); opaque to the agent
    deadline_at: float               # time.monotonic() value at which the 8 s request budget runs out
    order_refs: dict[str, str] = field(default_factory=dict)  # {order_ref_1} → real id (Step 5 fix 1); code only
    # How many clarification rounds this issue already had. The Gateway sets it from the memory card (D61, Milestone 2);
    # until the memory exists it stays 0. An input, not state: no node writes it.
    clarify_round: int = 0
    # The pending clarification card read from memory (app/memory.py, agent/pending.py), or None. Read-only input.
    pending: dict | None = None

    def remaining(self) -> float:
        """Seconds left in the budget, computed when asked, so no one has to keep a number up to date."""
        return self.deadline_at - time.monotonic()


@dataclass(frozen=True)
class Segment:
    """The answer to ONE part of the user's message. 11 validates and renders each segment on its own (D30, D66)
    and joins them in written order, so a failed segment falls back without losing the others."""

    part_index: int                   # written order: segments are joined by this index
    kind: Literal["template", "text", "clarify"]
    # kind "template": the D68 template to render. kind "text": the FALLBACK template if D66 fails (None if none).
    template_id: int | None = None
    text: str | None = None           # "text" and "clarify": the words, with typed placeholders like {order_id}
    render_values: dict[str, str] = field(default_factory=dict)   # real values; only code substitutes them (D60-A1)
    cited: list[str] = field(default_factory=list)                # doc_id §section@version (D66 check 2)


@dataclass(frozen=True)
class AgentResult:
    """What the agent returns for one turn: one segment per answered part, plus one handoff for the whole turn."""

    segments: list[Segment] = field(default_factory=list)
    handoff_reason: str | None = None  # reason code (D70), e.g. "POL", "BKD", "CMP": the final reason of the turn
    priority: str | None = None        # P1..P4: the most urgent priority of the turn (None while the owner has not answered)
    # CP-44: true only for a takeover or data exposure (or a P1 with no kind): 11 stops sharing the session's data.
    block_session_data: bool = False
    # The neutral summary for the human, built by code (D62): labels and outcomes, never user text. 9 turns it into a ticket.
    handoff_summary: dict | None = None
    # What the nodes measured on this turn (status and time of each model call, never text). Optional and empty by
    # default; only the Gateway reads it, to write one event row per request. It is not part of the HTTP answer.
    telemetry: dict = field(default_factory=dict)
    # What the Gateway should keep for the next turn ({"pending": card} or empty). Not part of the HTTP answer.
    memory: dict = field(default_factory=dict)

    @property
    def cited(self) -> list[str]:
        """Every document cited by any segment, once each (derived, so there is no second copy to disagree)."""
        return list(dict.fromkeys(c for segment in self.segments for c in segment.cited))


class Tools(Protocol):
    """What the Gateway gives your agent. Identity and deadline are bound by the Gateway."""
    async def my_recent_orders(self) -> ToolResult: ...
    async def my_returns(self) -> ToolResult: ...
    async def order_details(self, order_id: str) -> ToolResult: ...
    async def check_eligibility(self, kind: str, order) -> ToolResult: ...
    async def my_shipments_today(self, query: str) -> ToolResult: ...
    async def shipment_details(self, shipment_id: str, requested_fields: list[str]) -> ToolResult: ...
    # Implemented by the RAG (app/rag/retrieve.py).
    # query is the scrubbed user text, in any language, and drives the meaning search.
    # english_query is the English search query from classify and drives the keyword search. It is optional,
    # so the agent can call with query alone until classify exists.
    async def policy_search(self, query: str, english_query: str | None = None) -> ToolResult: ...     # customers
    async def procedure_search(self, query: str, english_query: str | None = None) -> ToolResult: ...  # workers


class AgentRejected(Exception):
    """The role has no agent (D36): the request is rejected, never sent to another agent. The Gateway answers 403."""

    def __init__(self, role: str):
        super().__init__("no agent for this role")
        self.role = role


async def run_agent(ctx: AgentContext, tools: Tools) -> AgentResult:
    """Entry point the Gateway calls for every chat turn: the router picks the agent by role, the agent runs its graph."""
    from .runner import run_agent as _run          # imported here: the nodes import this package, so not at the top
    return await _run(ctx, tools)
