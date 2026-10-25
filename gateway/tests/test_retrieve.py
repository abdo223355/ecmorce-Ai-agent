"""Retrieval tests: fake store + fake embedder. No database or network."""
import asyncio

from psycopg import OperationalError

from app.backend_client import Deadline
from app.rag import retrieve
from app.rag.embeddings import EmbedResult, FakeEmbedder
from app.rag.store import Hit

TIMEOUT = EmbedResult("timeout", reason="deadline_exceeded")


def hit(section, doc="POL-RET-001", score=0.5):
    return Hit(doc, "2.1", section, 1, f"Title {section}", f"text {section}", score)


class FakeStore:
    def __init__(self, vector=(), keyword=(), fail=False):
        self.vector, self.keyword, self.fail = list(vector), list(keyword), fail
        self.calls = []

    async def search_keywords(self, text, audience, k=5, allow_doc_ids=()):
        self.calls.append(("keywords", text, audience, allow_doc_ids))
        if self.fail:
            raise OperationalError("db down")
        return self.keyword

    async def search_vectors(self, vec, audience, model_id, k=5, allow_doc_ids=()):
        self.calls.append(("vectors", model_id, audience, allow_doc_ids))
        if self.fail:
            raise OperationalError("db down")
        return self.vector


def run(coro):
    return asyncio.run(coro)


def kinds(store):
    return [c[0] for c in store.calls]


# ---------- fusion ----------

def test_fuse_puts_chunks_found_by_both_searches_first_and_keeps_top_k():
    fused = retrieve.fuse([hit("1"), hit("2"), hit("3")], [hit("3"), hit("4")], k=3)
    assert [h.section for h, _ in fused] == ["3", "1", "2"]          # §3 is in both lists
    assert fused[0][1] > fused[1][1]


# ---------- the fallback policies (option ب) ----------

def test_keyword_only_policy_returns_the_keyword_hits_and_marks_them():
    out = retrieve.KeywordOnlyFallback().apply(TIMEOUT, [hit(str(i)) for i in range(1, 8)])
    assert [h.section for h in out.hits] == ["1", "2", "3", "4", "5"]  # never more than TOP_K
    assert out.details == {"mode": "keyword_only", "embedding": "timeout"}


def test_no_answer_policy_returns_nothing_even_if_keywords_matched():
    out = retrieve.NoAnswerFallback().apply(TIMEOUT, [hit("2")])
    assert out.hits == []
    assert out.details["mode"] == "no_retrieval" and out.details["why"] == "no_english_query"


def test_policy_choice_depends_on_the_english_query():
    assert isinstance(retrieve.choose_fallback("return window"), retrieve.KeywordOnlyFallback)
    assert isinstance(retrieve.choose_fallback(None), retrieve.NoAnswerFallback)
    assert isinstance(retrieve.choose_fallback(""), retrieve.NoAnswerFallback)
    assert issubclass(retrieve.KeywordOnlyFallback, retrieve.FallbackPolicy)
    assert issubclass(retrieve.NoAnswerFallback, retrieve.FallbackPolicy)


# ---------- search: normal paths ----------

def test_with_english_query_search_is_hybrid():
    store = FakeStore(vector=[hit("2"), hit("9")], keyword=[hit("2")])
    r = run(retrieve.search("عندي كام يوم أرجّع القميص؟", "customers", Deadline(8.0), store, FakeEmbedder(),
                            english_query="return window days"))
    assert r.ok and r.details["mode"] == "hybrid"
    assert r.data[0]["cited"] == "POL-RET-001 §2@2.1"
    assert set(r.data[0]) >= {"doc_id", "version", "section", "text", "score"}       # rag/__init__ contract
    assert store.calls[0][1] == "return window days"                                 # keywords use the English query


def test_without_english_query_there_is_no_keyword_search():
    store = FakeStore(vector=[hit("2")], keyword=[hit("7")])
    r = run(retrieve.search("عندي كام يوم أرجّع القميص؟", "customers", Deadline(8.0), store, FakeEmbedder()))
    assert r.ok and r.details["mode"] == "vector_only"
    assert kinds(store) == ["vectors"] and [d["section"] for d in r.data] == ["2"]


