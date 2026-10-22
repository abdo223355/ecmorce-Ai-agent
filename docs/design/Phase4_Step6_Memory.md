# Phase 4 — Step 6: Memory ✅ CLOSED (2026-10-15; D65 extended at the Phase 4 exit; audit errata applied 2026-10-16)

Phase 4 = what/why; numbers = Phase 5; code = Phase 7. Learning deck: Agent_Memory_Explained.pptx (15 slides, delivered in chat 2026-10-15).
Audit errata 2026-10-16 (claude/Phase3_4_Audit.md, his "موافق"): #14 "why?" follow-ups re-fetch the cited section, #15 clue field limited.

## Three memory types (vocabulary)
- **State** (working memory): one request, held by code (D38).
- **Short-term memory**: this chat, Redis (③) with TTL (D61).
- **Long-term memory**: across sessions — not in V1 (D63).

## D61 — Short-term memory = structured per-turn cards in ③ Redis
- Card fields: intents; entity references (resolved order / return / shipment ids for THIS owner only); shown-list mapping; pending clarification; question template id + resolved answer or a bounded clue field; outcome / reason code of the turn; policy IDs + versions consulted; backend error type / retries / time; handoff state. No raw message text.
- **Clue field (narrowed, audit #15):** product clues (product name / type as the user wrote it) and date clues only. Never names, phone numbers, addresses, payment data, passwords or OTPs (D64, POL-PRV-001 §3). Was: "no payment data, passwords or OTPs" — it allowed names and addresses, which D64 forbids.
- Keeps enough to build a PRC-HOF-001 §3 handoff (clarifying Q&A, policy IDs/versions, backend errors, neutral summary) and to escalate "with the collected clues" (POL-AGE-001 §4), so CS never asks the customer to repeat (§5).
- Window: last K turns (K → Phase 5) with K ≥ 4 (request + 3 clarification rounds), and the cards of an open issue are kept until it closes.
- TTL resets on each turn and never outlasts the login session (D22); value → Phase 5.

## D62 — Code-built summary
- The LLM gets a short summary built by CODE from the cards (no LLM-written summaries: no fabricated memory, fewer tokens), including the last turn's outcome / reason code, policy ID + version and the entity in focus (as a placeholder), so follow-ups like "why?" are answered from facts, not re-derived (POL-AIS-001 §2.1–2.2).
- **"Why?" follow-ups (added, audit #14):** D66 check 2 accepts only sections retrieved in THIS turn. So the plan (code) re-fetches the card's (doc_id, section) through ⑥ under the current ACTIVE + Audience filter and adds it to this turn's retrieved set. If the ACTIVE version changed since the card was written, the answer is re-derived on the current version (⑤ recomputes; POL-VER-001 §3 rule 1); the old version is never cited.
- Amends D28's "later queued messages get the earlier reply as context": the context is the earlier turn's card / placeholder version, never the delivered reply with real values (D60-A1).

## D63 — No long-term memory in V1
- Memory ends with the login session / chat + TTL (D22, POL-PRV-001 §1.1/§1.4). Customer history always comes fresh from the backend. Cost: no "last time you asked…". V2 option: non-personal preferences such as language.

## D64 — What memory never holds
- Never: identity, token, denial counts (⑩ in the DB, D15), raw backend data, names, contact details, addresses, payment data (D38, D60-A1). The P1 stop-data flag stays in the DB (CP-44).
- Allowed: resolved order / return / shipment ids of this owner only. They are hints: every tool call re-authorizes against the identity from the token (D1, POL-PRV-001 §1.2), and the owner is re-checked on every memory read.

## D65 — Chat boundaries
- One chat = owner + login_session_id (D28); two tabs of one login = one chat; a new login = new memory.
- Missing memory (Redis loss, TTL expiry) = fresh start: a pending clarification is never resumed; the D32/D37 counters restart (low risk: D15 and CP-44 live in the DB); the handoff record in the Gateway DB is the source of truth, so a handoff is never duplicated (D14, D33).
- Lost context (added at the Phase 4 exit, finding F4, his approval): a bare reference ("2", "التاني", "the other one") that arrives when ③ has no mapping is NOT an unclassified attempt (D37). Code re-shows the user's own list / asks again, and the attempt is not counted toward the 2-attempt P4 rule.

## Redis hygiene (from review)
- Eviction policy: volatile-* (only keys with a TTL can be evicted); mode / circuit keys have no TTL (or live in a separate store) so memory pressure never triggers a false Degraded mode (D17); alert on evictions. Numbers → Phase 5/6.

## Review log
- design-auditor on D61–D65: PASS WITH CONCERNS; not ready until handoff completeness, id-mapping wording and the D28 reply-context conflict were fixed → all applied, plus outcome codes for follow-ups, eviction policy and fresh-start rule.
- Phase 4 scenario tests (S11, 2026-10-16): lost-context rule added (F4).
- Phase 3+4 cross-phase audit (2026-10-16): FAIL (errata) → applied here: #14 re-fetch of the cited section for "why?"; #15 clue field narrowed to product and date clues.
