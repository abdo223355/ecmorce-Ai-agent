"""Node 2: safety_gate. Code only, no model call. Reads what classify wrote and gives the overall safety verdict.

- classify failed (classify_ok False): the gate writes nothing. The request is not judged safe and not judged P1;
  the edge after this node sends it to the code classifier (D37 step 2, N8). A classify failure is not a user attempt.
- any part is P1 (its safety field, or its intent is C7): safety_flag P1, handoff_reason SAFE, priority P1. Every part stops and the request goes to the
  P1 handoff only (D37 step 2, CP-44; his decision, night 45). No backend call happens before this node.
- otherwise: safety_flag SAFE.

The escalation flags (D42) are NOT read here: they are routed by the plan, per part.
"""
from __future__ import annotations

import json
import logging

from .state import AgentState

log = logging.getLogger("gateway.agent.safety_gate")

# An intent that is a safety report by itself. If classify returns it with safety SAFE, the two fields disagree and
# the gate sides with safety (his decision, night 53). Customer only: the worker side has no such intent.
P1_INTENTS = frozenset({"C7"})


def _is_p1(state: AgentState) -> bool:
    return state.any_p1 or any(p.intent is not None and p.intent.id in P1_INTENTS for p in state.parts)


def safety_gate_node(state: AgentState) -> dict:
    """Needs only the state: the verdict depends on nothing fixed per request. Never raises."""
    if not state.classify_ok:
        log.info(json.dumps({"node": "safety_gate", "verdict": "classify_failed"}))
        return {}
    if _is_p1(state):
        log.info(json.dumps({"node": "safety_gate", "verdict": "P1"}))
        return {"safety_flag": "P1", "handoff_reason": "SAFE", "priority": "P1"}
    log.info(json.dumps({"node": "safety_gate", "verdict": "SAFE"}))
    return {"safety_flag": "SAFE"}
