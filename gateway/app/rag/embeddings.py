"""Embedding adapter: turns text into vectors.

Like the LLM adapter, expected failures come back as a typed EmbedResult and never as an exception.

There are two methods on purpose. Some models want different prefixes for documents and for queries
("passage: " and "query: "), and keeping that inside the adapter means switching models touches nothing else.

Things to keep in mind:
- The model must be multilingual: documents are English, questions can be Arabic, Arabizi or English.
- Queries arrive already scrubbed, and text is never logged.
- A failed embedding at chat time means keyword-only search, so callers must check `result.ok`.
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

# Prefixes for the chosen model. Empty is right for gemini-embedding-001 (it scored well without any).
# Fill these in if the model is swapped for one that needs them, e.g. e5 wants "query: " and "passage: ".
QUERY_PREFIX = ""
DOCUMENT_PREFIX = ""

BATCH_SIZE = 32          # texts per HTTP call; indexing the whole corpus takes a handful of calls


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
    """Scale a vector to length 1. Then cosine similarity is just a dot product, and the whole system
    uses one metric."""
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


class EmbeddingAdapter(ABC):
    @abstractmethod
    async def embed_documents(self, texts: list[str], timeout_s: float) -> EmbedResult:
        """Embed policy chunks (used by ingest). timeout_s applies to each HTTP call."""

    @abstractmethod
    async def embed_query(self, text: str, timeout_s: float) -> EmbedResult:
        """Embed one scrubbed user question. `vectors` has exactly one item."""


class OpenRouterEmbedder(EmbeddingAdapter):
    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None,
                 client: httpx.AsyncClient | None = None, batch_size: int = BATCH_SIZE,
                 query_prefix: str | None = None, document_prefix: str | None = None,
                 dimensions: int | None = None):
        self._model = model or settings.embed_model or EMBEDDING_MODEL
        self._dims = dimensions or settings.embed_dimensions or EMBEDDING_DIMENSIONS
        self._api_key = api_key or settings.openrouter_api_key
        self._base_url = (base_url or settings.llm_base_url).rstrip("/")
        # httpx's own 5 s default would cut calls before our deadline, so it is turned off here.
        # The deadline is asyncio.wait_for in _call.
        self._client = client or httpx.AsyncClient(timeout=None)
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
            # Ask for smaller vectors. The provider rescales them; we normalise again in _parse.
            body["dimensions"] = self._dims
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
            # The API may return rows out of order, so sort by index.
            rows = sorted(resp.json()["data"], key=lambda r: r["index"])
            vectors = [[float(x) for x in r["embedding"]] for r in rows]
        except (ValueError, KeyError, TypeError):
            return _fail("bad_output", "invalid_response", latency_s)
        if len(vectors) != expected or not vectors[0] or len({len(v) for v in vectors}) != 1:
            return _fail("bad_output", "wrong_count_or_dimension", latency_s)
        return EmbedResult("ok", [_unit(v) for v in vectors], self._model, len(vectors[0]),
                           details={"latency_s": round(latency_s, 3)})


class FakeEmbedder(EmbeddingAdapter):
    """Bag-of-words vectors that are the same every time: texts sharing words end up close together.
    No network, no key. Good enough to test the ingest and search plumbing, but it knows nothing about
    meaning or Arabic."""

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
