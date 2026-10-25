"""Embedding adapter tests: no network, no key."""
import asyncio
import json
import math

import httpx

from app.rag.embeddings import EmbedResult, EmbeddingAdapter, FakeEmbedder, OpenRouterEmbedder


def run(coro):
    return asyncio.run(coro)


def embedder(handler, **kw) -> OpenRouterEmbedder:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenRouterEmbedder(model="test/embed", api_key="k", base_url="http://emb.test", client=client, **kw)


def answer(vectors, shuffled=False):
    rows = [{"index": i, "embedding": v} for i, v in enumerate(vectors)]
    return httpx.Response(200, json={"data": list(reversed(rows)) if shuffled else rows})


def echo(req):
    n = len(json.loads(req.read())["input"])
    return answer([[3.0, 4.0, float(i)] for i in range(n)])


def test_vectors_are_unit_length_and_in_input_order_even_if_api_shuffles():
    def handler(req):
        return answer([[1.0, 0.0], [0.0, 2.0]], shuffled=True)

    r = run(embedder(handler).embed_documents(["a", "b"], 1.0))
    assert r.ok and r.dim == 2 and r.model_id == "test/embed"
    assert r.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert all(math.isclose(math.hypot(*v), 1.0) for v in r.vectors)


def test_documents_are_sent_in_batches():
    sizes = []

    def handler(req):
        sizes.append(len(json.loads(req.read())["input"]))
        return echo(req)

    r = run(embedder(handler, batch_size=32).embed_documents([f"t{i}" for i in range(70)], 1.0))
    assert r.ok and len(r.vectors) == 70 and sizes == [32, 32, 6]


def test_prefixes_apply_to_the_right_method_only():
    seen = []

    def handler(req):
        seen.append(json.loads(req.read())["input"])
        return echo(req)

    e = embedder(handler, query_prefix="query: ", document_prefix="passage: ")
    run(e.embed_documents(["policy"], 1.0))
    run(e.embed_query("question", 1.0))
    assert seen == [["passage: policy"], ["query: question"]]


def test_http_errors_and_timeout_and_network_map_to_statuses():
    assert run(embedder(lambda r: httpx.Response(429)).embed_query("q", 1.0)).status == "rate_limited"
    assert run(embedder(lambda r: httpx.Response(401)).embed_query("q", 1.0)).reason == "auth_failed"
    assert run(embedder(lambda r: httpx.Response(500)).embed_query("q", 1.0)).status == "unavailable"

    async def slow(req):
        await asyncio.sleep(1)
        return echo(req)

    assert run(embedder(slow).embed_query("q", 0.05)).status == "timeout"

    def boom(req):
        raise httpx.ConnectError("down")

    assert run(embedder(boom).embed_query("q", 1.0)).status == "unavailable"


def test_bad_responses_are_bad_output():
    assert run(embedder(lambda r: httpx.Response(200, json={"oops": 1})).embed_query("q", 1.0)).status == "bad_output"
    assert run(embedder(lambda r: answer([[1.0], [2.0]])).embed_query("q", 1.0)).reason == "wrong_count_or_dimension"
    assert run(embedder(lambda r: answer([[1.0, 2.0], [1.0]])).embed_documents(["a", "b"], 1.0)).status == "bad_output"


def test_a_failed_batch_fails_the_whole_call():
    calls = []

    def handler(req):
        calls.append(1)
        return echo(req) if len(calls) == 1 else httpx.Response(429)

    r = run(embedder(handler, batch_size=2).embed_documents(["a", "b", "c", "d"], 1.0))
    assert r.status == "rate_limited" and r.vectors == []


def test_not_configured_makes_no_call(monkeypatch):
    from dataclasses import replace
    from app.rag import embeddings
    monkeypatch.setattr(embeddings, "settings", replace(embeddings.settings, embed_model="", openrouter_api_key=""))
    monkeypatch.setattr(embeddings, "EMBEDDING_MODEL", "")
    r = run(OpenRouterEmbedder().embed_query("q", 1.0))
    assert r.status == "unavailable" and r.reason == "embedding_not_configured"


def test_fake_is_deterministic_and_close_for_shared_words():
    f = FakeEmbedder()
    docs = run(f.embed_documents(["return window thirty days", "delivery worker access policy"], 1.0)).vectors
    q = run(f.embed_query("return window", 1.0)).vectors[0]
    score = [sum(a * b for a, b in zip(q, d)) for d in docs]
    assert score[0] > score[1]
    assert run(f.embed_query("return window", 1.0)).vectors[0] == q
    assert [c[0] for c in f.calls] == ["documents", "query", "query"]


def test_fake_can_simulate_a_failure_and_shares_the_interface():
    f = FakeEmbedder(fail_with=EmbedResult("timeout", reason="x"))
    assert run(f.embed_query("q", 1.0)).status == "timeout"
    assert issubclass(FakeEmbedder, EmbeddingAdapter) and issubclass(OpenRouterEmbedder, EmbeddingAdapter)


def test_dimensions_default_to_768_and_can_be_overridden(monkeypatch):
    from dataclasses import replace
    from app.rag import embeddings
    monkeypatch.setattr(embeddings, "settings", replace(embeddings.settings, embed_dimensions=0))
    seen = []

    def handler(req):
        seen.append(json.loads(req.read()))
        return echo(req)

    run(embedder(handler).embed_query("q", 1.0))
    run(embedder(handler, dimensions=512).embed_query("q", 1.0))
    assert seen[0]["dimensions"] == 768 and seen[1]["dimensions"] == 512


def test_default_http_client_has_no_hidden_5_second_timeout():
    # httpx's default (5 s) used to cut calls before our own deadline; only asyncio.wait_for may decide.
    from app.llm.openrouter import OpenRouterAdapter
    assert OpenRouterEmbedder(model="m", api_key="k")._client.timeout.read is None
    assert OpenRouterAdapter(model="m", api_key="k")._client.timeout.read is None
