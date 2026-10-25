"""Retrieval: what policy_search and procedure_search run at chat time.

    question -> [embed_query  ||  keyword search]  -> vector search -> fuse -> top 5 -> ToolResult

- The store filters first: ACTIVE, fully indexed, the caller's audience, plus the customer allow-list.
- The search is hybrid. Vector search runs on the question (the embedding model is multilingual). Keyword
  search is PostgreSQL full-text on the English query that classify produces. It only runs with that
  English query: the documents are English, so Arabic or Arabizi words would match nothing, and a single
  English word that happens to match ("Confirmed") would drag a wrong section into the fusion. Without
  the English query the search is vector-only.
- The two ranked lists are merged with Reciprocal Rank Fusion, which only needs ranks, so cosine and
  ts_rank scores never have to be compared directly.
- When embed_query fails, a FallbackPolicy decides what the agent gets.
- top-k is 5. There is a score gate, but it is off: the evaluation picked no gate (see SCORE_GATE).
- Nothing raises into the agent. Database trouble becomes ToolResult("unavailable").
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

TOP_K = 5
RAG_WINDOW_S = 1.5                          # backend and RAG share a 1.5 s window (D91)
MIN_WINDOW_S = 0.3                          # below this, don't even start a search
RRF_K = 60                                  # the usual constant for Reciprocal Rank Fusion
CUSTOMER_ALLOW_LIST = ("POL-SPC-001",)      # shown to customers by name even though its audience is internal

# Score gate: if the best cosine similarity is below it, the agent gets no chunks and hands off instead of
# answering from a weak match. It is off (None). The sweep in evals/l1_retrieval.py found that questions with
# no allowed answer scored 0.59-0.67, the same range as answerable ones, so any gate lost more correct answers
# than it gained correct abstentions. Re-run that eval if the corpus or the embedding model changes.
# (The gate can only look at cosine scores. RRF scores are rank-based and can't be thresholded.)
SCORE_GATE: float | None = None

# The user message is embedded as soon as /chat receives it, in parallel with classify, so the ~1.1 s embedding
# call hides behind classify. This timeout covers classify (up to 1.0 s) plus the RAG window.
PREFETCH_TIMEOUT_S = 2.5


# ---------- what to do when the embedding call fails ----------

@dataclass(frozen=True)
class FallbackOutcome:
    hits: list[Hit]              # what the agent gets; [] means nothing trustworthy, so it hands off
    details: dict                # goes into ToolResult.details so the agent knows how the result was made


class FallbackPolicy(ABC):
    """One way to answer when embed_query failed. Every policy takes the same input and returns the same
    type, so retrieve.search never needs to know which one it got. The work is O(k), at most TOP_K hits."""

    mode: str

    @abstractmethod
    def apply(self, embed: EmbedResult, keyword_hits: list[Hit]) -> FallbackOutcome:
        ...


class KeywordOnlyFallback(FallbackPolicy):
    """There is an English query, so keyword search means something on its own. The result is marked so the
    agent doesn't treat it like a normal hybrid result."""

    mode = "keyword_only"

    def apply(self, embed: EmbedResult, keyword_hits: list[Hit]) -> FallbackOutcome:
        return FallbackOutcome(keyword_hits[:TOP_K], {"mode": self.mode, "embedding": embed.status})


class NoAnswerFallback(FallbackPolicy):
    """No English query. Matching Arabic or Arabizi words against English documents isn't evidence, so return
    nothing and let the agent hand off instead of answering from a chance match."""

    mode = "no_retrieval"

    def apply(self, embed: EmbedResult, keyword_hits: list[Hit]) -> FallbackOutcome:
        return FallbackOutcome([], {"mode": self.mode, "embedding": embed.status, "why": "no_english_query"})


def choose_fallback(english_query: str | None) -> FallbackPolicy:
    return KeywordOnlyFallback() if english_query else NoAnswerFallback()


# ---------- fusion and the search itself ----------

def _key(h: Hit) -> tuple:
    return (h.doc_id, h.version, h.section, h.part)


def fuse(vector_hits: list[Hit], keyword_hits: list[Hit], k: int = TOP_K) -> list[tuple[Hit, float]]:
    """Reciprocal Rank Fusion. Each list gives a chunk 1 / (RRF_K + rank). A chunk found by both lists gets
    both contributions, so agreement between meaning and exact words pushes it up."""
    scores: dict[tuple, float] = {}
    first_seen: dict[tuple, Hit] = {}
    for hits in (vector_hits, keyword_hits):
        for rank, h in enumerate(hits, start=1):
            scores[_key(h)] = scores.get(_key(h), 0.0) + 1.0 / (RRF_K + rank)
            first_seen.setdefault(_key(h), h)
    ordered = sorted(scores, key=lambda key: -scores[key])[:k]
    return [(first_seen[key], scores[key]) for key in ordered]


def _to_result(pairs: list[tuple[Hit, float]], details: dict, cosine: dict | None = None) -> ToolResult:
    """`score` is the ranking score (RRF or ts_rank). `vector_score` is the raw cosine of that chunk when the
    vector search found it, else None. The gate and the evals need a real similarity, not a rank."""
    cosine = cosine or {}
    data = [{"doc_id": h.doc_id, "version": h.version, "section": h.section, "part": h.part, "title": h.title,
             "text": h.text, "score": round(s, 4), "vector_score": cosine.get(_key(h)), "cited": h.cited}
            for h, s in pairs]
    return ToolResult("ok", data=data, details=details)


async def _no_hits() -> list[Hit]:
    return []


async def _wait_prefetch(task: "asyncio.Task[EmbedResult]", window: float) -> EmbedResult:
    """Use the early embedding, but never wait for it longer than the RAG window. shield() makes sure a timeout
    here doesn't cancel the task itself; BoundTools.close() does that at the end of the request."""
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=window)
    except asyncio.TimeoutError:
        return EmbedResult("timeout", reason="prefetch_not_ready")


async def search(question: str, audience: str, deadline: Deadline, store: PolicyStore,
                 embedder: EmbeddingAdapter, english_query: str | None = None,
                 prefetched: "asyncio.Task[EmbedResult] | None" = None) -> ToolResult:
    """question is the scrubbed user text, in any language, and drives the meaning search.

    english_query is the English search query from classify and drives the keyword search. Until classify
    exists it is None, so the search is vector-only and a failed embedding means no retrieval.
    prefetched is an embedding of `question` that /chat already started; if given, no new call is made.
    """
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
