"""LLM timeout per node (D91 caps, D92 margin + minimum windows). All numbers are the design's INITIAL values."""
from __future__ import annotations

MARGIN_S = 0.5                                        # D92
CAP_S = {"classify": 1.0, "reply": 2.0}               # D91 / Step 2+3 fix 2
MIN_WINDOW_S = {"classify": 0.8, "reply": 1.5}        # D92: below this, do not call the LLM


def timeout_for(node: str, remaining_s: float, reserve_s: float = 0.0) -> float | None:
    """timeout = min(node cap, remaining - margin - reserve). None = below the minimum window:
    the caller must use the template / handoff / code classifier instead of calling the LLM.
    reserve_s = minimum windows of the REQUIRED later steps (e.g. classify reserves reply 1.5 + validate 0.2)."""
    t = min(CAP_S[node], remaining_s - MARGIN_S - reserve_s)
    return t if t >= MIN_WINDOW_S[node] else None
