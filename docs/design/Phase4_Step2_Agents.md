# Phase 4 — Step 2: Agent Architecture & Graph ✅ CLOSED (2026-10-14, his "اقفل step 2"; audit errata applied 2026-10-16/17)

Step 1 (intents, D30–D35) is in claude/Phase4_AI_Design.md. Phase 4 = what/why; numbers = Phase 5; code = Phase 7.
Follow-ups D41 and D42 (decided after the close) refine D35/D40 without changing the graph. **D41 amends D35's "at most one counted denial per user turn"** (now only for field/query denials).
Later amendments to this step: **D37 amended by D50** (bounded retrieval rounds, Step 4) and **clarified by D73** (fast path; the single reply call covers only System 2 parts, Step 8). **Audit errata** (claude/Phase3_4_Audit.md): round 1 (2026-10-16) — P1 check before classify in every mode (#1), classify failure uses the code classifier (#1), query-denial evidence (#13), unverified order IDs in tickets (#22); round 2 (2026-10-17) — narrow P1 patterns (N1), full code classifier on classify failure (N8), step 0 runs in ⑪ (N9), worker id only as evidence (N10).

## The graph (per request)
```
⑪: P1 pattern check (code, every mode) → agent ⑦: classify (LLM) → safety gate (code) → run the intent's plan (code) → write reply (LLM) → validate reply (code) → user
        │                                          │                         │                                   │
        └→ P1 path (⑪ → ⑨)                         ├→ P1 path (⑪ → ⑨)        ├→ clarify (one question)           └→ template or handoff
                                                   ├→ escalation flags (D42) └→ handoff (⑪ → ⑨)
                                                   └→ classify failed → ⑪ code classifier (as in Degraded mode)
```
Edges out of the main line:
- **P1 pattern hit (code in ⑪, before the agent, every mode; audit #1, N1, N9)** → P1 path at once, whatever classify would say. The list is made of PATTERNS for the three P1 cases of POL-AGE-001 §2 — account takeover, data exposure, physical danger — in Arabic, Egyptian, Arabizi and English (e.g. "someone got into my account", "7ad da5al 3ala el account", "you showed me someone else's data", "he is threatening me"), not single words such as "stolen" alone. For delivery workers the list also holds the P1 cases their procedures define — hazardous / leaking shipment (PRC-DMG-001 §2) and suspected theft of a shipment (PRC-MSG-001 §5) — so they stay P1 in Degraded mode (Step 1 W7: reason code SAFE as a design choice, Dispatch routing field, templates 8 + 6; F6). A customer's stolen parcel ("الطرد اتسرق") is not P1 (C12 delivered-not-received). Signed off by Security & AI Governance (go-live blocker 3); false P1s counted in ⑩.
- **Classification fails / times out** → no backend calls on the LLM path; the message goes through the FULL code classifier of ⑪ (the same one Degraded mode uses, audit N8): fast-path intents → status templates; rule-detected complaint → CMP handoff; rule-detected out-of-V1 action (e.g. "cancel my order") → mandatory SCOPE/P4 handoff (POL-AGE-001 §2); anything else → for customers template 15, which always carries the emergency line and offers a human; for delivery workers a handoff to Dispatch / CS with template 6 (workers get the same treatment as in Degraded mode, Step 8). A system classify failure is NOT an unclassified attempt of the user (like lost context, D65; audit N8) — an **interpretation** of POL-AGE-001 §2 "intent not classified after 2 attempts" (design choice: a system error is not the user's attempt).
- **SAFE/P1 in any part** (from classify) → P1 path before any backend call (CP-44).
- **Escalation flags in any part** (D42) → handoff in the same turn.
- **Missing or ambiguous identifier** → ONE clarifying question for the whole turn, about the first part that needs it (POL-AGE-001 §4; D32 rounds count per user turn).
- **Plan result says handoff** (SCOPE action, Processing cancellation, complaint, D21 review, conflicting ACTIVE documents, exception request, etc.) → ⑦ returns "needs handoff + reason"; ⑪ calls ⑨ (D19).
- **Validation fails** → safe template or handoff (D66 two failure classes).
- **⑪'s 8 s deadline** → fallback (D27; template 18 for a System 2 part with no template, D75).

## D36 — Roles
- Two agents inside ⑦: **Customer agent** (C1–C14, customer tools only) and **Worker agent** (W1–W9, worker tools only).
- CODE selects the agent from the role in the verified token (②, D1). No LLM router. Least privilege at agent level.
- Any other role (cs / approver / ops / unknown) → no agent selected, request rejected. Degraded mode needs no agent.
- D9 learning goal: the two agents never hand off; his choice to keep it simple; can be revisited.

## D37 — Working pattern ("intent → plan")
0. **P1 pattern check (code, runs in ⑪ BEFORE the agent is called; audit #1, N9):** on the raw message, in every mode. A hit → P1 path; classify is not needed for P1. Patterns only for takeover / data exposure / physical danger (N1).
1. **Classify (LLM, structured output only):** a safety flag AND escalation flags (D42) for EVERY part; intents + extracted arguments for the first N parts (D40). Own time cap (Phase 5). Splits multi-intent messages (D30).
2. **Safety gate (code):** classification fails/times out → no backend calls on the LLM path; ⑪'s full code classifier takes over (audit #1, N8). Any SAFE/P1 part → P1 path before any backend call; a P1 data-exposure report stops all further data (POL-PRV-001 §5).
3. **Run the plan (code):** the fixed tool plan for each intent in the Step 1 table. Resource lookups per turn are capped (same N, Phase 5). **Amended by D50:** no free tool loop, EXCEPT bounded retrieval rounds that use only the filtered search tool.
4. **Write the reply (LLM):** one reply call for all parts. A tool-call request here = typed error. **Clarified by D73:** the single reply call covers only the System 2 parts; fast-path parts get templates with no reply-LLM call.
5. **Validate the reply (code):** facts only from validated backend data, rules only from ACTIVE policy IDs, no unauthorized fields, no promised outcomes (POL-AIS-001 §4, POL-AGV-001 §5). Fail → safe template or handoff. Detail → Step 7.
- An "attempt" (unclassified intent, 2 → P4) = one user turn where classify returned valid output with no intent. A confident C13/W9 is NOT an unclassified attempt. A bare reference with lost context (D65) and a system classify failure (N8) are not attempts either.

## D38 — State (per request, held by code)
- IN: identity, role, login_session_id from ② (code-only, NEVER sent to the LLM — D2); the message; intents + extracted arguments; tool results after ④/⑤ filtering; ⑤ results; IDs + versions of policies used; request_id, remaining time, step counter.
- OUT: the token or any credential (D20, D24); the denial count (read from ⑩, D15); raw backend data or forbidden fields; passwords, OTPs, card numbers.
- One request only (D11); not persisted by a framework checkpointer (if ever, D22 applies). Cross-turn fields live in ③'s Redis state with TTL.

## D39 — No routing between agents
- Each agent's classifier knows only its own intents; never transferred to the other agent.
- A customer's "where is my delivery today?" = C1 (his own orders). C13 only when no customer intent fits (e.g. "show me my assigned route"); ambiguous → one clarifying question (POL-AIS-001 §2.8). Worker side: W9.
- C13/W9 never absorb mandatory escalations: an out-of-V1 ACTION is C8 → SCOPE/P4.
- Step 9: eval cases for both.

## D40 — Many questions in one message
- Answer only the first N parts (N → Phase 5); the reply names the unanswered parts. Reasons: 8 s budget, Reliability, tokens.
- SAFE/P1 and the D42 escalation flags are checked across ALL parts. Total message length / number of parts bounded (Phase 5).
- A handoff in that turn: its neutral summary covers all parts (PRC-HOF-001 §3).

## D41 — Denial counting (his approval of my recommendation)
- **Resource denials** — any attempt to reach an order or shipment that is not the user's, by ID (backend 404) OR by query (e.g. "list worker 4413's shipments", POL-DWA-001 §5 "Shipments of other workers") — are counted EACH (D30; POL-AGE-001 §2 "denied requests"; POL-DWA-001 §7). Three colleagues' shipments in one message = 3 → P2 + §7 notice in the same turn.
- **Evidence rule for query denials (audit #13, narrowed by N10):** a query denial is counted only when CODE finds another worker's ID word-for-word in the message (the worker-id format comes from the mock backend contract; no policy defines it — design choice). A name alone ("Ali's shipments") is never evidence — it could be one of his own customers — so the reply is the same neutral denial and nothing is counted. The LLM's enum label alone never counts.
- **Where it is recorded (audit N2):** every denial — on the agent path and on ⑪'s template path (Degraded status templates, classify-failure path) — is recorded by the SAME shared ④/⑤ library function, so both paths count identically (Step 3).
- **Field/query denials about his own shipment** (D35 row 2: email, payment except COD, customer history, internal notes, other orders of the customer) are counted at most ONCE per user turn (design reasoning: one sentence = one intent). Counting field denials is an interpretation that amends Phase 3 D15's denial list (audit #13, see D35).
- Parts beyond N are never executed, so they produce no lookups and no denials.
- Known false-positive risk (already accepted in D32): a customer who mistypes 3 order IDs reaches P2, but a human handles it with no accusation.

## D42 — Escalation triggers beyond N (his choice after a hint)
- The classifier flags for EVERY part: an explicit request for a human (C6), an out-of-V1 action (C8 → mandatory SCOPE/P4, POL-AGE-001 §2), a complaint (C10 → CMP). These are honoured in the SAME turn even beyond N. Design reasoning (ASSUMPTION, not policy text): they need no backend lookups, and deferring an explicit human request ignores it (POL-AGE-001 §3 lists it as a valid escalation). Small cost remains (classifier flags + ticket write).
- Ticket rules follow D33; the summary covers all parts (D40).
- An order ID the user typed in a part that was never looked up (amended, audit #22): it goes into the ticket only if it is in the user's own ③ list (then labelled "user-stated, not verified"); otherwise the ticket says only "an order number was mentioned", without the value — an unverified ID may belong to another customer (PRC-HOF-001 §3 "if identified", §4 no unrelated customer data, no unvalidated guesses as facts).
- Owner questions: reason code for C6 "talk to a human" (PRC-HOF-001 §2 has none — already open, Customer Operations); code for a delivery worker's complaint (CMP is defined for customers).

## Parked
- His target "the system should save about 20% tokens" → Step 8 (D74); needs a baseline; measured in Step 9; never at the expense of Security or Reliability.

## Review log
- design-auditor on D36–D38: PASS WITH CONCERNS; fixes applied.
- design-auditor close review (D39–D40 + Step 2): PASS WITH CONCERNS, ready to close after wording fixes — applied.
- design-auditor on D41–D42: PASS WITH CONCERNS, no ❌; fixes applied (query-based attempts on others' shipments = resource denials; resource lookups per turn capped; user-stated unverified order refs; rationale labelled as design reasoning; owner questions on C6 and worker complaint codes).
- Phase 3+4 cross-phase audit round 1 (2026-10-16): FAIL (errata) → applied: #1 P1 check in every mode + code classifier on classify failure; #13 query-denial evidence; #22 unverified IDs; D37 amendment notes.
- Round 2 re-verification (2026-10-17, his "موافق"): N1 P1 patterns for takeover / exposure / danger only; N2 one shared denial recorder; N8 full code classifier, classify failure not a user attempt; N9 step 0 runs in ⑪; N10 worker id only.
