# Phase 4 — Step 8: Model, cost & latency ✅ CLOSED (2026-10-16; D71/D75/Degraded extended at the Phase 4 exit; audit errata applied 2026-10-16/17)

Phase 4 = what/why; numbers = Phase 5; code = Phase 7. Learning deck: Step8_Model_Cost_Latency_Options.pptx (16 slides: options, pros/cons per decision; delivered in chat 2026-10-16; describes the pre-exit version — this doc is the source of truth).
Priority order from Phase 3 still rules: security > reliability > performance > cost.
Audit errata (claude/Phase3_4_Audit.md): round 1 (2026-10-16) — #1 P1 check in every mode, #2 workers never queue, #10 latency budget, #11 owner of the code classifier, #12 embedding vendor, #21 provider fallback wording; round 2 (2026-10-17) — N1 narrow P1 patterns, N8 one full code classifier for Degraded mode and classify failure.

## D71 — Model per node
- classify = small, fast model with structured output (JSON schema); reply = stronger model, good Arabic (understands Egyptian dialect, design choice) and English. No LLM in the P1 pattern check, safety gate, plan, validate or templates.
- Model names are config via OpenRouter (D17, D27).
- Gate before a candidate is considered (design choice, from Phase 3 "verify OpenRouter retention"): provider with no data retention + structured-output support.
- Chosen by a bake-off on the Step 9 eval set. Criteria: JSON validity, intent accuracy, Arabic quality and D66 pass rate, p95 latency, cost per resolved request ("resolved" defined in Step 9: the case's expected outcome — answer OR correct handoff — was met and passed D66, so correct handoffs are never penalised). Dollar cost is only a tie-breaker. Pass bars as numbers → Phase 5.
- Model down: no second model in V1 (approved at the exit). D27 "no live retry" stands; the fallback chain is the retry (template / Degraded / handoff). Swapping the model = a config change. Revisit in Phase 9.
- Provider fallback for the SAME model (added at the exit; wording clarified by audit #21): it is OpenRouter-side routing INSIDE one adapter call, under one timeout (remaining time − margin, D27); the adapter itself never re-sends a request, so D27 "no live retry" holds. Routing is allowed only among the providers that were evaluated in the bake-off (and pass the no-retention gate), because another provider may serve a different build of the "same" model and silently change the D66 pass rate. Settings verified in Phase 6.

## D72 — Embedding model
- Hosted multilingual embedding API from a no-retention provider, behind the ⑥ adapter (D49). Fallback option: self-hosted open-source multilingual model if the owner refuses sending text out (no container is designed for it yet; it would need a D12 amendment, audit #12). Vendor stays an owner question and its approval is go-live blocker 7 (audit #12).
- The embedding provider is a 4th external system with its own ⑧ circuit (D49, audit #12). Only documents with a user Audience plus the by-name allow-list are indexed (D47), so internal-only documents are never sent to the vendor.
- Privacy (from review, confirms D49 "query text is embedded with personal identifiers removed"): the search query is scrubbed before embedding — and before the judge+rewrite LLM call (D50, audit #15) — with the same D60-A1 placeholder rules and the D27 ban on customer / worker / session ids; the embedding call is a second external data flow and gets the same rules as the LLM (POL-PRV-001).
- Model change = full re-embed from the Gateway DB (D12/D48). Picked by the same bake-off on retrieval hit rate. Rejected: English-only model relying on D53 translation.

## D73 — Fast path (System 1 / System 2)
- When the plan (code) sees that a part's answer is pure backend data, it answers with a D68 template even when the LLM is healthy, with no reply-LLM call. The reply LLM is used only for policy explanations and data + policy synthesis.
- The fast-path intent list is fixed config, signed off by the owner (design choice). Initial list: order status, return status, worker shipment list, not found, internal rule, out of scope, outside V1, handoff acknowledgement, neutral denials (templates 16–17).
- A part that also contains a "why" or policy question goes to the reply LLM, never the fast path. Classify carries a needs_explanation flag per part. Misrouting traps go into the Step 9 eval set.
- Every outgoing message, template or LLM, passes the D66 checks that apply to it (facts from ④, allowed fields, numbers placed by code, language).
- Per part in multi-intent messages (D30). In normal mode ⑪'s P1 pattern check runs first, then classify runs on every message. Clarifies D37 step 4: the single reply call covers only the System 2 parts of the turn.

## D74 — Token levers and measurement
- Caching only where allowed under no-retention (no-retention wins). Prompts are always ordered static prefix first, variable content last. Existing levers: D50 score gate and top-k, D55 minimum context, D59 token caps, D62 code summary, D66 structured segments.
- Metric: tokens per resolved request, ours vs a naive baseline (no fast path, no caching, full history) on the same eval set. Target ≥20% fewer tokens with no drop in accuracy or safety. ⑩ logs token counts per node and per intent (D27). Dollar cost is logged but used only as a tie-breaker.

## D75 — Latency within the 8 s budget (POL-BDR-001)
- Parallel only after the safety gate: backend calls and RAG for all parts run together (async). If any part is SAFE/P1, nothing else is fetched (CP-44).
- From review: identical backend calls inside one message are deduplicated (two parts about the same order = one call). All retries share the one 8 s deadline and check the ⑧ circuit first. Denial counting rules (D35/D41) are unchanged and evaluated once, after all parallel results are collected (no race).
- LLM timeout = remaining time − margin (D27). Below a minimum window (design choice, from Phase 3) the LLM is skipped: a part with a template gets its template; a System 2 part with no template gets template 18 "I couldn't finish this part right now" + offer of a human — no automatic ticket (added at the exit, F5). Typing indicator (D69).
- **Per-node latency budget (added, audit #10; numbers → Phase 5):** in normal mode the chain is serial (P1 check → classify → plan with up to K agentic rounds → reply → validate), so the 5 s p95 target needs a budget per node and a fixed cut order when time runs short: first K → 0 (no extra retrieval rounds), then template / template 18. Phase 5 sets the numbers and the load test measures p95 at 20–50 users, the Degraded queue drain rate and pgvector load at 1,000–2,000 users.

## Degraded mode, classify failure and the ⑪ code path
Phase 3 says Degraded = no LLM call, yet classify is an LLM. Decision (design choice, approved at the exit; revised by audit #1 / #2 / #11 and N1 / N8):
- In Degraded mode the classify LLM is NOT called. The role comes from the token as always (② rejects other roles, D36).
- **Owner:** the P1 pattern check and the code classifier belong to ⑪ (audit #11), so they work when ⑦ or the LLM is down. The SAME full code classifier is used in normal mode when classify fails (D58, audit #1, N8).
- Order of checks:
  1. **P1 patterns FIRST** — in EVERY mode (audit #1). Phrase patterns for the three P1 cases of POL-AGE-001 §2 only (account takeover, data exposure, physical danger) in Arabic, Egyptian, Arabizi and English — not single words, so a customer's "الطرد اتسرق" (stolen parcel) is not P1 (N1). For delivery workers the list also holds the procedure-defined P1 cases: hazardous / leaking shipment (PRC-DMG-001 §2) and suspected theft of a shipment (PRC-MSG-001 §5) — SAFE code (design choice), Dispatch routing field, templates 8 + 6 with the procedure's "meanwhile" step (Step 1 W7, F6). Hit → P1 path (template 8 + SAFE handoff) before any backend call (CP-44). The list is signed off by Security & AI Governance (go-live blocker 3); false P1s counted in ⑩.
  2. **Code classifier:** keyword rules + the order-number pattern from POL-AGV-001 §2 for the fast-path intents → status templates 1–3, filled through the ④/⑤ shaping functions (with the shared denial recording, N2).
  3. **Complaints detected by rules → CMP handoff** (Phase 3), and **out-of-V1 actions detected by rules → mandatory SCOPE/P4 handoff** (POL-AGE-001 §2), on both the Degraded path and the classify-failure path (N8).
- Anything it cannot recognise:
  - **customer, Degraded mode** → the existing 3-minute Degraded queue (Phase 3), not the classification-failure template;
  - **customer, classify failure in normal mode** → template 15 (emergency line + offer of a human); not counted as an unclassified attempt (N8);
  - **delivery worker** (either case) → never queued (Phase 3 D16: "Workers never join the 3-minute queue"; Worker Interface always 200, never 202) → handoff to Dispatch / CS with template 6 (audit #2); reason code = the "unclassified" owner question (D70).
- Inside a queued job the graph reads the stored snapshot, counts no denials and resolves ACTIVE ids at job start; a missing record sends the chat's merged deferred handoff now (Step 3, audit #6, N5).
- The "talk to a human now" button stays.
- Ticketing burst capacity when the queue hands off at 1,000–2,000 users → Phase 5 (go-live blocker).
- Option for later (needs a Website contract change, D28): quick-action buttons.

## Review log
- design-auditor on D71–D75: PASS WITH CONCERNS → all fixes applied:
  - Degraded classify;
  - no second model;
  - embedding query scrubbing;
  - D66 on templates;
  - fixed fast-path list plus the "why" rule;
  - dedupe, shared deadline and circuit check;
  - "resolved" definition;
  - dollar cost as tie-breaker;
  - design-choice labels.
- Exit-checklist errata (2026-10-16): placeholders are D60-A1 (was cited as D59); token caps are D59 (was cited as D58); D73 clarifies D37's single reply call.
- Phase 4 exit analysis + scenario tests (2026-10-16, approved): P1 keywords first in Degraded mode with Arabizi; provider fallback limited to evaluated providers; template 18 for System 2 timeouts (F5).
- Phase 3+4 cross-phase audit round 1 (2026-10-16): FAIL (errata) → applied: #1 P1 check in every mode; #2 workers never queue; #10 per-node latency budget to Phase 5; #11 ⑪ owns the code classifier; #12 embedding vendor as external system; #21 provider fallback = routing inside one adapter call.
- Round 2 (2026-10-17, his "موافق"): N1 phrase patterns for takeover / exposure / danger only, sign-off + false-P1 count; N8 one full code classifier (incl. complaint → CMP) for Degraded mode and classify failure.