def test_customer_allow_list_is_passed_only_for_customers():
    store = FakeStore()
    run(retrieve.search("q", "customers", Deadline(8.0), store, FakeEmbedder()))
    run(retrieve.search("q", "delivery_workers", Deadline(8.0), store, FakeEmbedder()))
    assert [c[3] for c in store.calls if c[0] == "vectors"] == [retrieve.CUSTOMER_ALLOW_LIST, ()]


def test_embedding_timeout_is_capped_by_the_rag_window():
    seen = {}

    class Spy(FakeEmbedder):
        async def embed_query(self, text, timeout_s):
            seen["timeout"] = timeout_s
            return await super().embed_query(text, timeout_s)

    run(retrieve.search("q", "customers", Deadline(8.0), FakeStore(), Spy()))
    assert seen["timeout"] == retrieve.RAG_WINDOW_S


# ---------- search: failure paths ----------

def test_failed_embedding_with_english_query_gives_keyword_only_results():
    store = FakeStore(keyword=[hit("2")])
    r = run(retrieve.search("q", "customers", Deadline(8.0), store, FakeEmbedder(fail_with=TIMEOUT),
                            english_query="return window"))
    assert r.ok and r.details["mode"] == "keyword_only" and r.details["embedding"] == "timeout"
    assert [d["section"] for d in r.data] == ["2"] and "vectors" not in kinds(store)


def test_failed_embedding_without_english_query_gives_no_retrieval():
    store = FakeStore(keyword=[hit("2")])
    r = run(retrieve.search("عندي كام يوم أرجّع القميص؟", "customers", Deadline(8.0), store,
                            FakeEmbedder(fail_with=TIMEOUT)))
    assert r.ok and r.data == [] and r.details["mode"] == "no_retrieval"
    assert store.calls == []                         # nothing searched: no vector, no meaningful keywords


def test_no_time_left_means_no_search_at_all():
    store, emb = FakeStore(), FakeEmbedder()
    r = run(retrieve.search("q", "customers", Deadline(2.0), store, emb))     # 2.0 - 2.2 reserve < 0.3
    assert r.status == "unavailable" and r.reason == "no_time_for_retrieval"
    assert store.calls == [] and emb.calls == []


def test_database_error_becomes_unavailable_not_an_exception():
    for english in (None, "return window"):
        r = run(retrieve.search("q", "customers", Deadline(8.0), FakeStore(fail=True), FakeEmbedder(),
                                english_query=english))
        assert r.status == "unavailable" and r.reason == "policy_store_error"


# ---------- early embedding (option أ) ----------

def test_prefetched_embedding_is_used_instead_of_a_new_call():
    async def go():
        emb = FakeEmbedder()
        task = asyncio.ensure_future(emb.embed_query("q", 2.5))
        store = FakeStore(vector=[hit("2")])
        r = await retrieve.search("q", "customers", Deadline(8.0), store, emb, prefetched=task)
        return r, emb
    r, emb = run(go())
    assert r.ok and r.details["mode"] == "vector_only" and len(emb.calls) == 1      # only the early call


def test_slow_prefetch_is_not_waited_for_past_the_window(monkeypatch):
    monkeypatch.setattr(retrieve, "RAG_WINDOW_S", 0.05)
    monkeypatch.setattr(retrieve, "MIN_WINDOW_S", 0.01)        # else the search stops before waiting at all

    async def go():
        async def slow():
            await asyncio.sleep(1)
            return EmbedResult("ok", [[1.0]], "fake", 1)
        task = asyncio.ensure_future(slow())
        r = await retrieve.search("q", "customers", Deadline(8.0), FakeStore(), FakeEmbedder(), prefetched=task)
        alive = not task.cancelled()                       # shield: the task itself is not cancelled here
        task.cancel()
        return r, alive
    r, alive = run(go())
    assert r.data == [] and r.details["mode"] == "no_retrieval" and r.details["embedding"] == "timeout"
    assert alive
