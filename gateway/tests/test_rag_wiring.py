"""policy_search / procedure_search as the agent sees them (main.BoundTools). Fake store + embedder."""
import asyncio

from app.backend_client import Deadline
from app.identity import Identity
from app.main import BoundTools
from app.rag.embeddings import FakeEmbedder
from app.rag.store import Hit

CUST = Identity("C-100001", "customer", "s1", "tok")
WORK = Identity("W-2001", "worker", "s2", "tok")


class FakeStore:
    def __init__(self):
        self.calls = []

    async def search_keywords(self, text, audience, k=5, allow_doc_ids=()):
        self.calls.append(("keywords", text, audience))
        return [Hit("POL-RET-001", "2.1", "2", 1, "Return Window", "30 days", 0.4)]

    async def search_vectors(self, vec, audience, model_id, k=5, allow_doc_ids=()):
        self.calls.append(("vectors", audience))
        return [Hit("POL-RET-001", "2.1", "2", 1, "Return Window", "30 days", 0.7)]


def tools(identity, store=None, embedder=None):
    return BoundTools(None, identity, Deadline(8.0), store, embedder)


def run(coro):
    return asyncio.run(coro)


def test_customer_policy_search_uses_customer_audience_and_both_texts():
    store = FakeStore()
    r = run(tools(CUST, store, FakeEmbedder()).policy_search("عندي كام يوم أرجّع القميص؟", "return window"))
    assert r.ok and r.details["mode"] == "hybrid" and r.data[0]["cited"] == "POL-RET-001 §2@2.1"
    assert ("keywords", "return window", "customers") in store.calls and ("vectors", "customers") in store.calls


def test_worker_procedure_search_uses_worker_audience():
    store = FakeStore()
    r = run(tools(WORK, store, FakeEmbedder()).procedure_search("أبلّغ إزاي عن شحنة متكسرة؟"))
    assert r.ok and r.details["mode"] == "vector_only" and store.calls == [("vectors", "delivery_workers")]


def test_wrong_role_is_denied_before_any_search():
    store = FakeStore()
    assert run(tools(WORK, store, FakeEmbedder()).policy_search("q")).reason == "wrong_role"
    assert run(tools(CUST, store, FakeEmbedder()).procedure_search("q")).reason == "wrong_role"
    assert store.calls == []


def test_missing_store_is_unavailable_not_a_crash():
    r = run(tools(CUST).policy_search("q"))
    assert r.status == "unavailable" and r.reason == "policy_store_not_configured"
