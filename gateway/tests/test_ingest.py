"""Ingest tests: fake PDF reader, fake embedder, fake store. No PDFs, network or database needed."""
import asyncio

from app.rag import ingest as ing
from app.rag.embeddings import EmbedResult, FakeEmbedder

_REAL_SLEEP = asyncio.sleep          # keep the real one: the tests replace asyncio.sleep to skip waiting


def doc_text(doc_id="POL-RET-001", version="2.1", status="ACTIVE", audience="Customers, Customer Service, AI Gateway"):
    return f"""Return Policy
NovaCart Document {doc_id} - Version {version} - Status: {status}

Document Metadata
Document ID: Title: Audience:
{doc_id} Return Policy {audience} {version} {status}

Table of Contents
1. Purpose 2. Window

1. Purpose
This policy defines returns.

2. Window
The window is 30 days.
"""


class FakeStore:
    def __init__(self, known=()):
        self.known = set(known)            # (doc_id, version) already in the store
        self.replaced, self.statuses = [], []

    async def replace_version(self, chunks, vectors, model_id):
        self.replaced.append((chunks[0].doc_id, chunks[0].version, len(chunks), len(vectors), model_id))

    async def set_status(self, doc_id, version, status):
        self.statuses.append((doc_id, version, status))
        return (doc_id, version) in self.known


def corpus(tmp_path, files: dict):
    """files: {"Folder/name.pdf": text}. Returns (corpus dir, reader)."""
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    return tmp_path, (lambda path: files[f"{path.parent.name}/{path.name}"])


def run(coro):
    return asyncio.run(coro)


def by_file(reports):
    return {r.file: r for r in reports}


def test_indexes_only_active_docs_for_customers_or_workers(tmp_path):
    root, reader = corpus(tmp_path, {
        "Customer_Policies/02_Return.pdf": doc_text(),
        "Delivery_Worker_Policies/14_Damage.pdf": doc_text("PRC-DMG-001", "1.0", audience="Delivery Workers, Dispatch"),
        "Customer_Policies/10_Comms.pdf": doc_text("POL-COM-001", "1.0", audience="Customer Service, AI Gateway"),
        "Customer_Policies/02c_Draft.pdf": doc_text(version="3.0", status="DRAFT"),
    })
    store = FakeStore()
    r = by_file(run(ing.ingest(root, FakeEmbedder(), store, reader=reader)))
    assert r["02_Return.pdf"].action == "indexed" and r["02_Return.pdf"].chunks == 2
    assert r["14_Damage.pdf"].action == "indexed"
    assert r["10_Comms.pdf"].action == "skipped" and "audience" in r["10_Comms.pdf"].reason
    assert r["02c_Draft.pdf"].action == "skipped"
    assert sorted(x[0] for x in store.replaced) == ["POL-RET-001", "PRC-DMG-001"]
    assert all(x[2] == x[3] and x[4] == "fake" for x in store.replaced)          # one vector per chunk


def test_evaluation_folders_and_internal_docs_are_never_indexed(tmp_path):
    root, reader = corpus(tmp_path, {
        "Evaluation/29_Eval.pdf": doc_text("EVL-RAG-001"),
        "Adversarial/30_Adv.pdf": doc_text("EVL-ADV-001"),
        "Security_AI_Policies/27_Usage.pdf": doc_text("POL-AKU-001"),     # even with a Customers audience
    })
    store = FakeStore()
    reports = run(ing.ingest(root, FakeEmbedder(), store, reader=reader))
    assert [r.file for r in reports] == ["27_Usage.pdf"]                    # the two test folders are not read
    assert reports[0].action == "skipped" and "internal" in reports[0].reason
    assert store.replaced == []


def test_superseded_version_already_in_store_gets_its_status_updated(tmp_path):
    root, reader = corpus(tmp_path, {"Customer_Policies/02b_Old.pdf": doc_text(version="2.0", status="SUPERSEDED")})
    store = FakeStore(known={("POL-RET-001", "2.0")})
    r = run(ing.ingest(root, FakeEmbedder(), store, reader=reader))[0]
    assert r.action == "status_updated" and store.statuses == [("POL-RET-001", "2.0", "SUPERSEDED")]
    assert store.replaced == []


def test_two_active_versions_of_one_document_index_neither(tmp_path):
    root, reader = corpus(tmp_path, {"Customer_Policies/a.pdf": doc_text(version="2.1"),
                                     "Customer_Policies/b.pdf": doc_text(version="2.2")})
    store = FakeStore()
    reports = run(ing.ingest(root, FakeEmbedder(), store, reader=reader))
    assert [r.action for r in reports] == ["failed", "failed"] and store.replaced == []


def test_transient_embedding_failure_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(ing.asyncio, "sleep", lambda s: _REAL_SLEEP(0))
    root, reader = corpus(tmp_path, {"Customer_Policies/02_Return.pdf": doc_text()})

    class Flaky(FakeEmbedder):
        def __init__(self):
            super().__init__()
            self.n = 0

        async def embed_documents(self, texts, timeout_s):
            self.n += 1
            return EmbedResult("rate_limited", reason="429") if self.n == 1 else await super().embed_documents(texts, timeout_s)

    store = FakeStore()
    r = run(ing.ingest(root, Flaky(), store, reader=reader))[0]
    assert r.action == "indexed" and len(store.replaced) == 1


def test_embedding_that_keeps_failing_is_reported_and_nothing_is_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(ing.asyncio, "sleep", lambda s: _REAL_SLEEP(0))
    root, reader = corpus(tmp_path, {"Customer_Policies/02_Return.pdf": doc_text()})
    store = FakeStore()
    emb = FakeEmbedder(fail_with=EmbedResult("timeout", reason="deadline_exceeded"))
    r = run(ing.ingest(root, emb, store, reader=reader))[0]
    assert r.action == "failed" and "timeout" in r.reason and store.replaced == []
    assert len(emb.calls) == ing.EMBED_ATTEMPTS


def test_dry_run_calls_neither_embedder_nor_store(tmp_path):
    root, reader = corpus(tmp_path, {"Customer_Policies/02_Return.pdf": doc_text(),
                                     "Customer_Policies/02b_Old.pdf": doc_text(version="2.0", status="SUPERSEDED")})
    reports = run(ing.ingest(root, None, None, dry_run=True, reader=reader))
    assert [r.action for r in reports] == ["would_index", "skipped"]


def test_unreadable_file_is_reported_not_fatal(tmp_path):
    root, reader = corpus(tmp_path, {"Customer_Policies/broken.pdf": "no header at all",
                                     "Customer_Policies/02_Return.pdf": doc_text()})
    r = by_file(run(ing.ingest(root, FakeEmbedder(), FakeStore(), reader=reader)))
    assert r["broken.pdf"].action == "failed" and r["02_Return.pdf"].action == "indexed"
