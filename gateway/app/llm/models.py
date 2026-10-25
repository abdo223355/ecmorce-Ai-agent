"""Which model each node uses (D71). Names are not secrets, so they live here, not in .env.

Starting candidates only: the final choice comes from the bake-off on the eval set (Step 9, A5 / A8).
An environment variable LLM_MODEL_<NODE> (e.g. LLM_MODEL_CLASSIFY) overrides a value for quick tests.
"""
from __future__ import annotations

MODELS: dict[str, str] = {
    "classify": "google/gemma-3-12b-it",      # small + fast: p50 0.89 s in the speed test (classify cap 1.0 s)
    "reply": "anthropic/claude-haiku-5.5",   # stronger, good Arabic (reply <= 2.0 s)
}

# Embedding model (D49, D72): must be multilingual (English documents, Arabic / Arabizi / English questions).
# Chosen 2026-10-23 by عبدالرحمن after a 36-query test (English / Egyptian Arabic / Arabizi): document in the
# top 5 for 36 of 36 queries, see docs/PROGRESS.md. EMBED_MODEL in the environment overrides it.
# Open: output size is 3072 numbers (above the pgvector index limit of 2000, D49) and vendor retention (D111).
EMBEDDING_MODEL = "google/gemini-embedding-001"

# Vector size we store (chosen by عبدالرحمن): 768, not the model's full 3072. Same quality on the 36-query test
# (35/36 vs 36/36, inside the noise), and it fits a pgvector HNSW index (limit 2000). The column in the store must
# be vector(768). If this changes, every chunk must be embedded again. EMBED_DIMENSIONS in the environment overrides it.
EMBEDDING_DIMENSIONS = 768
