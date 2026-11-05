"""Node 5: handoff. Code only, no model call. Decides the ONE handoff of the turn and what goes with it.

It is not the ticket (that is 9, Milestone 2). It prepares the content of the handoff:
- the final reason and priority, derived once from every source: the safety gate (P1) and each part's outcome.
  Rule (a design choice, no policy source): the most urgent priority wins (None counts as least urgent), a tie goes
  to the earlier part, and a P1 from the gate comes first;
- the acknowledgement template, one for the whole turn: 8 for a P1, else 5 for a customer and 6 for a worker. Parts
  whose outcome was only that acknowledgement lose their own template so it is not shown twice;
- block_session_data (CP-44): true only for takeover or exposure, or for a P1 with no flag (the stricter case);
  a physical danger gets the emergency line without blocking the session's data (N1);
- the summary for the human, built by code from labels and outcomes (D62, PRC-HOF-001 §3): never user text, never a
  render value. A product clue (D61) is kept only if it is short and plain. An order number is shown only when a tool
  confirmed it is the user's own; otherwise the summary only says a number was mentioned (audit #22).

Not here: after hours (template 7), the worker "what to do meanwhile" procedure, the denial threshold, the ticket
and its outbox, Dispatch routing, the classify-failure path (11, Milestone 2). The node never raises, and the same
input always gives the same output (9 will use it as a de-duplication key). No message text is logged (D108).
"""
from __future__ import annotations

import json
import logging
import re

from . import AgentContext
from .classify import CUSTOMER, WORKER
from .safety_gate import P1_INTENTS
from .state import (NO_DATA_FLAGS, AgentState, Handoff, HandoffReason, HandoffSummary, Part, PartOutcome,
                    PartSummary, Priority)

log = logging.getLogger("gateway.agent.handoff")

ACK_BY_ROLE = {"customer": 5, "worker": 6}      # D68 5 and 6
ACK_P1 = 8                                      # D68 8: P1 emergency
ACK_TEMPLATES = frozenset({5, 6, 8})
_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
_LEAST_URGENT = 9

# What a part's template means to the human, as a fixed word (D68 numbers).
TEMPLATE_WORD = {1: "answered", 2: "answered", 3: "answered", 5: "handoff_requested", 6: "handoff_requested",
                 8: "safety_report", 9: "out_of_scope", 10: "outside_v1", 11: "information_unavailable",
                 12: "policy_not_confirmed", 14: "not_found", 16: "not_found", 17: "field_not_available",
                 18: "could_not_finish"}


def _is_p1_part(part: Part) -> bool:
    return part.safety == "P1" or (part.intent is not None and part.intent.id in P1_INTENTS)


def _word(part: Part) -> str:
    o = part.outcome
    if _is_p1_part(part):
        return "safety_report"
    if o is None:
        return "not_processed"
    if o.kind == "clarify":
        return "needs_clarification"
    if o.kind == "reply":
        return "policy_answer" if o.sections else "answered"
    if o.kind == "handoff":
        return "handoff_requested"
    return TEMPLATE_WORD.get(o.template_id, "answered")


def _safe_clue(value: object) -> str | None:
    """A product clue (D61) is kept only if it is short and plain: no long digit runs, no addresses or links."""
    if not isinstance(value, str):
        return None
    clue = value.strip()
    if not clue or len(clue) > 40 or re.search(r"\d{6,}", clue) or "@" in clue or "http" in clue.casefold():
        return None
    return clue


def _label(role: str, part: Part) -> str | None:
    if part.intent is None:
        return None
    return (CUSTOMER if role == "customer" else WORKER).intents.get(part.intent.id, part.intent.id)


def _candidates(state: AgentState) -> list[tuple[int, HandoffReason, Priority | None]]:
    found: list[tuple[int, HandoffReason, Priority | None]] = []
    if state.safety_flag == "P1":
        found.append((-1, "SAFE", "P1"))                                  # the gate's P1 comes before any part
    for part in state.parts:
        o = part.outcome
        if o is not None and o.handoff_reason is not None:
            found.append((part.index, o.handoff_reason, o.priority))
    return found


def _block_session_data(state: AgentState) -> bool:
    if state.safety_flag != "P1":
        return False
    p1_parts = [p for p in state.parts if _is_p1_part(p)]
    if not p1_parts:
        return True                                                       # P1 with nothing to tell the kind: the stricter case
    return any(p.p1_flag is None or p.p1_flag in NO_DATA_FLAGS for p in p1_parts)


def _summary(state: AgentState, ctx: AgentContext) -> HandoffSummary:
    mentioned = {ctx.order_refs.get(ref) for p in state.parts if p.intent
                 for ref in [p.intent.arguments.get("order_ref")] if isinstance(ref, str)} - {None}
    confirmed = {r.argument for r in state.tool_results
                 if r.tool == "order_details" and r.result.ok and r.argument in mentioned}
    errors = sorted({f"{r.tool}:{r.result.status}:{r.result.reason or ''}" for r in state.tool_results
                     if not r.result.ok})
    policies = list(dict.fromkeys(c for p in state.parts if p.outcome for c in p.outcome.cited))
    parts = [PartSummary(part_index=p.index, intent=p.intent.id if p.intent else None, label=_label(ctx.role, p),
                         outcome=_word(p), p1_flag=p.p1_flag,
                         clue=_safe_clue(p.intent.arguments.get("item_clue")) if p.intent else None)
             for p in state.parts]
    return HandoffSummary(parts=parts, error_codes=errors, policies=policies, verified_order_ids=sorted(confirmed),
                          order_number_mentioned_unverified=bool(mentioned - confirmed))


def _without_ack_template(part: Part) -> Part:
    """A part that was only an acknowledgement drops its template: the turn shows the acknowledgement once."""
    o = part.outcome
    if o is not None and o.kind == "template" and o.template_id in ACK_TEMPLATES:
        return part.model_copy(update={"outcome": o.model_copy(update={"kind": "handoff", "template_id": None})})
    return part


def handoff_node(state: AgentState, ctx: AgentContext) -> dict:
    candidates = _candidates(state)
    if not candidates:
        return {}                                                         # nothing to hand off: the node adds nothing
    _, reason, priority = min(candidates, key=lambda c: (_RANK.get(c[2], _LEAST_URGENT), c[0]))
    block = _block_session_data(state)
    handoff = Handoff(reason=reason, priority=priority,
                      acknowledgement_template=ACK_P1 if state.safety_flag == "P1" else ACK_BY_ROLE[ctx.role],
                      block_session_data=block, summary=_summary(state, ctx))
    log.info(json.dumps({"node": "handoff", "reason": reason, "priority": priority, "parts": len(state.parts),
                         "ack": handoff.acknowledgement_template, "block_session_data": block}))
    return {"parts": [_without_ack_template(p) for p in state.parts], "handoff": handoff,
            "handoff_reason": reason, "priority": priority}
