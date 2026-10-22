"""⑦ AI module — YOUR PART (عبدالرحمن): agents, LangGraph state / nodes / edges, routing.

This file only fixes the CONTRACT between the Gateway and your agent, so both sides can be built
independently. Build the real thing step by step with Claude Code (docs/AGENT_ROADMAP.md).

Non-negotiables from the design (details in docs/design/):
- The agent never sees identity, token, customer_id or worker_id (D2, D38). It gets an AgentContext.
- Tools are called by CODE (the plan executor), not by a free LLM tool loop (D37).
- Eligibility / access decisions come from tools (code), never from the LLM (D6).
- Numbers in replies are placeholders rendered by code (D60-A1); user text is data in delimiters (D56).
- The reply passes the 9 validate checks (D66) before it is sent. If it fails → handoff / template.
- Budget: the whole request has 8 s; reply LLM ≤ 2.0 s; classify ≤ 1.0 s (D91, D92).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..tools import ToolResult


@dataclass(frozen=True)
class AgentContext:
    role: Literal["customer", "worker"]
    message: str                     # already scrubbed at ingress (D107) — PII → placeholders
    chat_id: str                     # owner + login session (D65); opaque to the agent
    remaining_s: float               # time left in the 8 s budget
    order_refs: dict[str, str] = field(default_factory=dict)  # {order_ref_1} → real id (Step 5 fix 1); code only


@dataclass(frozen=True)
class AgentResult:
    kind: Literal["reply", "clarify", "handoff", "template"]
    text: str | None = None           # reply text with placeholders, e.g. "{days_left}"
    placeholders: dict[str, str] = field(default_factory=dict)
    template_id: int | None = None    # one of the 19 templates (D68)
    handoff_reason: str | None = None # reason code (D70), e.g. "POL", "BKD", "CMP"
    priority: str | None = None       # P1..P4
    cited: list[str] = field(default_factory=list)  # doc_id §section@version used (D66 check 2)


class Tools(Protocol):
    """What the Gateway gives your agent. Identity and deadline are bound by the Gateway."""
    async def my_recent_orders(self) -> ToolResult: ...
    async def order_details(self, order_id: str) -> ToolResult: ...
    async def check_eligibility(self, kind: str, order) -> ToolResult: ...
    async def my_shipments_today(self, query: str) -> ToolResult: ...
    async def shipment_details(self, shipment_id: str, requested_fields: list[str]) -> ToolResult: ...
    async def policy_search(self, query: str) -> ToolResult: ...      # your RAG (customer audience)
    async def procedure_search(self, query: str) -> ToolResult: ...   # your RAG (worker audience)


async def run_agent(ctx: AgentContext, tools: Tools) -> AgentResult:
    """Entry point the Gateway calls for every chat turn. Replace with your LangGraph graph."""
    raise NotImplementedError("Agent not built yet — see docs/AGENT_ROADMAP.md")
