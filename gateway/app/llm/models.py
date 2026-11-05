"""Which model each node uses. Model names are not secrets, so they live here and not in .env.

These are measured choices on small samples, to be re-checked under load and with the D66 text checks.
Set LLM_MODEL_<NODE> (for example LLM_MODEL_CLASSIFY) in the environment to override one for a quick test.
"""
from __future__ import annotations

MODELS: dict[str, str] = {
    # Picked from the container bake-offs with the no-retention rule on (night 80). classify: haiku-5.5 got 28 of 32
    # right (gemma-3-12b, the earlier pick, 8 of 16 and slower), with reasoning off, p50 1.6 s, p95 about 3 s.
    "classify": "anthropic/claude-haiku-5.5",
    # reply: deepseek-v4.1-flash with reasoning off, p95 1.9 s for policy answers and 1.4 s for fact replies.
    "reply": "deepseek/deepseek-v4.1-flash",
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
