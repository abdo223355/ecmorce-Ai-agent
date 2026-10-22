# Phase 4 — Step 4: Knowledge & RAG ✅ CLOSED (2026-10-15; D47-b revised at the Phase 4 exit; audit errata applied 2026-10-16/17)

Phase 4 = what/why; numbers = Phase 5; code = Phase 7. Earlier steps: claude/Phase4_AI_Design.md (Step 1) · claude/Phase4_Step2_Agents.md (Step 2) · claude/Phase4_Step3_Tools.md (Step 3).
Audit errata (claude/Phase3_4_Audit.md): round 1 (2026-10-16) — #3 conflict links, #9 adapter path, #12 embedding provider as an external system, #15 scrub before judge+rewrite, #20 D52 scope; round 2 (2026-10-17) — N3 escalate only on a real conflict.

## D47 — Chunking
- One chunk per policy section, with metadata: doc_id, version_id, version, audience, effective date, section number, title, embedding_model_id.
- Tables kept whole, EXCEPT definition tables (Glossary §2): one chunk per row so "what does X mean?" matches well.
- POL-VER-001 §5 register (contains SUPERSEDED and DRAFT rows inside an ACTIVE doc): not indexed for customers/workers (POL-PRV-001 §2/§4, POL-VER-001 §6).
- Cross-reference mentions (e.g. "see PRC-DMG-001") are captured as doc-ID links at indexing time.
- **Conflict links (added, audit #3; semantics fixed, N3):** two sections from different doc_ids may be linked as "same-rule" sections, each with the structured value(s) it states (D13). At answer time CODE compares the linked structured values: if they are equal, nothing happens (the documents agree); if they differ and POL-VER-001 §3 rule 3 (the special-case document applies to its case) does not resolve it, CODE returns POL/P3 — rule 4: "If two ACTIVE documents with different Document IDs conflict and rule 3 does not resolve it, the Gateway must not choose; it escalates." Who records the links and how they are checked at upload → Phase 5 (upload safeguards). Known gap until then: only linked sections are compared.
- The Evaluation category (EVL-RAG-001, EVL-ADV-001) is never indexed (it would leak test questions into retrieval).
- **What is indexed (added, audit #12):** only ACTIVE documents whose Audience includes Customers or Delivery Workers, plus the by-name allow-list entries (POL-SPC-001, D47-a; the use-only Glossary, D47-b). Internal documents that no user may see (e.g. POL-AGE-001, POL-AIS-001, POL-AKU-001, POL-VER-001) are applied by code and templates (D34), not retrieved, so their text is never sent to the embedding vendor.

## D48 — Vector store = pgvector inside the Gateway PostgreSQL (owned by ⑥)
- Fills the D12 "Vector Store" placeholder (form left to Phase 4, CP-4); no new container.
- Filter + search in one query; re-index replaces chunks of (doc_id, version, section) inside ONE transaction, together with indexing_status = DONE (D14-8).
- Filtering joins on version_id from ⑥ only — never on a chunk-level status copy (avoids drift, D14-8 / R-d).
- Retrieval uses its own DB connection pool + statement timeout (no contention with sync audit / queue writes at peak). pgvector load on the shared Gateway DB at 1,000–2,000 users is part of the Phase 5 load test (audit #10).
- Recovery (amends D23 step): chunks are now in the backed-up DB; restored chunks matching the restored rows stay DONE; re-index only when the row has no chunks or embedding_model_id changed.
- Considered: Chroma (needs server mode for N instances, two systems to keep consistent, limited keyword search); Qdrant (stronger, but a separate container + consistency checks). Kept as a later learning option.

## D49 — Embeddings
- One embedding adapter owned by ⑥ (Worker for indexing, instances for queries); provider = config, chosen in Step 8; must be MULTILINGUAL (Arabic + English, D53). If it is the same vendor as the LLM, recorded as a named exception to D19 "one door per external system". **Phase 5 decision (audit #9):** whether the LLM adapter and the embedding adapter move into one leaf "model adapter" module that ⑥ and ⑦ both call (a D19 amendment that also removes this named exception and gives the upload LLM checker a legal path).
- **The embedding provider is a 4th external system (audit #12):** it gets its own ⑧ circuit breaker like every external system (Phase 3: "circuit breaker per external system"). Circuit open → keyword-only search (D51), not P3. Added to the Phase 3 System Context as an amendment. Vendor approval by Security & AI Governance = go-live blocker 7.
- Query text is embedded with personal identifiers removed (POL-PRV-001 §1.4, §3).
- Embedding dimension must fit the pgvector index limit (checked when the model is chosen, Step 8).

## D50 — Agentic RAG, bounded (his choice over my plain-RAG recommendation)
- Amends D37: "no free tool loop, EXCEPT bounded retrieval rounds that use only the filtered search tool."
- Flow: code runs the first search → if the best fused score is above a threshold, no extra LLM call → otherwise ONE combined LLM call judges + rewrites the query → at most K extra rounds (K, threshold → Phase 5).
- **Scrub before judge+rewrite (audit #15):** the search query is scrubbed with the D72 rules (D60-A1 placeholders, no customer / worker / session ids) before it goes to the judge+rewrite LLM call, not only before embedding. The rewritten query is scrubbed again before the next search.
- Cross-references are followed by CODE from the doc-ID links captured at indexing (no LLM call).
- The LLM can only change the query text; code enforces ACTIVE + caller Audience + allow-list on every round.
- Rounds count against ⑪'s deadline and the step counter; stop when the time left is less than reply + validation need. Per-node latency budget and cut order (K → 0 first, then template) → Phase 5 (audit #10).
- Still nothing → ambiguous question: one clarifying question (POL-AGE-001 §4, PRC-DIS-001 §3); unanswered: "required policy not retrieved" → POL/P3 (POL-AIS-001 §3, POL-AGE-001 §2).
- Cost acknowledged against his 20% token target; Step 9 compares plain vs agentic on EVL-RAG-001, now also on p95 latency (D78, audit #10).

## D51 — Retrieval
- Filter first (ACTIVE version ids resolved once per request by ⑥ + caller Audience + allow-list), then hybrid search (vector + PostgreSQL full-text on the ENGLISH search query from the classify call, D53), top-k → Phase 5.
- Validation (D37 step 5) is content-level: code keeps the set of (doc_id, version, section) actually retrieved; the validator rejects any citation outside that set and any number not placed by code or not verifiable against the cited section (D66 check 3).

## D52 — Versions (scope clarified, audit #20)
- SUPERSEDED versions are never RETRIEVED or SHOWN in V1 (stricter than POL-VER-001 §3 rule 5 "may be quoted when the user explicitly asks about historical rules"): historical questions get the current rule + offer of a human.
- Not affected: D21's internal gate read — ⑤ may read the directly superseded version's structured values (never its text) to decide "review required" for an older order under a stricter new rule (POL-VER-001 §4 "customers are not retroactively disadvantaged"). The customer gets template 19 REVIEW_REQUIRED (D68).

## D53 — Languages (his answer "ب")
- Customers and workers may write Arabic (incl. Egyptian) or English. The classify call also outputs an English search query (same call, no extra cost); embeddings are multilingual (D49); the reply language is decided in Step 5.

## D47-b — Allow-lists (REVISED at the Phase 4 exit, his approval 2026-10-16)
- Internal engineering/governance docs (POL-AIS-001, POL-AGE-001, POL-AKU-001, POL-VER-001) stay closed to users and are not indexed (D47, audit #12); their customer questions use D34 templates; EVL expectations re-annotated in Step 9.
- Glossary (REF-GLO-001): its Audience is "All staff, AI Gateway" (not Customers, not Delivery Workers), so under D34 it may be USED but not SHOWN. Until the Policy Office (its owner) adds Customers / Delivery Workers to its Audience or approves named entries, the Glossary is use-only: it may help code / LLM context understand terms, but its text is never quoted or paraphrased to users. After approval, only the approved (doc_id, section) entries may be shown, and D66 check 2 accepts exactly those entries. POL-AKU-001 §2 says where to LOOK for definitions, not what may be shown. Note: the entry "Delivered is not proof of receipt in disputes" is NovaCart's internal dispute position and must never be shown (C12: never argue).
- Status definitions for users come from customer/worker-facing reference docs (REF-OST-001 / REF-RST-001, UNVERIFIED until docs 04–10 are added). Cost accepted: some definition questions become POL/P3 handoffs until the Policy Office answers; counted in ⑩.
- Was (2026-10-15): "Glossary joins both allow-lists (definitions are not sensitive)" — withdrawn because it conflicted with D34 and D66 check 2.

## Review log
- design-auditor on D47–D52: PASS WITH CONCERNS, not ready until D37 amended, allow-list decided, chunk-status drift fixed, language settled → all four settled (D37 amended, drift fixed, D53, D47-b); other fixes applied.
- Phase 4 exit analysis (2026-10-16): Glossary Audience conflict found; D47-b revised (use-only); independent review agreed.
- Phase 3+4 cross-phase audit round 1 (2026-10-16): FAIL (errata) → applied: #3 conflict links; #9 model-adapter question to Phase 5; #12 embedding circuit, indexing scope, vendor blocker; #15 scrub before judge+rewrite; #20 D52 scope + template 19.
- Round 2 (2026-10-17, his "موافق"): N3 code compares the linked structured values and escalates only when they differ.
