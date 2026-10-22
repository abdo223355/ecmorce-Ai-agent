"""⑩ Audit — Milestone 1 version: structured log lines only.

Milestone 2 replaces this with sync rows in the Gateway DB (D15), the 3-denials-per-login-session
rule (→ AUTH/P2 handoff) and the coalesced invalid-token counter (D88).
The function names stay the same, so tool code does not change.
"""
from __future__ import annotations

import json
import logging

from .identity import Identity

log = logging.getLogger("gateway.audit")


def record_denial(identity: Identity, kind: str, requested_id: str | None) -> None:
    """Shared denial recorder (N2): used by agent tools AND template paths.

    kind: "record_not_found_or_not_yours" | "field_denied" | "query_denied"
    requested_id is kept on denial rows (Phase 5 Step 5 fix 9). No PII, no message text (D108).
    """
    log.warning(json.dumps({"event": "denial", "role": identity.role, "subject": identity.subject_id,
                            "session": identity.session_id, "kind": kind, "requested_id": requested_id}))
