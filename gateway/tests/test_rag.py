"""Chunking tests on a small synthetic policy text (same shape as pdftotext output). No PDF needed."""
from app.rag import chunking
from app.rag.chunking import chunk_document, parse_header

DOC = """NOVACART - SYNTHETIC DOCUMENT FOR SOFTWARE/RAG TESTING ONLY (FICTIONAL)

Return Policy
NovaCart Document POL-RET-001 - Version 2.1 - Status: ACTIVE

Document Metadata
Document ID: Title: Category: Audience: Version: Status: Effective Date: Supersedes:

POL-RET-001 Return Policy Customer Policy Customers, Customer Service, AI Gateway 2.1 ACTIVE 2026-09-01 POL-RET-001 v2.0

Table of Contents
1. Purpose and Scope 2. Return Window 3. Escalation

1. Purpose and Scope
This policy defines which items may be returned. It governs eligibility only.

2. Return Window

The standard window is 30 calendar days. The window starts at delivery.

1. A numbered step inside the section must not become a heading.

NovaCart | POL-RET-001 | v2.1 | ACTIVE | Effective 2026-09-01

Page 1

NOVACART - SYNTHETIC DOCUMENT FOR SOFTWARE/RAG TESTING ONLY (FICTIONAL)

The window ends at 23:59 Cairo time.

3. Escalation
Contact Customer Service when unsure.
"""


def test_header_and_audience():
    h = parse_header(DOC.split("\n"))
    assert (h["doc_id"], h["version"], h["status"], h["doc_title"]) == ("POL-RET-001", "2.1", "ACTIVE", "Return Policy")
    assert h["audience"] == ("customers",)        # "Customer Policy" / "Customer Service" do not count


def test_audience_workers_and_none():
    base = DOC.replace("Customers, Customer Service, AI Gateway", "Delivery Workers, Dispatch, AI Gateway")
    assert parse_header(base.split("\n"))["audience"] == ("delivery_workers",)
    none = DOC.replace("Customers, Customer Service, AI Gateway", "Customer Service, AI Gateway")
    assert parse_header(none.split("\n"))["audience"] == ()


def test_one_chunk_per_section_and_toc_is_skipped():
    chunks = chunk_document(DOC, "02_Return_Policy.pdf")
    assert [(c.section, c.title) for c in chunks] == [("1", "Purpose and Scope"), ("2", "Return Window"), ("3", "Escalation")]
    assert all(c.doc_id == "POL-RET-001" and c.source_file == "02_Return_Policy.pdf" for c in chunks)


def test_page_noise_removed_and_section_continues_across_pages():
    c2 = chunk_document(DOC)[1]
    assert "NOVACART - SYNTHETIC" not in c2.text and "NovaCart |" not in c2.text and "Page 1" not in c2.text
    assert "starts at delivery" in c2.text and "ends at 23:59" in c2.text


def test_citation_and_embed_text():
    c = chunk_document(DOC)[1]
    assert c.cited == "POL-RET-001 §2@2.1"
    assert c.embed_text.startswith("Return Policy — §2 Return Window")


def test_overlap_goes_to_embedding_only_and_is_small():
    a, b, _ = chunk_document(DOC)
    assert a.context_before == ""
    assert b.context_before == "It governs eligibility only."          # last sentence of the previous section
    assert "It governs eligibility only." not in b.text                  # not in the cited text
    assert b.context_before in b.embed_text
    assert len(b.context_before.split()) <= chunking.OVERLAP_MAX_WORDS


def test_overlap_is_cut_to_max_words(monkeypatch):
    monkeypatch.setattr(chunking, "OVERLAP_MAX_WORDS", 3)
    assert chunk_document(DOC)[1].context_before == "governs eligibility only."


def test_long_section_is_split_with_overlap(monkeypatch):
    monkeypatch.setattr(chunking, "MAX_WORDS", 10)
    long_doc = DOC.replace("This policy defines which items may be returned. It governs eligibility only.",
                           "First paragraph has seven words here now.\n\nSecond paragraph also has many words. Last words end here.")
    first = [c for c in chunk_document(long_doc) if c.section == "1"]
    assert [c.part for c in first] == [1, 2]
    assert first[1].context_before == "First paragraph has seven words here now."


def test_missing_header_raises():
    try:
        chunk_document("no header here\n1. A\ntext")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_numbered_steps_that_end_with_a_period_are_not_headings():
    doc = DOC.replace("3. Escalation\nContact Customer Service when unsure.",
                      "3. Escalation\n1. Check the task list.\n2. Wait for Dispatch.\n3. Do not open other parcels.\n"
                      "4. Report it in the app.\n5. Close the task.")
    assert [c.section for c in chunk_document(doc)] == ["1", "2", "3"]


def test_no_overlap_when_previous_section_ends_with_a_table_row():
    doc = DOC.replace("The window ends at 23:59 Cairo time.", "Gift cards and digital goods Not returnable No exceptions")
    assert chunk_document(doc)[2].context_before == ""
