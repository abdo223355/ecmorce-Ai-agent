"""OutcomeMapper: turns what a tool returned into a decision for the part. One shared default table per role, so
no intent can treat `denied` or `unavailable` differently by accident. A row may override single entries.

The decision is None ("carry on with the next step") or a PartOutcome ("stop here, this is the answer").

Rules kept here, learned from reading the tools:
- denied is already recorded inside the tool (record_denial). The plan never records a second one.
- data_issue comes WITH data. That data is never used.
- ok with a reason (worker: access_window_closed) is its own outcome, not a plain ok.

Template numbers are the D68 set. The wording behind each number is owned by 11 (Milestone 2); only the number is
chosen here. Entries marked "interpretation" are our reading of D68 and need confirming.
"""
from __future__ import annotations

from ..tools import ToolResult
from .state import PartOutcome

Key = tuple[str, str | None]                      # (status, reason); reason None matches any reason of the status

# D68: 11 information unavailable, 14 not found among your recent orders, 16 worker: no such shipment among
# yours, 17 field not available. BKD / P3 is the handoff for a backend that could not answer (R2, Phase 5).
_UNAVAILABLE = PartOutcome(kind="template", template_id=11, handoff_reason="BKD", priority="P3")

DEFAULTS: dict[str, dict[Key, PartOutcome]] = {
    "customer": {
        ("clarify", None): PartOutcome(kind="clarify", reason="invalid_format"),
        ("denied", "not_found_or_not_yours"): PartOutcome(kind="template", template_id=14),
        ("denied", None): PartOutcome(kind="template", template_id=14),
        ("unavailable", None): _UNAVAILABLE,
        ("data_issue", None): _UNAVAILABLE,                                           # interpretation
        ("not_implemented", None): PartOutcome(kind="handoff", handoff_reason="PENDING_OWNER"),
    },
    "worker": {
        ("clarify", None): PartOutcome(kind="clarify", reason="invalid_format"),
        ("denied", "not_found_or_not_yours"): PartOutcome(kind="template", template_id=16),
        ("denied", "field_not_allowed"): PartOutcome(kind="template", template_id=17),
        ("denied", None): PartOutcome(kind="template", template_id=16),
        ("ok", "access_window_closed"): PartOutcome(kind="template", template_id=17),   # interpretation
        ("unavailable", None): _UNAVAILABLE,
        ("data_issue", None): _UNAVAILABLE,                                           # interpretation
        ("not_implemented", None): PartOutcome(kind="handoff", handoff_reason="PENDING_OWNER"),
    },
}


class OutcomeMapper:
    def __init__(self, role: str, overrides: dict[Key, PartOutcome] | None = None):
        self._table = {**DEFAULTS[role], **(overrides or {})}

    def map(self, result: ToolResult) -> PartOutcome | None:
        entry = self._table.get((result.status, result.reason)) or self._table.get((result.status, None))
        if entry is not None:
            return entry
        if result.status == "ok":
            return None                                                               # a plain ok: carry on
        return _UNAVAILABLE                                                           # an unknown failure: be safe
