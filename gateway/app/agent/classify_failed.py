"""Interim for the classify-failure path, until the code classifier R1 of 11 (Milestone 2) exists.

When classify could not be trusted (timeout, rate limit, bad output, an answer the code rejected) the request must not go
on to the plan (D37 step 2). The design sends it to 11's full code classifier; that is not built, so this node gives the
safe answer the design names for a failure that is not a user attempt (N8, F1):
- a customer gets template 15 (classification failure: always carries the emergency line and an offer of a human);
- a worker gets template 6 and a handoff PENDING_OWNER (the owner question for an unrecognised worker message, D70).
It writes one synthetic part (no intent, no verdict) so the same assemble and handoff nodes finish the turn.
Replace this node by the call to R1 when 11 exists. No message text is read or logged.
"""
from __future__ import annotations

import json
import logging

from . import AgentContext
from .state import AgentState, Part, PartOutcome

log = logging.getLogger("gateway.agent.classify_failed")

CUSTOMER_FAILURE_TEMPLATE = 15


def classify_failed_node(state: AgentState, ctx: AgentContext) -> dict:
    if ctx.role == "worker":
        outcome = PartOutcome(kind="template", template_id=6, handoff_reason="PENDING_OWNER")
    else:
        outcome = PartOutcome(kind="template", template_id=CUSTOMER_FAILURE_TEMPLATE)
    log.info(json.dumps({"node": "classify_failed", "role": ctx.role}))
    return {"parts": [Part(index=0, safety="SAFE", outcome=outcome)]}
