"""Which model each node uses (D71). Names are not secrets, so they live here, not in .env.

Starting candidates only: the final choice comes from the bake-off on the eval set (Step 9, A5 / A8).
An environment variable LLM_MODEL_<NODE> (e.g. LLM_MODEL_CLASSIFY) overrides a value for quick tests.
"""
from __future__ import annotations

MODELS: dict[str, str] = {
    "classify": "google/gemma-3-12b-it",      # small + fast: p50 0.89 s in the speed test (classify cap 1.0 s)
    "reply": "anthropic/claude-haiku-5.5",   # stronger, good Arabic (reply <= 2.0 s)
}
