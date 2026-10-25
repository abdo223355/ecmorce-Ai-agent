"""Policy store (D48): pgvector inside the Gateway PostgreSQL.

Two tables:
- policy_versions: ONE row per (doc_id, version). The status (ACTIVE / SUPERSEDED / DRAFT) and the audience
  live here, and only here. Changing a status is one UPDATE of one row.
- policy_chunks: the sections. Each row points to its version by version_id and holds the embedding.

Search always JOINs the two tables and filters on the VERSION row, never on a status copy inside a chunk
(D48 "avoids drift"). Re-indexing a version replaces all of its chunks inside ONE transaction, together with
indexing_status = DONE (D48 / D14-8): either the whole new version is there, or the old one stays untouched.

Database errors are raised, not hidden: retrieve.py turns them into ToolResult("unavailable") for the agent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool

from ..config import settings
from ..llm.models import EMBEDDING_DIMENSIONS
from .models import Chunk

_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def _ddl(dims: int) -> str:
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_versions (
    version_id         BIGSERIAL PRIMARY KEY,
    doc_id             TEXT NOT NULL,
    version            TEXT NOT NULL,
    doc_title          TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'DRAFT')),
    audience           TEXT[] NOT NULL DEFAULT '{{}}',
    source_file        TEXT NOT NULL DEFAULT '',
    indexing_status    TEXT NOT NULL DEFAULT 'PENDING' CHECK (indexing_status IN ('PENDING', 'DONE')),
    embedding_model_id TEXT,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id, version)
);

CREATE TABLE IF NOT EXISTS policy_chunks (
    chunk_id           BIGSERIAL PRIMARY KEY,
    version_id         BIGINT NOT NULL REFERENCES policy_versions(version_id) ON DELETE CASCADE,
    section            TEXT NOT NULL,
    part               INT NOT NULL DEFAULT 1,
    title              TEXT NOT NULL,
    text               TEXT NOT NULL,
    context_before     TEXT NOT NULL DEFAULT '',
    embedding          vector({dims}) NOT NULL,
    embedding_model_id TEXT NOT NULL,
    tsv                tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || text)) STORED,
    UNIQUE (version_id, section, part)
);

CREATE INDEX IF NOT EXISTS policy_chunks_tsv ON policy_chunks USING gin (tsv);
"""
# No vector index yet: with ~130 chunks an exact scan is instant. Add HNSW (vector_cosine_ops) when it grows;
# it works because 768 < 2000 dimensions (pgvector's index limit).


@dataclass(frozen=True)
class Hit:
    doc_id: str
    version: str
    section: str
    part: int
    title: str
    text: str
    score: float           # vector search: cosine similarity (1 = same direction); keyword search: ts_rank_cd

    @property
    def cited(self) -> str:
        return f"{self.doc_id} §{self.section}@{self.version}"


def to_vector_literal(v: list[float]) -> str:
    """pgvector accepts '[0.1,0.2,...]' cast to ::vector. Keeps us free of an extra driver package."""
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def plain_dsn(url: str) -> str:
    """'postgresql+psycopg://...' (SQLAlchemy style in docker-compose) -> 'postgresql://...' for psycopg."""
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


