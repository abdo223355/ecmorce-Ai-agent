"""Time limits for LLM calls, per node. The numbers are the design's starting values (D91, D92)."""
from __future__ import annotations

MARGIN_S = 0.5                                        # safety margin kept free at the end of the request
# Longest a node may wait. AMENDED (night 80, his decision) from D91/D92's classify 1.0 s: in the container no model got
# its p95 under 1.0 s (haiku-5.5: p50 1.6 s, p95 about 3 s), and the code fast path skips the classify for simple
# messages. The reply cap was AMENDED too (night 98, his decision, option A) from 2.0 s to 2.5 s: in the container 30 calls of
# deepseek-v4.1-flash with reasoning off had p50 1.26 s but p95 2.37 s, so 2.0 s cut about 1 call in 4 on slow ones.
CAP_S = {"classify": 3.0, "reply": 2.5}
# One attempt waits at most this long, and a call that TIMES OUT is tried once more if the request still has time
# (night 119, his choice 1, then the go-ahead to build). Numbers from the events table (489 classify and 86 reply calls that succeeded):
# classify p50 1.27 s, p90 2.05, p95 2.34, p99 2.69; reply p50 1.24, p90 1.96, p95 2.12, p99 2.21. Timeouts were about 3 %
# of classify calls: a call still silent after p95 is usually stuck at the provider, so a fresh try is the better bet.
# A first limit of 2.0 s for classify would have cut about 10 % of good calls, so it sits just above p95. Worst case
# (two classify attempts, plan, reply attempt): 2.4 + 2.4 + 0.3 + 2.5 = 7.6 s, inside the 8 s budget.
ATTEMPT_CAP_S = {"classify": 2.4, "reply": 2.0}
MAX_ATTEMPTS = 2
MIN_WINDOW_S = {"classify": 0.8, "reply": 1.5}        # below this there is no point calling the model
# Cap on the answer length per node (D59). None = no cap. The reply stays uncapped on purpose: measured on the real
# models (night 75), claude-haiku-5.5 and deepseek-v4.1-flash spend hundreds of hidden tokens before the answer and
# a cap of 300 or even 600 cut them off (1 of 14 short replies written instead of 14 of 14). Only a model that does
# not think first (mistral-small) works under a cap. Set a number here only per model, after measuring.
MAX_TOKENS: dict[str, int | None] = {"classify": None, "reply": None}
# How much hidden thinking a node's model may do (OpenRouter reasoning.effort). The reply gets none: measured on the
# real models it halves or better the reply time with the same acceptance ("low" still thinks: bad for replies). The
# classify gets none too: low and none were equal in the bigger sample (p50 about 1.6 s) and none is simpler.
# A model that does not reason ignores the field. Sample sizes were small.
REASONING_EFFORT: dict[str, str | None] = {"classify": "none", "reply": "none"}


def timeout_for(node: str, remaining_s: float, reserve_s: float = 0.0, cap_s: float | None = None) -> float | None:
    """How long this node may wait: min(cap, remaining - margin - reserve). The cap is the node's CAP_S unless given.

    Returns None when what is left is under the node's minimum window. The caller should then use a
    template, a handoff or the code classifier instead of calling the model.
    reserve_s is for later steps that still need time (classify, for example, has to leave room for the reply).
    """
    t = min(CAP_S[node] if cap_s is None else cap_s, remaining_s - MARGIN_S - reserve_s)
    return t if t >= MIN_WINDOW_S[node] else None
