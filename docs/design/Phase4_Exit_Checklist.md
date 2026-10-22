# Phase 4 — AI Design: Exit checklist ✅ PHASE 4 CLOSED (2026-10-16, his "موافق") · cross-phase audit errata applied (round 1: 2026-10-16; round 2: 2026-10-17, his "موافق")

Phase 4 decided WHAT and WHY for the AI part of the Adaptive AI Gateway (decisions D30–D80). Numbers go to Phase 5 (Reliability & Safety) and later; code goes to Phase 7 (Implementation); running the evals goes to Phase 8 (Testing & Evaluation).
Diagram: Claude Design canvas "Agent Graph — Adaptive AI Gateway" (https://claude.ai/artifact/R2beVHH7LC5Gp1raz2HRYy). Step docs: claude/Phase4_AI_Design.md (Step 1) and claude/Phase4_Step2…9_*.md. Design scenario tests: claude/Phase4_Scenario_Tests.md. Cross-phase audit: claude/Phase3_4_Audit.md.

## 1. Exit criteria
| # | Criterion | Status |
|---|---|---|
| 1 | All 9 steps closed, each with an independent design review and fixes applied | ✅ Steps 1–9 closed; every batch reviewed (design-auditor), fixes in each doc's review log |
| 2 | Every Phase 3 item deferred to "AI Design" has an answer (section 3) | ✅ 9 of 11 answered; 1 partly answered (LLM checker path → Phase 5); 1 closed under a signed exception ("talk to a human" code). Corrected by the audit (was "9 of 10 answered; 1 partly") |
| 3 | Decision references are consistent across the docs (section 4) | ✅ 4 errata fixed + 1 conflict resolved at the exit; the cross-phase audit found 23 + 11 more (section 4b), all applied |
| 4 | Nothing invented beyond the policies: design choices labelled, gaps = owner questions | ✅ (section 6); D35 row 2 relabelled as an interpretation that amends D15 (audit #13); D44 flags labelled an assumption (N11) |
| 5 | Open owner questions listed, each with an interim rule so nothing blocks | ✅ (section 6), incl. the open Phase 3 questions (audit #8) |
| 6 | Calls Claude made on his behalf, analysed and reviewed, confirmed by him | ✅ approved 2026-10-16 (section 5) |
| 7 | Design tested on realistic scenarios | ✅ 17 scenarios (F1–F5 fixed, F6 accepted cost) + 8 audit scenarios + 3 round-2 scenarios (all fixed by the errata) |
| 8 | Numbers and later-phase work handed over (sections 7–8), go-live blockers listed (section 5b) | ✅ |
| 9 | A clean diagram of the whole agent graph | ✅ Claude Design canvas (updated with the exit changes and the audit errata) |

## 2. Decision index (one line each)
- **Step 1 Intents (D30–D35):** C1–C14 (C14 account problem after login, added by the audit) and W1–W9; D30 multi-intent in one reply; D31 neutral out-of-scope; D32 missing order (clues → typed ID → 404 counted; 3 rounds INFO/P4; 3 denials AUTH/P2; UNVERIFIED vs PRC-MIS-001); D33 several handoffs from one message; D34 use vs show (Audience); D35 worker denials (amended by D41; row 2 = interpretation amending D15). Plus: holiday extensions and exception requests (C2/C5), conflicting ACTIVE documents → POL/P3.
- **Step 2 Agents & graph (D36–D42):** D36 two agents chosen by CODE from the token role; D37 ⑪ P1 pattern check (step 0, before the agent) → classify → safety gate → plan → reply → validate (amended by D50, clarified by D73; classify failure → ⑪'s full code classifier, not a user attempt); D38 per-request State; D39 no routing between agents; D40 first N parts; D41 denial counting split + a worker ID word-for-word as the only evidence for query denials + one shared denial recorder; D42 escalation flags on every part (unverified IDs only from the user's own list).
- **Step 3 Tools (D43–D46, D47-a):** D43 tool lists (+ "another worker's list" enum value); D44 missing data + item category and flags (assumption for the backend owner); D45 customer denials; D46 MCP in-process (his choice, thin handlers); D47-a POL-SPC-001 on the customer allow-list; queued-job rule (③-resolved prefetch, merged deferred handoff on a missing record, prefetch 404 not queued); shaping and denial recording in ④/⑤, templates + code classifier + P1 check owned by ⑪.
- **Step 4 RAG (D47–D53, D47-b):** D47 section chunking + conflict links (escalate only when linked values differ) + indexing scope; D48 pgvector in the Gateway DB; D49 multilingual embedding adapter, embedding provider = 4th external system with its own circuit; D50 bounded agentic RAG (his choice; scrubbed judge+rewrite); D51 filter-first hybrid search; D52 SUPERSEDED never retrieved or shown (D21 gate read kept); D53 Arabic + English; D47-b governance docs closed, Glossary use-only.
- **Step 5 Prompts (D54–D59, D60-A1):** D54 prompt types + versioning; D55 minimum context; D56 injection delimiters, free-text backend fields always placeholders; D57 reply language and style (+ Arabizi); D58 strict classify JSON, P1 never depends on classify (narrow phrase patterns), failure → full code classifier; D59 token caps + caching order; D60-A1 placeholders (day counts too; structured-value numbers always placeholders; other policy numbers matched as number + unit against the cited section).
- **Step 6 Memory (D61–D65):** structured per-turn cards in Redis (clue field = product and date clues only); code-built summary ("why?" re-fetches the cited section); no long-term memory in V1; memory never holds identity/denials/personal data; chat = login session, missing memory = fresh start, lost context not counted.
- **Step 7 Guardrails (D66–D70):** D66 nine validate checks (check 3 code-verifiable numbers), two failure classes; D67 internal topics; D68 19 templates rendered by ⑪ (15 with the emergency line, 19 REVIEW_REQUIRED; P1 no-data flag only for takeover / data exposure); D69 no streaming; D70 reason codes + PENDING_OWNER, highest severity wins within one case, static fallback only when the Ticketing circuit is open or the DB is down.
- **Step 8 Model, cost & latency (D71–D75):** D71 model per node + bake-off, no backup model, provider fallback = routing inside one adapter call among evaluated providers; D72 hosted multilingual embedding (vendor = blocker 7); D73 fast path (System 1 / System 2); D74 caching under no-retention + 20% measured per resolved request; D75 parallel after the safety gate inside 8 s, timeout → template 18, per-node budget → Phase 5. Plus: P1 patterns first in EVERY mode; one full code classifier (incl. complaint → CMP) for Degraded mode and classify failure; unrecognised → queue (customers, Degraded) / template 15 (customers, classify failure) / handoff (workers).
- **Step 9 Evaluation (D76–D80):** three layers L1/L2/L3 (+ cases for every audit fix, incl. "P1 must not trigger" and enumeration through templates); code scoring first, L3 zero tolerance with repeated runs; three experiments (experiment 1 now also judged on p95) + held-out split; data rules; when to run.

## 3. Phase 3 items deferred to AI Design
| Phase 3 item | Answered by |
|---|---|
| Which fields may be sent to the LLM provider | D55, D56, D60-A1 (placeholders), D38 |
| Token reduction: templates, routing, caching, model tiers | D71–D74 |
| "number 2" → a specific order | D55 (code resolves), D61 (cards), D65 (lost context) |
| Agent roles, router, planner, memory, human-in-the-loop thresholds | D36–D42, D61–D65, escalation via POL-AGE-001 |
| Retrieval filtered by ACTIVE version id; no duplicate chunks | D48, D51 |
| Old (SUPERSEDED) versions never used to explain while Business Rules uses the new one (Phase 3 open question, closed there) | D51 filter by ACTIVE version ids, D52 (never retrieved or shown). Added by the audit (#19) |
| Template set and matching | D68 (19 templates, rendered by ⑪) |
| Streaming in normal mode | D69 (no streaming) |
| Path for embedding calls | D49, D72 (⑥ adapter; named exception to D19 if same vendor as the LLM; one shared "model adapter" module is a Phase 5 decision) |
| Path for the LLM checker at upload | ⚠ PARTLY: not decided in Phase 4. The earlier recommendation ("through ⑦'s single LLM adapter") was withdrawn by the audit (#9): the Background Worker never runs ⑦ (D18) and ⑥ → ⑦ is an upward call (D19). Phase 5 decides whether the LLM and embedding adapters move into one leaf "model adapter" module that ⑥ and ⑦ both call (a D19 amendment), together with the upload safeguards (CP-9) |
| Reason code for "talk to a human" — "must be answered before AI Design finishes the escalation design" | ⚠ Still an owner question. Closed Phase 4 under an exception signed by عبدالرحمن on 2026-10-16 (section 5, item 8); interim rule D70; go-live blocker 2 |

## 4. Consistency check (done 2026-10-16)
Read all nine step docs against each other. Found and fixed:
1. Step 7 template 15 cited D57 for classify failure → corrected to D58 (fail closed).
2. Step 8 D72 cited "D59 placeholder scrubber" → corrected to D60-A1, and linked to D49's identifier-removal rule, which already said the same.
3. Step 8 D74 cited "D58 caps" → corrected to D59.
4. D37 says "one reply call for all parts", while D73 sends fast-path parts to templates → recorded in Step 8 as a clarification: the single reply call covers only the System 2 parts.
5. REF-GLO-001's Audience is "All staff, AI Gateway" — not Customers or Delivery Workers — so showing Glossary text (old D47-b) conflicted with D34 and with D66 check 2 → resolved: Glossary use-only (D47-b revised).
Known in learning material only (not re-issued): Step7_Guardrails_Explained.pptx says "D59" for placeholders and "D57" for classify JSON; Step8_Model_Cost_Latency_Options.pptx says "D58" for token caps; the Step 9 deck and the Step 7 deck describe the pre-exit versions (15 templates, per-part failure only). The docs are the source of truth.

## 4b. Cross-phase audit Phase 3 × Phase 4 — round 1 FAIL → round 2 PASS WITH CONCERNS → all errata applied
Report: claude/Phase3_4_Audit.md.
**Round 1 (2026-10-16, his "موافق" 19:32):** 4 ❌ + 19 ⚠️, no redesign. Where each fix landed:
- #1 P1 not detected when classify fails → Step 2 (graph), Step 5 D58, Step 7 template 15, Step 8 (P1 check in every mode).
- #2 workers in the Degraded queue → Step 8 (workers → handoff, never 202).
- #3 holiday extensions, exception requests, conflicting ACTIVE documents → Step 1 (C2, C5, cross-cutting), Step 3, Step 4 D47 conflict links, Step 7 template 12; link mechanics → Phase 5.
- #4 day counts → Step 5 D60-A1, Step 7 check 3.
- #5 policy numbers → Step 5 D60-A1, Step 7 check 3.
- #6 queued jobs → Step 3.
- #7 PENDING_OWNER and static fallback → Step 7 D70, template 5.
- #8 open Phase 3 questions → section 6 + blockers 2 and 8.
- #9 LLM checker path → section 3, Step 4 D49; decision → Phase 5.
- #10 latency budget → Step 8 D75, Step 9 D78; numbers → Phase 5.
- #11 module ownership → Step 3, Step 7 D68, Step 8.
- #12 embedding provider → Step 4 D47/D49, Step 8 D72, blocker 7.
- #13 denial definition → Step 1 D35, Step 2 D41, Step 3; Phase 3 doc amendment note.
- #14 "why?" follow-ups → Step 6 D62, Step 7 check 2.
- #15 personal data → Step 5 D55/D56, Step 4 D50, Step 6 D61.
- #16 missing docs → Step 1 tags, blocker 6.
- #17 account problems after login → Step 1 C14, template 9.
- #18 severity scope → Step 7 D70, Step 1 D33.
- #19 superseded text → Phase 3 doc amendment notes, Steps 1–2 notes, Scenario doc, sections 1 and 3 here.
- #20 D52 vs D21 → Step 4 D52, template 19.
- #21 provider fallback → Step 8 D71.
- #22 unverified IDs in tickets → Step 2 D42.
- #23 item category and flags → Step 3 D44.
**Round 2 (re-verification 2026-10-16; his "موافق" 2026-10-17 00:41):** 19 RESOLVED, 4 PARTLY, 0 NOT RESOLVED; 11 new findings, all applied:
- N1 P1 patterns over-trigger → Step 2, Step 5 D58, Step 8: phrase patterns for takeover / exposure / danger only; Step 7 template 8: no-data flag only for takeover / data exposure; Step 9 "must not trigger" cases; blocker 3 sign-off.
- N2 denials not counted on ⑪'s template path → Step 3 shared denial recorder, Step 2 D41, Step 9 L3 enumeration case.
- N3 conflict links escalated agreeing documents → Step 4 D47 (compare values, escalate only on a difference).
- N4 number matching → Step 5 D60-A1, Step 7 check 3 (structured-value numbers must be placeholders; number + unit normalised across Arabic / English).
- N5 queued-job gaps → Step 3 (③-resolved prefetch, merged deferred handoff, prefetch 404 not queued); Phase 3 amendments table.
- N6 P1 in a later queued message → section 6 interim rule (sibling line + "hold").
- N7 stale status docs → fixed (CP-107).
- N8 classify-failure path incomplete → Step 2, Step 5 D58, Step 8 (full code classifier incl. complaint → CMP; not a user attempt).
- N9 step 0 wording → Step 2 D37 (runs in ⑪ before the agent).
- N10 name as evidence → Step 2 D41, Step 3 (worker ID only).
- N11 D44 flags → Step 3 (ASSUMPTION), section 6 backend-owner row.
**Round 2 re-check (2026-10-17, fresh independent reviewer, read-only):** PASS WITH CONCERNS — all N-findings in the text; consistency fixes applied the same night: classify failure for workers → template 6 handoff in Step 2 / D58 (F1); diagram shows step 0 in ⑪ before classify and the classify-failure branch (F2); status records, dates and "pattern" wording (F3); the "not a user attempt" rule labelled an interpretation (F4); Phase 3 citation → D68 template 8 (F5); later queued messages end HANDED_OFF (F8); unlinkable conflict links → Phase 5 (F9). Two small decisions F6 (worker P1 cases: SAFE + Dispatch routing field + templates 8 + 6 with the procedure step) and F7 ("hold" note only when the P1 sets the no-data flag) — approved by him ("موافق", 2026-10-17 10:27) and applied (Step 1 W7, Step 2, Step 8, §6).

## 5. Calls Claude made — analysed, independently reviewed, revised, APPROVED by him (2026-10-16)
Independent review (design-auditor): PASS WITH CONCERNS — "agree with change" on all 8. All revisions applied to the step docs.
| # | Where | Approved rule |
|---|---|---|
| 1 | D47-b Glossary | Governance docs closed; Glossary use-only until the Policy Office approves named entries; then only those (doc_id, section) entries are shown and D66 check 2 accepts exactly those |
| 2 | D57 Arabizi | Arabizi → Arabic script (Egyptian) when classify is confident, else English; Arabizi variants in the P1, injection and code-classifier pattern lists; Arabizi eval cases |
| 3 | D66 failure | Security failure anywhere → whole reply → handoff; content failure → per part (template, else handoff); no retry |
| 4 | D70 PENDING_OWNER | Kept; highest-severity code wins (within one case, audit #18); static fallback only when the Ticketing circuit is open or the DB is down (audit #7) |
| 5 | Degraded classifier | P1 patterns FIRST (phrase patterns for takeover / exposure / danger, Arabizi) — in every mode (audit #1, N1) — then the full code classifier, else the 3-minute queue for customers / handoff for workers (audit #2); templates via the ④/⑤ shaping functions, rendered by ⑪ (audit #11) |
| 6 | D71 no backup model | Kept; provider fallback only among evaluated, no-retention providers, as routing inside one adapter call within the 8 s budget (audit #21); revisit in Phase 9 |
| 7 | D78 held-out | Frozen before prompt tuning, pinned to doc versions, refreshed after each release review; counts reported |
| 8 | Closing with PENDING_OWNER | Exception to the Phase 3 gate SIGNED by عبدالرحمن ("موافق", 2026-10-16); go-live blocker |
Scenario-test fixes approved the same day: F1 template rename; F2 templates 16–17 + enum value; F3 numbers placed by code only (refined by audit #4/#5 and N4); F4 lost context; F5 template 18; F6 cost counted in ⑩.

## 5b. Go-live blockers (must be cleared before V1 goes live)
1. Contract test with the Ticketing owner: PENDING_OWNER code and missing priority are accepted AND routed to a real queue (Phase 5).
2. Owner decision on the reason code and priority for "talk to a human", the human-now button and the Degraded queue timeout (Customer Operations; the queue-timeout code covers most handoffs at peak — audit #8).
3. P1 pattern detection runs first in EVERY mode (normal, classify failure, Degraded), with Arabizi coverage; the pattern list covers takeover / data exposure / physical danger, plus worker hazard / exposure and suspected theft for delivery workers (patterns depend on the role — e.g. "stolen" is P1 for a worker, not for a customer; Phase 5 D103 + review fix 8), and is signed off by Security & AI Governance; tested in L3 for both hits and "must not trigger" cases (Phase 5 / 8; audit #1, N1).
4. Policy Office decision on showing Glossary entries (until then: use only).
5. Ticketing capacity for the burst of handoffs from the Degraded queue at 1,000–2,000 users (Phase 5).
6. Corpus docs 04–10 (POL-ESC-001, PRC-MIS-001, POL-COM-001, REF-OST-001, REF-RST-001, POL-ACC-001, POL-IDV-001) present and checked against D30–D80; ④ cannot implement POL-AGV-001 §3 status validation without REF-OST-001 / REF-RST-001 (audit #16).
7. Embedding vendor approved by Security & AI Governance, incl. which documents may be sent (audit #12); widened by Phase 5 (D111 + Step 5 review fix 7): the LLM vendor and every provider OpenRouter routes to are approved too (no retention, no training, deletion, data-handling terms).
8. Ticketing can route to Dispatch (D26 routing field), or an agreed alternative; PRC-MSG-001 §5 "always notify Dispatch for a missing shipment" depends on it (audit #8).

## 6. Owner questions (open) — each has an interim rule
| Question | Owner | Interim rule |
|---|---|---|
| Reason codes for: talk to a human, human-now button, queue timeout, unclassified intent (incl. an unrecognised worker message in Degraded mode), delivered-not-received, worker complaint, validation failed with no template | Customer Operations | PENDING_OWNER + POL-AGE-001 priority where it gives one (D70); highest severity wins within one case |
| Reason code for a worker's P1 shipment cases (hazardous / leaking, suspected theft) | Customer Operations / Dispatch | SAFE + P1 + Dispatch routing field (design choice, F6, approved 2026-10-17) |
| Priority for "user asks for a human" (POL-AGE-001 §3 optional) | Customer Operations | none set; handoff still created |
| May Glossary (REF-GLO-001) entries be shown to customers / workers? | Policy Office | use only, not shown |
| Can Ticketing link sibling tickets? | Customer Operations / Ticketing | content-free sibling line (D33) |
| Backend owner: 404 for migrated unlinked orders? Does the backend store a sale label set at purchase and custom-made / pre-order facts (D44 flags, N11)? | Backend owner | migration: handoff with migration note (POL-SPC-001 §8); flags: mock backend has them (ASSUMPTION); a missing flag → handoff, never a guess |
| Which internal facts may customers be told, and who decides | Customer Operations | D34 templates only |
| Official holiday dates; ad-hoc hour changes; Gateway ticket reply window | Customer Operations | structured values entered at upload; until then "a CS agent will reply" without a time |
| "High-value" shipment; priority for damage with suspected theft | Dispatch / Customer Operations | escalate without inventing a priority |
| Is pre-purchase product advice in scope? | Business | out of scope (D31) |
| Priority for missing-data handoffs (D44) | Customer Operations | POL-ESC-001 UNVERIFIED |
| Fast-path intent list sign-off (D73); template wording review (D68, 19 templates) | Customer Operations | initial lists in D68/D73 |
| P1 pattern list sign-off (N1) | Security & AI Governance | initial phrase patterns for takeover / exposure / danger; go-live blocker 3 |
| Embedding vendor; may scrubbed text and user-audience documents go to a hosted API? (D72) | Security & AI Governance | hosted, no-retention, scrubbed; self-hosted fallback (needs a container design); go-live blocker 7 |
| Does time in Degraded mode count toward the 99% availability target? | Business / Operations | Phase 5 question |
| Missing corpus docs 04–10 and EVL-ADV-001 | عبدالرحمن (on his computer) | rules marked UNVERIFIED; eval cases BLOCKED; go-live blocker 6 |
| **From Phase 3 (added by the audit, #8):** how long are audit records kept? | Security and AI Governance (owner of POL-PRV-001) | nothing deleted until set (D22) |
| **From Phase 3:** can Ticketing route a ticket to Dispatch; if not, does the worker see "reported to dispatch" (POL-DWA-001 §7) or "Dispatch or Customer Service has been notified" (PRC-HOF-001 §6)? | Customer Operations; Logistics Operations / Security | routing field on the same ticket (D26); wording per D35; go-live blocker 8 |
| **From Phase 3:** when a P1 appears in a later queued message, is the chat's merged deferred handoff cancelled or left to fire? | Customer Operations | Interim design choice (revised, N6): the P1 handoff is sent at once; the merged deferred handoff is left to fire (nothing is lost) but carries D33's content-free sibling line pointing to the P1 ticket; when that P1 sets the session no-data flag (account takeover or data exposure) it also carries "P1 open on this login session — hold until the P1 case is cleared", so CS does not answer the queued case through a possibly taken-over account; a physical-danger P1 leaves the queued case as normal (F7, approved 2026-10-17) |
| **From Phase 3:** how long does Ticketing keep idempotency keys, and who watches FAILED handoffs in the CS Console after hours? | Ticketing owner, Customer Operations | Sweeper never re-sends a SENT handoff; FAILED stays visible in the CS Console; a failed P1 send raises an immediate alert (Phase 3) |

## 7. Handed to Phase 5 (Reliability & Safety) — numbers and safeguards
- N parts per message and total message length (D40); resource lookups per turn; classify time cap (D37).
- Per-node latency budget and cut order (K → 0, then template) for the 5 s p95 (D75, audit #10).
- Agentic RAG: score-gate threshold, K extra rounds (D50); top-k (D51); total chunk/field caps (D59).
- Memory: K turns (≥ 4) and TTL (D61); Redis eviction alerts.
- Queued jobs: job deadline, prefetch rules in numbers (Step 3, audit #6, N5).
- Model bake-off pass bars (D71); LLM timeout margin and minimum window (D75).
- Eval: L3 repeat count N, L1/L2 thresholds, held-out size, acceptable false-P1 rate (D77/D78, N1).
- Upload safeguards incl. the LLM checker path and the "model adapter" module decision (D19 amendment, audit #9); who records same-rule links between ACTIVE documents and their structured values, and how they are checked (audit #3, N3) — including what happens to a link whose sections have no comparable structured value (reject at upload, or escalate fail-closed; re-check F9); circuit breaker (incl. the embedding provider, audit #12), Degraded recovery, rate limits (Phase 3 list).
- Load test: 5 s p95 at 20–50 users, 8 s budget, Degraded at 1,000–2,000 users incl. queue drain rate and pgvector load (Phase 5/6); Ticketing burst capacity.
- Go-live blockers 1, 3, 5, 7, 8 (section 5b); availability question (section 6).

## 8. Handed to later phases
- Phase 6 Production / MLOps: verify OpenRouter retention, caching and provider-routing settings; production monitoring beyond ⑩ counts (D80).
- Phase 7 Implementation: the graph, MCP servers (thin), ④/⑤ shaping and shared denial-recording functions, 19 templates rendered by ⑪ (incl. Arabic number agreement), P1 pattern check and code classifier in ⑪, validators (incl. the number/unit synonym table), eval harness; mock backend item flags (D44).
- Phase 8 Testing & Evaluation: build the L1 overlay, L2/L3 cases (incl. Arabizi, the 17 design scenarios and the audit cases), Arabic variants; run D78 experiments.

## 9. Learning material produced in Phase 4
Agent_Memory_Explained.pptx · Step7_Guardrails_Explained.pptx · Step8_Model_Cost_Latency_Options.pptx (in chat) · Claude Slides deck "Step 9 Evaluation Plan" (with speaker notes) · Claude Design canvas "Agent Graph — Adaptive AI Gateway".

## Sign-off
✅ عبدالرحمن approved section 5 + F1–F5 and signed the PENDING_OWNER exception ("موافق", 2026-10-16 17:59 Cairo). Phase 4 CLOSED.
✅ Cross-phase audit round 1 errata approved ("موافق", 2026-10-16 19:32 Cairo) and applied.
✅ Round 2 errata N1–N11 approved ("موافق", 2026-10-17 00:41 Cairo) and applied.
✅ F6 / F7 approved ("موافق", 2026-10-17 10:27 Cairo) and applied. Phase 3 × Phase 4 audit closed. Next: Phase 5 Reliability & Safety.