class PolicyStore:
    def __init__(self, dsn: str | None = None, schema: str = "public",
                 statement_timeout_ms: int | None = None, dims: int = EMBEDDING_DIMENSIONS,
                 max_size: int = 5):
        if not _SCHEMA_NAME.match(schema):
            raise ValueError(f"bad schema name: {schema!r}")
        self.schema = schema
        self.dims = dims
        timeout = settings.rag_statement_timeout_ms if statement_timeout_ms is None else statement_timeout_ms
        # Own pool + statement timeout (D48): retrieval never waits behind audit / queue writes.
        self._pool = AsyncConnectionPool(
            plain_dsn(dsn or settings.gateway_database_url), min_size=1, max_size=max_size, open=False,
            kwargs={"options": f"-c statement_timeout={timeout} -c search_path={schema},public",
                    "autocommit": True})

    async def open(self, wait: bool = False, timeout: float = 30.0) -> None:
        """wait=True: fail now (within `timeout`) if the database cannot be reached, instead of on the first query."""
        await self._pool.open(wait=wait, timeout=timeout)

    async def close(self) -> None:
        await self._pool.close()

    async def __aenter__(self) -> "PolicyStore":
        await self.open()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def ensure_schema(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            await conn.execute(_ddl(self.dims))

    async def drop_schema(self) -> None:
        """Tests only: never call this on 'public'."""
        if self.schema == "public":
            raise ValueError("refusing to drop the public schema")
        async with self._pool.connection() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {self.schema} CASCADE")

    async def replace_version(self, chunks: list[Chunk], vectors: list[list[float]], model_id: str) -> int:
        """Write ONE document version: its version row + all its chunks, in one transaction.
        Old chunks of that version are deleted first, so re-running ingest never duplicates. Returns version_id."""
        if not chunks or len(chunks) != len(vectors):
            raise ValueError("need one vector per chunk")
        first = chunks[0]
        if any((c.doc_id, c.version) != (first.doc_id, first.version) for c in chunks):
            raise ValueError("all chunks must belong to the same document version")
        if any(len(v) != self.dims for v in vectors):
            raise ValueError(f"every vector must have {self.dims} numbers")
        async with self._pool.connection() as conn:
            async with conn.transaction():
                row = await (await conn.execute(
                    """INSERT INTO policy_versions (doc_id, version, doc_title, status, audience, source_file,
                                                     indexing_status, embedding_model_id, updated_at)
                       VALUES (%s, %s, %s, %s, %s::text[], %s, 'PENDING', %s, now())
                       ON CONFLICT (doc_id, version) DO UPDATE SET
                           doc_title = EXCLUDED.doc_title, status = EXCLUDED.status, audience = EXCLUDED.audience,
                           source_file = EXCLUDED.source_file, indexing_status = 'PENDING',
                           embedding_model_id = EXCLUDED.embedding_model_id, updated_at = now()
                       RETURNING version_id""",
                    (first.doc_id, first.version, first.doc_title, first.status, list(first.audience),
                     first.source_file, model_id))).fetchone()
                version_id = row[0]
                await conn.execute("DELETE FROM policy_chunks WHERE version_id = %s", (version_id,))
                async with conn.cursor() as cur:
                    await cur.executemany(
                        """INSERT INTO policy_chunks (version_id, section, part, title, text, context_before,
                                                      embedding, embedding_model_id)
                           VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s)""",
                        [(version_id, c.section, c.part, c.title, c.text, c.context_before,
                          to_vector_literal(v), model_id) for c, v in zip(chunks, vectors)])
                await conn.execute("UPDATE policy_versions SET indexing_status = 'DONE' WHERE version_id = %s",
                                   (version_id,))
        return version_id

    async def set_status(self, doc_id: str, version: str, status: str) -> bool:
        """One UPDATE of one row: every chunk of that version changes with it. False = no such version."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE policy_versions SET status = %s, updated_at = now() WHERE doc_id = %s AND version = %s",
                (status, doc_id, version))
            return cur.rowcount == 1

    _FILTER = """v.status = 'ACTIVE' AND v.indexing_status = 'DONE'
                 AND (%(audience)s = ANY(v.audience) OR v.doc_id = ANY(%(allow)s::text[]))"""

    async def search_vectors(self, query_vector: list[float], audience: str, model_id: str, k: int = 5,
                             allow_doc_ids: tuple[str, ...] = ()) -> list[Hit]:
        """Nearest chunks by cosine, only from ACTIVE, fully indexed versions the audience may see
        (+ by-name allow-list, D47-a), and only vectors made by the same model (no mixing after a model change)."""
        if len(query_vector) != self.dims:
            raise ValueError(f"query vector must have {self.dims} numbers")
        sql = f"""SELECT v.doc_id, v.version, c.section, c.part, c.title, c.text,
                         1 - (c.embedding <=> %(q)s::vector) AS score
                  FROM policy_chunks c JOIN policy_versions v ON v.version_id = c.version_id
                  WHERE {self._FILTER} AND c.embedding_model_id = %(model)s
                  ORDER BY c.embedding <=> %(q)s::vector
                  LIMIT %(k)s"""
        return await self._hits(sql, {"q": to_vector_literal(query_vector), "audience": audience,
                                      "allow": list(allow_doc_ids), "model": model_id, "k": k})

    async def search_keywords(self, query_text: str, audience: str, k: int = 5,
                              allow_doc_ids: tuple[str, ...] = ()) -> list[Hit]:
        """PostgreSQL full-text search on the ENGLISH search query (D51, D53). Also the fallback when the
        embedding provider is down (D49): it needs no external call.
        ANY word may match (OR), and chunks matching more words rank higher. With AND, "return window shirt"
        missed the Return Window section because it never says "shirt" (found in the real-corpus check)."""
        sql = f"""SELECT v.doc_id, v.version, c.section, c.part, c.title, c.text,
                         ts_rank_cd(c.tsv, t.q) AS score
                  FROM policy_chunks c JOIN policy_versions v ON v.version_id = c.version_id,
                       (SELECT NULLIF(replace(plainto_tsquery('english', %(text)s)::text, '&', '|'), '')::tsquery
                        AS q) t
                  WHERE {self._FILTER} AND c.tsv @@ t.q
                  ORDER BY score DESC
                  LIMIT %(k)s"""
        return await self._hits(sql, {"text": query_text, "audience": audience,
                                      "allow": list(allow_doc_ids), "k": k})

    async def active_docs(self) -> dict[str, tuple[str, ...]]:
        """doc_id -> audience of every ACTIVE, fully indexed version (used by the evals to know what a role may see)."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT doc_id, audience FROM policy_versions WHERE status = 'ACTIVE' AND indexing_status = 'DONE'"
            )).fetchall()
        return {doc_id: tuple(aud) for doc_id, aud in rows}

    async def counts(self) -> dict:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                """SELECT v.status, count(DISTINCT v.version_id), count(c.chunk_id)
                   FROM policy_versions v LEFT JOIN policy_chunks c ON c.version_id = v.version_id
                   GROUP BY v.status""")).fetchall()
        return {status: {"versions": n_v, "chunks": n_c} for status, n_v, n_c in rows}

    async def _hits(self, sql: str, params: dict) -> list[Hit]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(sql, params)).fetchall()
        return [Hit(r[0], r[1], r[2], r[3], r[4], r[5], float(r[6])) for r in rows]
