"""Retrieval (A3, D51): what policy_search / procedure_search run at chat time.

    question -> [embed_query  ||  keyword search]  -> vector search -> fuse -> top 5 -> ToolResult

- Filter first (inside the store): ACTIVE + fully indexed + caller audience, plus the customer allow-list (D47-a).
- Hybrid (D51): vector search on the question (multilingual, D49) and PostgreSQL full-text on the ENGLISH search
  query from classify (D53). Keyword search runs ONLY with that English query: the documents are English, so
  Arabic / Arabizi words would match nothing, or worse, one English word by chance ("Confirmed") would pull a
  wrong section into the fusion. Without it the search is vector-only.
- The two ranked lists are merged with Reciprocal Rank Fusion. The design says "fused score" (D50) without a
  method: RRF is a PROPOSAL (no score calibration needed between cosine and ts_rank).
- When embed_query fails, a FallbackPolicy decides what the agent gets (decision by عبدالرحمن, option ب).
- top-k 5 (D94). No score gate yet: D114 says it is chosen from the eval set, not guessed.
- Never raises to the agent: database trouble -> ToolResult("unavailable") (POL-BDR-001 path).
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout

from ..backend_client import Deadline
from ..config import settings
from ..tools import ToolResult
from .embeddings import EmbeddingAdapter, EmbedResult
from .store import Hit, PolicyStore

TOP_K = 5                                   # D94
RAG_WINDOW_S = 1.5                          # D91: backend + RAG in parallel <= 1.5 s
MIN_WINDOW_S = 0.3                          # PROPOSAL: below this, do not start a search at all
RRF_K = 60                                  # PROPOSAL: the usual RRF constant
CUSTOMER_ALLOW_LIST = ("POL-SPC-001",)      # D47-a: shown to customers by name
# Score gate (D94 / D114): if the best COSINE similarity of the vector search is below it, the agent gets no
# chunks (it hands off instead of answering from a weak match). None = off. It is chosen by evals/l1_retrieval.py
# on the tuning split and confirmed once on the held-out, never guessed. RRF scores cannot be gated: rank-based.
# DECISION (عبدالرحمن, 2026-10-26): no gate. The D114 sweep on 96 tuning questions picked 0.0: the questions with
# no allowed answer scored 0.59-0.67, inside the range of answerable ones, so any gate lost more correct answers
# than it gained abstentions. Re-run evals/l1_retrieval.py when the corpus or the embedding model changes.
SCORE_GATE: float | None = None
# Early embedding (decision by عبدالرحمن, option أ): /chat starts embedding the user message when it arrives, in
# parallel with classify. Its timeout covers classify (cap 1.0 s, D92) + the RAG window (1.5 s). PROPOSAL.
PREFETCH_TIMEOUT_S = 2.5


# ---------- what to do when the embedding call fails (Strategy pattern, his option ب) ----------

@dataclass(frozen=True)
class FallbackOutcome:
    hits: list[Hit]              # what the agent gets ([] = nothing trustworthy: the agent hands off)
    details: dict                # goes into ToolResult.details, so the agent knows how the result was made


class FallbackPolicy(ABC):
    """One way to answer when embed_query failed. Same input, same output type: retrieve.search never needs
    to know which policy it got. Work is O(k) on at most TOP_K keyword hits."""

    mode: str

    @abstractmethod
    def apply(self, embed: EmbedResult, keyword_hits: list[Hit]) -> FallbackOutcome:
        ...


class KeywordOnlyFallback(FallbackPolicy):
    """We had an English search query, so the full-text search is meaningful on its own (D49 keyword-only).
    The result is marked, so the agent does not treat it like a normal hybrid result."""

    mode = "keyword_only"

    def apply(self, embed: EmbedResult, keyword_hits: list[Hit]) -> FallbackOutcome:
        return FallbackOutcome(keyword_hits[:TOP_K], {"mode": self.mode, "embedding": embed.status})


class NoAnswerFallback(FallbackPolicy):
    """No English query: a keyword search on Arabic / Arabizi text against English documents is not evidence.
    Return nothing, so the agent hands off instead of answering from a chance match."""

    mode = "no_retrieval"

    def apply(self, embed: EmbedResult, keyword_hits: list[Hit]) -> FallbackOutcome:
        return FallbackOutcome([], {"mode": self.mode, "embedding": embed.status, "why": "no_english_query"})


def choose_fallback(english_query: str | None) -> FallbackPolicy:
    return KeywordOnlyFallback() if english_query else NoAnswerFallback()


# ---------- fusion and the search itself ----------

def _key(h: Hit) -> tuple:
    return (h.doc_id, h.version, h.section, h.part)


def fuse(vector_hits: list[Hit], keyword_hits: list[Hit], k: int = TOP_K) -> list[tuple[Hit, float]]:
    """Reciprocal Rank Fusion: each list gives 1 / (RRF_K + rank). A chunk found by both lists adds both,
    so agreement between meaning and exact words pushes it up. Uses ranks only, never raw scores."""
    scores: dict[tuple, float] = {}
    first_seen: dict[tuple, Hit] = {}
    for hits in (vector_hits, keyword_hits):
        for rank, h in enumerate(hits, start=1):
            scores[_key(h)] = scores.get(_key(h), 0.0) + 1.0 / (RRF_K + rank)
            first_seen.setdefault(_key(h), h)
    ordered = sorted(scores, key=lambda key: -scores[key])[:k]
    return [(first_seen[key], scores[key]) for key in ordered]


def _to_result(pairs: list[tuple[Hit, float]], details: dict, cosine: dict | None = None) -> ToolResult:
    """score = the ranking score (RRF or ts_rank). vector_score = the raw cosine of that chunk when the vector
    search found it (None otherwise): the score gate and later evals need a real similarity, not a rank."""
    cosine = cosine or {}
    data = [{"doc_id": h.doc_id, "version": h.version, "section": h.section, "part": h.part, "title": h.title,
             "text": h.text, "score": round(s, 4), "vector_score": cosine.get(_key(h)), "cited": h.cited}
            for h, s in pairs]
    return ToolResult("ok", data=data, details=details)


async def _no_hits() -> list[Hit]:
    return []


async def _wait_prefetch(task: "asyncio.Task[EmbedResult]", window: float) -> EmbedResult:
    """Use the early embedding, but never wait past the RAG window for it. shield(): a timeout here must not
    cancel the task itself (BoundTools.close() does that at the end of the request)."""
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=window)
    except asyncio.TimeoutError:
        return EmbedResult("timeout", reason="prefetch_not_ready")


async def search(question: str, audience: str, deadline: Deadline, store: PolicyStore,
                 embedder: EmbeddingAdapter, english_query: str | None = None,
                 prefetched: "asyncio.Task[EmbedResult] | None" = None) -> ToolResult:
    """question: the scrubbed user text (any language), used for the meaning search.
    english_query: the English search query from classify (D53), used for the keyword search. Until classify
    exists (A5) it is None, so the search is vector-only and a failed embedding means no retrieval.
    prefetched: an embedding of `question` already started by /chat (early embedding); no new call is made."""
    window = min(RAG_WINDOW_S, deadline.remaining() - settings.reserve_after_backend_s)
    if window < MIN_WINDOW_S:
        return ToolResult("unavailable", reason="no_time_for_retrieval", details={"window_s": round(window, 3)})
    allow = CUSTOMER_ALLOW_LIST if audience == "customers" else ()
    start = time.monotonic()
    try:
        keywords = (store.search_keywords(english_query, audience, k=TOP_K, allow_doc_ids=allow)
                    if english_query else _no_hits())
        embedding = (_wait_prefetch(prefetched, window) if prefetched is not None
                     else embedder.embed_query(question, timeout_s=window))
        embed, keyword_hits = await asyncio.gather(embedding, keywords)
        if not embed.ok:
            outcome = choose_fallback(english_query).apply(embed, keyword_hits)
            return _to_result([(h, h.score) for h in outcome.hits],
                              {"latency_s": round(time.monotonic() - start, 3), **outcome.details})
        vector_hits = await store.search_vectors(embed.vectors[0], audience, embed.model_id, k=TOP_K,
                                                 allow_doc_ids=allow)
    except (DatabaseError, PoolTimeout) as e:
        return ToolResult("unavailable", reason="policy_store_error", details={"error": type(e).__name__})
    best = vector_hits[0].score if vector_hits else None
    details = {"mode": "hybrid" if english_query else "vector_only", "best_cosine": best,
               "latency_s": round(time.monotonic() - start, 3),
               "vector_hits": len(vector_hits), "keyword_hits": len(keyword_hits)}
    if SCORE_GATE is not None and (best is None or best < SCORE_GATE):
        return _to_result([], {**details, "mode": "below_gate", "gate": SCORE_GATE})
    cosine = {_key(h): round(h.score, 4) for h in vector_hits}
    return _to_result(fuse(vector_hits, keyword_hits), details, cosine)
