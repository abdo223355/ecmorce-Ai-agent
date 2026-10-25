"""Ingest (D47, D48, D105): policy PDFs -> chunks -> embeddings -> pgvector.

    python -m app.rag.ingest                # index the corpus
    python -m app.rag.ingest --dry-run      # only show what would happen: no embedding call, no database write

Runs as an offline job (the indexing "Worker" of D48), not inside a chat request. It needs `pdftotext`
(poppler) on PATH: the chunker was checked against `pdftotext -layout` output on the whole corpus.

What gets indexed (D47, D105):
- only ACTIVE versions whose Audience names Customers or Delivery Workers;
- never the Evaluation / Adversarial folders (test questions must not leak into retrieval);
- never the internal documents in NEVER_INDEX, even if their metadata changes by mistake.
A SUPERSEDED / DRAFT file is not indexed; if that version is already in the store, its status is updated
(one row, D48), so it disappears from search at once.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .chunking import chunk_document, parse_header
from .embeddings import EmbeddingAdapter, EmbedResult, get_embedder

SKIP_FOLDERS = {"Evaluation", "Adversarial"}                          # D47
NEVER_INDEX = {"POL-AIS-001", "POL-AGE-001", "POL-AKU-001", "POL-VER-001"}   # internal docs (D47-b, D105)

EMBED_TIMEOUT_S = 120.0          # offline job: generous, per HTTP call
EMBED_ATTEMPTS = 3               # PROPOSAL: retries are fine here; D27 "no live retry" is for chat requests
_RETRYABLE = {"timeout", "rate_limited", "unavailable"}

DEFAULT_CORPUS = Path(__file__).resolve().parents[4] / "Rag_files" / "NovaCart_RAG_Corpus"


@dataclass
class DocReport:
    file: str
    doc_id: str = ""
    version: str = ""
    status: str = ""
    action: str = ""             # indexed | would_index | status_updated | skipped | failed
    reason: str = ""
    chunks: int = 0


def read_pdf(path: Path) -> str:
    try:
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, check=True,
                             text=True, encoding="utf-8")
    except FileNotFoundError:
        raise RuntimeError("pdftotext not found: install poppler-utils (Linux) or poppler (Windows)") from None
    return out.stdout


def find_pdfs(corpus: Path) -> list[Path]:
    return sorted(p for p in corpus.glob("*/*.pdf") if p.parent.name not in SKIP_FOLDERS)


async def _embed_with_retry(embedder: EmbeddingAdapter, texts: list[str]) -> EmbedResult:
    result = EmbedResult("unavailable", reason="not_tried")
    for attempt in range(EMBED_ATTEMPTS):
        result = await embedder.embed_documents(texts, EMBED_TIMEOUT_S)
        if result.ok or result.status not in _RETRYABLE:
            return result
        await asyncio.sleep(2 ** attempt)                  # 1 s, 2 s, 4 s
    return result


async def ingest(corpus: Path, embedder: EmbeddingAdapter | None, store, dry_run: bool = False,
                 reader: Callable[[Path], str] = read_pdf) -> list[DocReport]:
    files = find_pdfs(corpus)
    parsed: list[tuple[DocReport, list]] = []
    for path in files:
        rep = DocReport(file=path.name)
        try:
            text = reader(path)
            header = parse_header(text.split("\n"))
            chunks = chunk_document(text, path.name)
        except (ValueError, RuntimeError, subprocess.CalledProcessError) as e:
            rep.action, rep.reason = "failed", f"could not read or chunk: {e}"
            parsed.append((rep, []))
            continue
        rep.doc_id, rep.version, rep.status = header["doc_id"], header["version"], header["status"]
        parsed.append((rep, chunks))

    # Two ACTIVE versions of the same document: the code must not choose (POL-VER-001); index neither.
    active = Counter(r.doc_id for r, _ in parsed if r.status == "ACTIVE")

    for rep, chunks in parsed:
        if rep.action == "failed":
            continue
        if rep.doc_id in NEVER_INDEX:
            rep.action, rep.reason = "skipped", "internal document (never indexed)"
        elif rep.status != "ACTIVE":
            if dry_run:
                rep.action, rep.reason = "skipped", f"{rep.status}: not indexed"
            elif await store.set_status(rep.doc_id, rep.version, rep.status):
                rep.action, rep.reason = "status_updated", f"set to {rep.status} in the store"
            else:
                rep.action, rep.reason = "skipped", f"{rep.status}: not indexed"
        elif active[rep.doc_id] > 1:
            rep.action, rep.reason = "failed", "two ACTIVE versions of the same document"
        elif not chunks:
            rep.action, rep.reason = "failed", "no sections found"
        elif not chunks[0].audience:
            rep.action, rep.reason = "skipped", "audience names neither Customers nor Delivery Workers"
        elif dry_run:
            rep.action, rep.chunks = "would_index", len(chunks)
        else:
            result = await _embed_with_retry(embedder, [c.embed_text for c in chunks])
            if not result.ok:
                rep.action, rep.reason = "failed", f"embedding {result.status}/{result.reason}"
                continue
            await store.replace_version(chunks, result.vectors, result.model_id)
            rep.action, rep.chunks = "indexed", len(chunks)
    return [r for r, _ in parsed]


def _print(reports: list[DocReport]) -> None:
    for r in reports:
        print(f"{r.action:15s} {r.doc_id or '-':12s} v{r.version or '-':5s} {r.status or '-':10s} "
              f"chunks {r.chunks:3d}  {r.file}  {r.reason}")
    totals = Counter(r.action for r in reports)
    print("\n" + ", ".join(f"{k}: {v}" for k, v in sorted(totals.items())),
          f"| chunks: {sum(r.chunks for r in reports)}")


async def _main(args) -> int:
    from .store import PolicyStore
    corpus = Path(args.corpus)
    if not corpus.is_dir():
        print(f"corpus folder not found: {corpus}")
        return 2
    if args.dry_run:
        reports = await ingest(corpus, None, None, dry_run=True)
    else:
        store = PolicyStore(statement_timeout_ms=60_000)                  # offline job: no 1 s chat limit
        try:
            await store.open(wait=True, timeout=10)
        except Exception as e:
            await store.close()
            print(f"cannot reach the Gateway database ({type(e).__name__}). Is docker compose up? GATEWAY_DATABASE_URL?")
            return 2
        try:
            await store.ensure_schema()
            reports = await ingest(corpus, get_embedder(), store)
            print("store now:", await store.counts())
        finally:
            await store.close()
    _print(reports)
    return 1 if any(r.action == "failed" for r in reports) else 0


if __name__ == "__main__":
    if sys.platform == "win32":          # psycopg async cannot use the Windows default event loop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser(description="Index the NovaCart policy PDFs into pgvector.")
    parser.add_argument("--corpus", default=os.getenv("RAG_CORPUS_DIR", str(DEFAULT_CORPUS)))
    parser.add_argument("--dry-run", action="store_true")
    sys.exit(asyncio.run(_main(parser.parse_args())))
