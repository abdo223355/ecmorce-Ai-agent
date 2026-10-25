"""Time limits for LLM calls, per node. The numbers are the design's starting values (D91, D92)."""
from __future__ import annotations

MARGIN_S = 0.5                                        # safety margin kept free at the end of the request
CAP_S = {"classify": 1.0, "reply": 2.0}               # longest a node may wait
MIN_WINDOW_S = {"classify": 0.8, "reply": 1.5}        # below this there is no point calling the model


def timeout_for(node: str, remaining_s: float, reserve_s: float = 0.0) -> float | None:
    """How long this node may wait: min(node cap, remaining - margin - reserve).

    Returns None when what is left is under the node's minimum window. The caller should then use a
    template, a handoff or the code classifier instead of calling the model.
    reserve_s is for later steps that still need time (classify, for example, has to leave room for the reply).
    """
    t = min(CAP_S[node], remaining_s - MARGIN_S - reserve_s)
    return t if t >= MIN_WINDOW_S[node] else None
