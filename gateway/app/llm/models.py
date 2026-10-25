"""Which model each node uses. Model names are not secrets, so they live here and not in .env.

These are starting choices. The final pick comes from comparing models on the evaluation set.
Set LLM_MODEL_<NODE> (for example LLM_MODEL_CLASSIFY) in the environment to override one for a quick test.
"""
from __future__ import annotations

MODELS: dict[str, str] = {
    "classify": "google/gemma-3-12b-it",      # small and fast: median 0.89 s in the speed test (cap is 1.0 s)
    "reply": "anthropic/claude-haiku-5.5",   # stronger, handles Arabic well (cap is 2.0 s)
}

# Embedding model. It has to be multilingual: the documents are English, the questions can be Arabic,
# Arabizi or English. Picked after a 36-query test, where the right document was in the top 5 every time
# (see docs/PROGRESS.md). Set EMBED_MODEL in the environment to override it.
EMBEDDING_MODEL = "google/gemini-embedding-001"

# Size of the vectors we store: 768 instead of the model's full 3072. Quality on the test was the same
# (35/36 vs 36/36, within noise) and 768 fits a pgvector HNSW index, which stops at 2000 dimensions.
# The store's column must match (vector(768)); changing this means embedding every chunk again.
# Set EMBED_DIMENSIONS in the environment to override it.
EMBEDDING_DIMENSIONS = 768
