"""Policy store tests.

Unit tests need nothing. Integration tests need the Gateway PostgreSQL with pgvector
(docker compose: GATEWAY_DATABASE_URL). They use a throwaway schema and drop it; they skip if the DB is down.
"""
import asyncio
import uuid

import pytest

from app.rag.models import Chunk
from app.rag.store import PolicyStore, plain_dsn, to_vector_literal

DIMS = 4
MODEL = "test/embed"


def chunk(doc="POL-RET-001", version="2.1", status="ACTIVE", audience=("customers",), section="2",
          title="Return Window", text="The standard window is 30 calendar days.", part=1):
    return Chunk(doc_id=doc, doc_title="Return Policy", version=version, status=status, audience=audience,
                 section=section, title=title, text=text, part=part)


# ---------- unit ----------

def test_vector_literal_and_dsn():
    assert to_vector_literal([1, 0.5, -2]) == "[1.0,0.5,-2.0]"
    assert plain_dsn("postgresql+psycopg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert plain_dsn("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


def test_bad_schema_name_is_refused():
    with pytest.raises(ValueError):
        PolicyStore(dsn="postgresql://x/y", schema="public; DROP TABLE x")


def test_input_checks_before_any_database_call():
    store = PolicyStore(dsn="postgresql://x/y", dims=DIMS)      # pool is never opened
    with pytest.raises(ValueError):
        asyncio.run(store.replace_version([chunk()], [[1, 0, 0]], MODEL))                  # wrong size
    with pytest.raises(ValueError):
        asyncio.run(store.replace_version([chunk(), chunk(version="2.0")], [[1, 0, 0, 0]] * 2, MODEL))
    with pytest.raises(ValueError):
        asyncio.run(store.replace_version([chunk()], [], MODEL))


# ---------- integration (real pgvector) ----------

def with_store(body):
    async def go():
        store = PolicyStore(schema=f"rag_test_{uuid.uuid4().hex[:8]}", dims=DIMS, statement_timeout_ms=5000)
        try:
            await store.open(wait=True, timeout=5)
        except Exception as e:                                     # no database here -> skip, do not fail
            await store.close()
            pytest.skip(f"Gateway DB not reachable: {type(e).__name__}")
        try:
            await store.ensure_schema()
            await body(store)
        finally:
            await store.drop_schema()
            await store.close()
    asyncio.run(go())


def test_search_returns_nearest_active_chunks_with_citation():
    async def body(s):
        await s.replace_version([chunk(section="2", text="return window"), chunk(section="3", text="eligibility")],
                                [[1, 0, 0, 0], [0, 1, 0, 0]], MODEL)
        hits = await s.search_vectors([0.9, 0.1, 0, 0], "customers", MODEL)
        assert [h.section for h in hits] == ["2", "3"]
        assert hits[0].cited == "POL-RET-001 §2@2.1" and hits[0].score > hits[1].score
    with_store(body)


def test_one_status_update_hides_every_chunk_of_that_version():
    """The drift lesson: status lives on the version row, so ONE update changes all its chunks at once."""
    async def body(s):
        await s.replace_version([chunk(version="2.0", section=str(i)) for i in range(1, 4)], [[1, 0, 0, 0]] * 3, MODEL)
        await s.replace_version([chunk(version="2.1", section="1")], [[1, 0, 0, 0]], MODEL)
        assert {h.version for h in await s.search_vectors([1, 0, 0, 0], "customers", MODEL)} == {"2.0", "2.1"}
        assert await s.set_status("POL-RET-001", "2.0", "SUPERSEDED") is True
        assert {h.version for h in await s.search_vectors([1, 0, 0, 0], "customers", MODEL)} == {"2.1"}
        assert await s.set_status("POL-RET-001", "9.9", "SUPERSEDED") is False
    with_store(body)


def test_draft_and_superseded_are_never_returned():
    async def body(s):
        await s.replace_version([chunk(version="3.0", status="DRAFT")], [[1, 0, 0, 0]], MODEL)
        await s.replace_version([chunk(version="1.0", status="SUPERSEDED")], [[1, 0, 0, 0]], MODEL)
        assert await s.search_vectors([1, 0, 0, 0], "customers", MODEL) == []
        assert await s.search_keywords("window", "customers") == []
    with_store(body)


def test_audience_filter_and_allow_list():
    async def body(s):
        await s.replace_version([chunk(doc="PRC-DMG-001", audience=("delivery_workers",), text="damaged parcel photos")],
                                [[1, 0, 0, 0]], MODEL)
        await s.replace_version([chunk(doc="POL-SPC-001", audience=("delivery_workers",), text="special cases")],
                                [[0, 1, 0, 0]], MODEL)
        assert await s.search_vectors([1, 0, 0, 0], "customers", MODEL) == []                 # workers only
        assert len(await s.search_vectors([1, 0, 0, 0], "delivery_workers", MODEL)) == 2
        allowed = await s.search_vectors([1, 0, 0, 0], "customers", MODEL, allow_doc_ids=("POL-SPC-001",))
        assert [h.doc_id for h in allowed] == ["POL-SPC-001"]                                  # by-name allow-list
    with_store(body)


def test_reindex_replaces_instead_of_duplicating():
    async def body(s):
        for _ in range(3):
            await s.replace_version([chunk(section="1"), chunk(section="2")], [[1, 0, 0, 0]] * 2, MODEL)
        assert (await s.counts())["ACTIVE"] == {"versions": 1, "chunks": 2}
    with_store(body)


def test_failed_reindex_leaves_the_old_version_untouched():
    """One transaction: if inserting the new chunks fails half way, nothing of the new write is kept."""
    async def body(s):
        await s.replace_version([chunk(section="1", text="old text")], [[1, 0, 0, 0]], MODEL)
        bad = [chunk(section="1", text="new text"), chunk(section=None, text="breaks NOT NULL")]
        with pytest.raises(Exception):
            await s.replace_version(bad, [[1, 0, 0, 0]] * 2, MODEL)
        hits = await s.search_vectors([1, 0, 0, 0], "customers", MODEL)
        assert [h.text for h in hits] == ["old text"]
    with_store(body)


def test_vectors_from_another_model_are_not_mixed_in():
    async def body(s):
        await s.replace_version([chunk()], [[1, 0, 0, 0]], "old/model")
        assert await s.search_vectors([1, 0, 0, 0], "customers", MODEL) == []
        assert len(await s.search_vectors([1, 0, 0, 0], "customers", "old/model")) == 1
    with_store(body)


def test_keyword_search_finds_exact_terms():
    async def body(s):
        await s.replace_version([chunk(section="2", title="Return Window", text="Electronics have 15 days."),
                                 chunk(section="5", title="Defective Items", text="Report damaged items within 24 hours.")],
                                [[1, 0, 0, 0], [0, 1, 0, 0]], MODEL)
        hits = await s.search_keywords("damaged items", "customers")
        assert [h.section for h in hits] == ["5"]
        assert await s.search_keywords("gift cards", "customers") == []
    with_store(body)
