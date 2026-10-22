"""Tools the agent can use (D43). CODE calls them (plan executor, D37) — never a free LLM tool loop.

Every tool returns a ToolResult, never raises to the agent:
- ok              → data is a tool view (owner ids stripped, D38)
- clarify         → ask the user (e.g. malformed order id: POL-AGV-001 §2, not a denial)
- denied          → neutral reply (D45 / templates 16–17); the denial is already recorded (N2)
- unavailable     → backend down / out of time → status template or BKD handoff (POL-BDR-001)
- data_issue      → inconsistent backend data → escalate, never guess (POL-AGV-001 §3–4)
- not_implemented → this tool belongs to a later milestone

Customer tools: my_recent_orders, order_details, check_eligibility*, policy_search*
Worker tools:   my_shipments_today, shipment_details, procedure_search*
(* check_eligibility = ⑤ Business Rules, Milestone 2 · policy_search / procedure_search = YOUR RAG)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["ok", "clarify", "denied", "unavailable", "data_issue", "not_implemented"]


@dataclass(frozen=True)
class ToolResult:
    status: Status
    data: Any = None
    reason: str | None = None          # machine-readable code, e.g. "invalid_order_id_format"
    details: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"
