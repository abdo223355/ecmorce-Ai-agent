"""Embedding adapter (D49): turns text into vectors. Same pattern as the LLM adapter (app/llm):
expected failures come back as a typed EmbedResult, never as an exception to the caller.

Two methods on purpose: documents and queries may need different prefixes (some models want
"query: " / "passage: "). The prefix stays inside the adapter, so changing the model touches nothing else.

Rules that carry over from the design:
- The provider is config (D49) and must be multilingual: documents are English, questions are Arabic / Arabizi / English.
- Queries arrive already scrubbed (D107); never log text (D108).
- A failed embedding at chat time means keyword-only search (D51): the caller must check `result.ok`.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import httpx

from ..config import settings
from ..llm.errors import HTTP_ERRORS
from ..llm.models import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

EmbedStatus = Literal["ok", "timeout", "rate_limited", "bad_output", "unavailable"]

# TODO(عبدالرحمن): البادئات بتتحدد حسب الموديل اللي هنختاره (e5 بيطلب "query: " و "passage: "، غيره لأ).
#   Hint: بعد ما نختار الموديل، شوف صفحته عند OpenRouter واكتب القيمتين دول.
QUERY_PREFIX = ""
DOCUMENT_PREFIX = ""

BATCH_SIZE = 32          # PROPOSAL: texts per HTTP call (ingest sends ~185 chunks, so 6 calls)


@dataclass(frozen=True)
class EmbedResult:
    status: EmbedStatus
    vectors: list[list[float]] = field(default_factory=list)   # same order as the input texts, unit length
    model_id: str = ""
    dim: int = 0
    reason: str | None = None
    details: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _fail(status: EmbedStatus, reason: str, latency_s: float = 0.0, **details) -> EmbedResult:
    return EmbedResult(status, reason=reason, details={"latency_s": round(latency_s, 3), **details})


def _unit(v: list[float]) -> list[float]:
    """Scale to length 1, so cosine similarity = dot product, and the store uses ONE metric (cosine)."""
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


class EmbeddingAdapter(ABC):
    @abstractmethod
    async def embed_documents(self, texts: list[str], timeout_s: float) -> EmbedResult:
        """Embed policy chunks (ingest). timeout_s applies to each HTTP call."""

    @abstractmethod
    async def embed_query(self, text: str, timeout_s: float) -> EmbedResult:
        """Embed one scrubbed user question. vectors has exactly one item."""


class OpenRouterEmbedder(EmbeddingAdapter):
    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None,
                 client: httpx.AsyncClient | None = None, batch_size: int = BATCH_SIZE,
                 query_prefix: str | None = None, document_prefix: str | None = None,
                 dimensions: int | None = None):
        self._model = model or settings.embed_model or EMBEDDING_MODEL
        self._dims = dimensions or settings.embed_dimensions or EMBEDDING_DIMENSIONS
        self._api_key = api_key or settings.openrouter_api_key
        self._base_url = (base_url or settings.llm_base_url).rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=None)   # the deadline is asyncio.wait_for in _call, not httpx's 5 s default
        self._batch = batch_size
        self._qp = QUERY_PREFIX if query_prefix is None else query_prefix
        self._dp = DOCUMENT_PREFIX if document_prefix is None else document_prefix

    async def embed_documents(self, texts: list[str], timeout_s: float) -> EmbedResult:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            r = await self._call([self._dp + t for t in texts[i:i + self._batch]], timeout_s)
            if not r.ok:
                return r
            vectors += r.vectors
        return EmbedResult("ok", vectors, self._model, len(vectors[0]) if vectors else 0)

    async def embed_query(self, text: str, timeout_s: float) -> EmbedResult:
        return await self._call([self._qp + text], timeout_s)

    async def _call(self, inputs: list[str], timeout_s: float) -> EmbedResult:
        if not self._api_key or not self._model:
            return _fail("unavailable", "embedding_not_configured")
        body = {"model": self._model, "input": inputs}
        if self._dims:
            body["dimensions"] = self._dims        # smaller vectors; the provider re-scales, we re-normalise in _parse
        start = time.monotonic()
        try:
            resp = await asyncio.wait_for(
                self._client.post(f"{self._base_url}/embeddings", json=body,
                                  headers={"Authorization": f"Bearer {self._api_key}"}),
                timeout=timeout_s)
        except (asyncio.TimeoutError, httpx.TimeoutException):
            return _fail("timeout", "deadline_exceeded", time.monotonic() - start)
        except httpx.HTTPError:
            return _fail("unavailable", "network_error", time.monotonic() - start)
        latency = time.monotonic() - start
        if resp.status_code != 200:
            status, reason = HTTP_ERRORS.get(resp.status_code, ("unavailable", f"http_{resp.status_code}"))
            return _fail(status, reason, latency, http_status=resp.status_code)
        return self._parse(resp, len(inputs), latency)

    def _parse(self, resp: httpx.Response, expected: int, latency_s: float) -> EmbedResult:
        try:
            rows = sorted(resp.json()["data"], key=lambda r: r["index"])      # the API may answer out of order
            vectors = [[float(x) for x in r["embedding"]] for r in rows]
        except (ValueError, KeyError, TypeError):
            return _fail("bad_output", "invalid_response", latency_s)
        if len(vectors) != expected or not vectors[0] or len({len(v) for v in vectors}) != 1:
            return _fail("bad_output", "wrong_count_or_dimension", latency_s)
        return EmbedResult("ok", [_unit(v) for v in vectors], self._model, len(vectors[0]),
                           details={"latency_s": round(latency_s, 3)})


class FakeEmbedder(EmbeddingAdapter):
    """Deterministic bag-of-words vectors: texts that share words are close. No network, no key.
    Good enough to test ingest / search plumbing; it knows nothing about meaning or Arabic."""

    def __init__(self, dim: int = 64, fail_with: EmbedResult | None = None):
        self.dim = dim
        self.fail_with = fail_with
        self.calls: list[tuple[str, int]] = []

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for w in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        return _unit(v)

    async def embed_documents(self, texts: list[str], timeout_s: float) -> EmbedResult:
        self.calls.append(("documents", len(texts)))
        return self.fail_with or EmbedResult("ok", [self._vec(t) for t in texts], "fake", self.dim)

    async def embed_query(self, text: str, timeout_s: float) -> EmbedResult:
        self.calls.append(("query", 1))
        return self.fail_with or EmbedResult("ok", [self._vec(text)], "fake", self.dim)


@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingAdapter:
    return OpenRouterEmbedder()
