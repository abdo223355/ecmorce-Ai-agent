# Phase 5 — Reliability & Safety (Adaptive AI Gateway, NovaCart)

Status: **CLOSED 2026-10-19 (his "موافق", 12:17).** Steps 1–8 approved (D81–D129) with independent reviews per step and a final cross-step review; all fixes applied. Next: Phase 6 Production / MLOps. Phase 5 decides the NUMBERS and the SAFEGUARDS (how the design behaves when things fail or are attacked); code is Phase 7, production setup is Phase 6, running the tests is Phase 8. Phases 3 and 4 (D1–D80, incl. the cross-phase audit errata) are constraints here.

## Starting material (handed over)
- Phase 4 Exit checklist §7 (numbers and safeguards) and §5b (go-live blockers 1, 3, 5, 7, 8).
- Phase 3 deferred items marked "Reliability and Safety" (claude/Phase3_System_Context.md, deferred table).
- Audit items moved here: #9 "model adapter" module (D19 amendment, upload LLM checker path), #10 per-node latency budget, #3 / N3 / F9 conflict-link mechanics, #12 embedding-provider circuit.

## Roadmap
1. **Risk register** ✅ — failure modes + threats, each with effect, detection, current mitigation, gap and owning step.
2. **Resilience mechanics** — timeouts, retries / backoff, circuit breakers (backend, LLM, Ticketing, embedding), Degraded-mode switch ON (429, latency, D66-failure spike) and recovery OFF, rate limiting (incl. before token checks), JWKS refresh rules, Redis memory / eviction, outbox priority (P1 first), Worker / Sweeper health signals, Cairo time source, P1-flag read when the DB is down.
3. **Latency and capacity budget** — per-node budget for the 5 s p95 and the 8 s limit, cut order, N parts, K rounds, top-k, caps, memory K turns and TTL, queue limits and job deadline, Sweeper interval, Worker send rate at the burst, Ticketing burst, DB connection pools and pgvector load, end-to-end load test of the R4 chain, the availability question.
4. **AI safety safeguards** — prompt injection defense in depth, P1 detection (false P1 and missed P1, blocker 3), policy-upload safeguards (maker-checker, structured-value checks, conflict-link recording, LLM checker path, "model adapter" module), insider controls, embedding vendor (blocker 7).
5. **Data safety** — retention numbers, audit retention, backups (RPO / RTO / frequency), secrets, idempotency-key lifetime.
6. **Eval thresholds** — L3 repeat count N, L1 / L2 thresholds, held-out size, acceptable false-P1 rate AND missed-P1 pass bar, D66-failure alarm level, model bake-off pass bars.
7. **Go-live readiness** — plan for blockers 1, 2, 3, 5, 7, 8 (contract tests, sign-offs, load test, release gate for config changes).
8. **Exit checklist.**

Estimated decisions per step (estimate shared with him 2026-10-17; may change; numbering continues from D81): Step 1 = 2 · Step 2 ≈ 8 · Step 3 ≈ 8 · Step 4 ≈ 7 · Step 5 ≈ 5 · Step 6 ≈ 5 · Step 7 ≈ 3 · Step 8 = 0 (checks only). Total ≈ 38.

## Step 1 — Risk register ✅ CLOSED (2026-10-17)
Method (taught): for each item — failure mode / threat → effect on the user and on NovaCart → how we detect it → what D1–D80 already do → gap → owning step (Security > Reliability > Performance > Cost).
His first answer (graded PARTIALLY CORRECT): picked Redis full, prompt injection, Ticketing down; missed the certain one at peak (LLM 429) and backend slowness, and the chain they form into Ticketing.

### D81 — The risk register is the backbone of Phase 5
- One row per risk; each row names the Phase 5 step — or the later phase — that closes its gap; the register is updated at the end of every step. Why: every number or safeguard we add must close a known risk, and a risk with no owner becomes visible at once.

### D82 — Scoring, priority and acceptance (design choice; revised by the review, F8)
- **Scale (one fixed scale):**
  - Likelihood — High: expected on a normal sale day or every week · Medium: plausible a few times a year · Low: needs unusual conditions.
  - Impact — High: a security or privacy breach, a wrong final answer to many users, or a broken promise to a customer · Medium: degraded service, extra handoffs or delay · Low: a small loss of quality.
  - Score = L × I with H = 3, M = 2, L = 1.
- **Priority:** Tier A = score ≥ 6; inside Tier A, Security risks come first (Phase 3: when two attributes conflict the higher one wins), then by score; then Tier B (3–4), then Tier C (≤ 2).
- **Acceptance rule:** a Security risk with High impact may NEVER be accepted. Only Reliability / Performance / Cost risks with a score ≤ 4 may be ACCEPTED with monitoring, and each accepted risk names its detection signal and a trigger for re-review.
- **Priority order (recomputed with this rule):** T3 → T4 → T1 → T5b → R4 → R3b → R2 → R3 → R9 → R10 → R11 → R12 → R1 → then Tier B. Accepted: R7 (now); R5 (only after the Phase 6 load test — Step 2+3 fix 4).

### Register v2 (2026-10-17; L × I are ASSUMPTIONS until measured in the Phase 5/6 load test and the Phase 8 evals)
**Failures (reliability)**
| # | What fails | L × I | User sees | Detected by (signal; tools in Phase 6) | Covered by | Gap → owner |
|---|---|---|---|---|---|---|
| R1 | LLM 429 / overload on sale day | H × M | template at once, or "waiting" + human button, handoff after 3 min | 429 rate, ⑧ LLM circuit state, Degraded switch events in ⑩ | D16, D20, Degraded mode (Phase 4 Step 8) | Degraded ON / OFF thresholds → Step 2; queue drain → Step 3 |
| R2 | Backend slow or down | M × H | "status unavailable now" + BKD/P3 handoff | backend timeout / 5xx rate, ⑧ circuit | POL-BDR-001, 2 retries, D75 | timeouts, circuit thresholds → Step 2 |
| R3 | Ticketing down | M × H | "registered" + CS phone and hours | Ticketing 5xx / timeouts, PENDING count and age | D14 outbox, D26 idempotency | backoff, retry counts → Step 2; burst capacity (blocker 5) → Steps 3 / 7 |
| R3b | Ticketing accepts the call but rejects or misroutes the ticket (PENDING_OWNER, missing priority, no Dispatch route); a P1 waits behind a burst | H × H at peak, until blockers 1, 2, 8 clear | told "registered", but the ticket ends FAILED or reaches the wrong queue | FAILED count, Ticketing 4xx, age of the oldest P1 send | D70 interim rules, CS Console FAILED view | P1 sent first from the outbox, FAILED alert → Step 2; contract tests (blockers 1, 2, 8) → Step 7 |
| R4 | Chain: R1 + R2 + R10 feed R3 / R3b at the same time | H × H | many handoffs, longer CS reply time | queue depth + handoff rate + PENDING age watched together | no coverage of the chain as a whole | end-to-end load test of the chain → Steps 3 / 7 |
| R5 | Redis full or lost | L × M | chat starts fresh, or unnecessary Degraded mode; Redis-based rate limits stop working (ASSUMPTION) | Redis evictions, missing mode / circuit key (D17 alert) | D17 rule "Redis lost → Degraded mode"; eviction policy volatile-* (Phase 4 Step 6, Redis hygiene) | memory size, eviction alerts → Step 2; ACCEPT after Step 2 (re-review if evictions appear in the load test) |
| R6 | Gateway DB down | L × H | only static text works: "we could not register" + CS phone (Phase 3) | DB errors, static-fallback count | static fallback (Phase 3) | RPO / RTO, backups → Step 5; P1-flag read fails closed → Step 2 |
| R7 | Embedding provider down | M × L | weaker retrieval (keyword-only, more POL/P3 handoffs); a new policy version cannot reach DONE, so it activates late | embedding circuit, keyword-only share, age of indexing PENDING | D49 | circuit thresholds → Step 2; ACCEPTED (re-review if keyword-only share stays high) |
| R8 | Serial graph too slow, p95 > 5 s | M × M | slow reply | p95 per node (⑩ timings) | D73 fast path | per-node budget and cut order → Step 3 |
| R9 | Background Worker / Sweeper down (single process) | M × H | told "registered", but handoffs stay PENDING, 3-min timeouts never fire, approved versions do not activate on time | measured OUTSIDE the Worker: age of the oldest PENDING handoff (P1 tracked separately), overdue deferred handoffs, overdue activations | D14 outbox (nothing is lost, only delayed) | health signals → Step 2; send rate at the burst (standby only if too slow) → Step 3; auto-restart → Phase 6 |
| R10 | LLM output degrades at scale (e.g. a new provider build: fast replies that fail D66) | M × H | many whole-reply handoffs; Degraded mode does not switch on today | D66 failure rate, typed-error rate | D66 two failure classes, D71 evaluated providers | a D66-failure spike opens the LLM circuit → Degraded mode (amends the Phase 3 trigger "429 or high latency") → Step 2; alarm level → Step 6 |
| R11 | Change, keys and time: bad deploy or config change (P1 list, templates, unit synonyms, model name); backend rotates its signing key while down; wrong clock / timezone (Cairo dates) | M × H | wrong answers, all new tokens rejected, wrong eligibility or activation date | config / release version in ⑩, JWKS fetch failures, spike in rejected tokens, date-boundary eval cases | D24 key cache, D80 regression on every config change | key-cache rules and one Cairo time source → Step 2; release gate for config changes → Step 7; rollback → Phase 6; date-boundary cases → Phase 8 |
| R12 | Gateway DB saturated at peak (connection pools of N instances + Worker + retrieval; ACTIVE ids read every request; sync audit; queue; pgvector) | M × H | slow replies, then fallbacks | pool wait time, statement timeouts | separate retrieval pool (D48) | pool sizes and load test → Step 3 |

**Threats (security)**
| # | Threat | L × I | Detected by | Covered by | Gap → owner |
|---|---|---|---|---|---|
| T1 | Prompt injection (message, or an edited policy — indirect injection) | M × H | D66 check 9 hits, injection-sign counts | D2, D56, D66, code decides | defense in depth + injection at upload → Step 4 |
| T2 | Enumeration of orders / shipments | M × M | denials per session, AUTH/P2 count | D4 404, D15, D41, N2 shared recorder | rate limiting → Step 2 |
| T3 | **P1 missed** — takeover, data exposure, physical danger, and the worker P1 cases (hazard, theft); in Degraded mode the patterns are the only check | M × H | missed-P1 eval cases (L3), CS reports | P1 patterns (N1), classify safety flag, template 15 emergency line | pattern list + sign-off (blocker 3) → Step 4; missed-P1 pass bar next to the false-P1 rate → Step 6 |
| T4 | Wrong policy goes live (bad structured value, conflicting documents) | M × H | activation audit, post-activation eval regression, CS complaints | D13, five activation conditions; conflict links PARTIAL (mechanics open, D47 known gap) | maker-checker, value checks, link recording (F9), LLM checker path, "model adapter" module → Step 4 |
| T5a | Spam with valid tokens to burn tokens / cost | M × M | tokens per user / session in ⑩ | D29 (token required), D59 caps | per-user limits → Step 2 |
| T5b | Availability DoS with junk tokens: each forces a token check, maybe a JWKS refresh (unknown key id) and an audit write; latency can force Degraded mode | M × H | invalid-token rate, JWKS refresh rate | D24 (keys refreshed only on an unknown key id) | limits before token checks, minimum interval between key refreshes, coalesced audit rows for invalid tokens (denial rows stay sync) → Step 2; edge limits → Phase 6 |
| T6 | Data leaks to a vendor (LLM, embedding) | L × H | vendor-settings checks | D17 no-retention, placeholders, scrub | vendor approval (blocker 7) → Step 4; settings → Phase 6 |
| T7 | Insider or compromised staff account (uploader also approving, ops forcing Degraded mode, "handled manually" used to drop FAILED cases) | L × H | sync audit of every CS Console action (D15), ops-switch alerts | D15 audit, RBAC roles (cs / approver / ops) | uploader ≠ approver, alert on the ops switch and on bulk "handled manually" → Steps 4 / 2 |

**Phase 4 Exit §7 / Phase 3 deferred items not tied to a single row:** memory K turns and TTL → Step 3; queued-job deadline → Step 3; Sweeper interval → Step 3; retry counts and queue priorities → Step 2; Redis memory → Step 2; safeguards on structured values at upload → Step 4.

### Review (2026-10-17, independent design-auditor, read-only on local copies): PASS WITH CONCERNS, 12 findings — all applied after his "ok" (12:19)
- F1 R9 Worker / Sweeper; F2 T3 widened to "P1 missed"; F3 T5 split (T5b junk tokens, audit flood); F4 R3b Ticketing rejects / P1 first; F5 "Detected by" column; F6 R10 LLM output degrades; F7 T4 PARTIAL + T7 insider; F8 fixed scale, priority and acceptance rule; F9 R5 citation (eviction policy is in Phase 4 Step 6; numbers open) and acceptance after Step 2; F10 R12 DB saturation + P1-flag fail-closed; F11 R11 change / keys / time; F12 mapping gaps and D81 wording.
- His answers to the reviewer's questions (my recommendations, approved): one Worker + outside detection now, auto-restart in Phase 6, standby only if Step 3 shows the send rate is too slow · no High-impact Security risk may be accepted · a D66-failure spike opens the LLM circuit (Phase 3 trigger amended; numbers in Step 2).

## Step 2 — Resilience mechanics ✅ APPROVED (2026-10-17 12:36, his "ok"; learning deck Step2_Resilience_Mechanics.pptx/.pdf; independent review batched with Step 3 to save tokens)
- **D83 Retries:** backend up to 2 retries, backoff 1 s then 2 s, transient only (timeout, 503, network), inside the 8 s budget (POL-BDR-001 §2–3); no retry on 400/401/403/404/422; one re-request on a malformed response; stop when the remaining time cannot fit another attempt. LLM: no live retry (D27). Ticketing: Sweeper retries with growing backoff + jitter, honours Retry-After, 4xx → FAILED. Embedding: no retry on the request path → keyword-only; indexing retried by the Sweeper.
- **D84 Circuit breakers:** one per external system (backend, LLM, Ticketing, embedding); closed → open → half-open with one probe; state shared in Redis (D11), missing key → Degraded (D17). Initial values (design choice, tuned in the load test): open at ≥ 50% failures of the last 20 calls or 5 consecutive failures; cool-down 30 s.
- **D85 Degraded ON/OFF:** ON when the LLM circuit opens (429 burst, 5xx/timeouts, or a D66-failure spike — amends the Phase 3 trigger), when p95 stays above a threshold for a period, or by the ops switch (audited + alert, T7). OFF with hysteresis: circuit closed + latency below a lower threshold for a stable period; drain the queue first.
- **D86 Rate limiting:** three layers — before the token check (per IP / connection, T5b; edge copy in Phase 6), per login session (T5a, T2), per chat queued messages (existing). Over the limit → 429 + Retry-After, not a denial. Counters in Redis; Redis lost → local per-instance limits (fail safe). Numbers → Step 3.
- **D87 Outbox priority + Worker health:** P1 / SAFE lane sent first; instances watch the Worker from outside (oldest PENDING age with P1 separate, overdue deferred handoffs, overdue activations); P1 FAILED or late → immediate alert, others batched.
- **D88 Tokens and keys:** JWKS refresh only on an unknown kid, minimum interval + single-flight, keep the last keys if the fetch fails; invalid-token audit rows coalesced as counts, denial rows stay sync (D15) — closes the parked audit-flood item.
- **D89 Time:** one Africa/Cairo time source for all date logic in ⑤ (activation, "today", return windows); small JWT exp leeway (initial value); NTP in Phase 6.
- **D90 Redis / DB failure:** Redis maxmemory + volatile eviction + eviction alerts, mode/circuit keys without TTL; Redis lost → Degraded + local limits; DB down → static fallback; P1 no-data flag read fails CLOSED. R5 accepted only after the Phase 6 load test (Step 2+3 fix 4).
- Risks closed or reduced: R1, R2, R3, R3b, R5, R6, R7, R9, R10, R11 (keys, time), T2, T5a, T5b, T7 (ops switch).

## Step 3 — Latency & capacity budget ✅ APPROVED (2026-10-18; he confirmed D91–D98 in his own written summary after studying Step3_Latency_Capacity.md)
All numbers marked (initial) are design choices / ASSUMPTIONS, tuned in the Phase 6 load test and Phase 8 evals.
- **D91 Latency budget + cut order:** 8 s hard limit, normal target ≈ 4.8 s. Budgets (initial): P1 + safety gate + plan 0.1 s · classify ≤ 1.0 s · backend + RAG in parallel ≤ 1.5 s (parallel ≈ the slower one, not the sum) · reply LLM ≤ 2.0 s · validate + render ≤ 0.2 s. Optional work is budget-aware and cancellable. Cut order: agentic extra rounds (K → 0) → judge+rewrite → template / template 18 for a System 2 part → retries stop when a full attempt cannot fit (D83). Never cut: P1 check, safety gate, validate.
- **D92 Dynamic LLM timeout:** timeout = remaining time − margin (0.5 s, initial); no call below the minimum window (reply 1.5 s, classify 0.8 s, initial) → template or handoff.
- **D93 Limits (initial):** ≤ 3 parts answered per message (D40) · message ≤ 1,000 characters · UP TO 3 backend calls per turn · 3 clarification rounds (POL-AGE-001) · 60 requests/min per IP before the token check · 20 messages/min per login session · ≤ 3 queued messages per chat.
- **D94 RAG (initial):** top-k 5 · K ≤ 1 extra agentic round (K ≥ 2 only if evaluation proves it pays) · ≤ 8 chunks per request in total across all rounds · score gate set from the eval set, not guessed. No duplicate-removal strategy is specified (not invented).
- **D95 Memory (initial):** ≤ 6 turns · TTL 30 min since the last message · never beyond the login session.
- **D96 Queue (initial):** 3-min queue (Phase 3) · total queue size from the load test · queued-job lifetime = min(20 s, deferred-handoff due time) · Sweeper every 15 s, P1 lane checked first on every pass (implementation not specified) · Worker send rate measured; standby only if below the peak handoff rate.
- **D97 DB / Ticketing capacity:** pool per instance + separate retrieval and Worker pools, total below the PostgreSQL limit with a margin; full pool → wait ≈ 0.5 s (initial) then fallback; never unlimited connections; ACTIVE ids read per request (no cache assumed). Ticketing burst: compute the peak handoff rate and agree capacity (blocker 5); if Ticketing cannot keep up, the outbox queues tickets and the customer is not promised an exact reply time.
- **D98 Load-test plan (run in Phase 6):** normal 20–50 users → p95 ≤ 5 s, nothing > 8 s · peak 1,000–2,000 users + LLM 429 → Degraded works, templates and handoffs work, no message lost · failure chain (slow backend + 429 + slow Ticketing) → oldest-ticket age watched, P1 always first · junk-token flood → limit before the token check, JWKS refresh bounded, no forced Degraded · Redis lost → no fail open · Worker down → outside alert before a P1 is late. (His uploaded summary was cut off after the failure-chain item; the remaining items are as proposed in Step3_Latency_Capacity.md.)
- **Owner question (availability 99%):** does Degraded time count as "up"? Interim: counted as up while templates and handoffs work; Degraded time recorded separately for the owner.
- Risks closed or reduced: R1 (queue drain), R4 (chain load test), R8 (p95), R9 (Worker send rate), R12 (DB pools), R3 / blocker 5 (Ticketing burst), T5a / T5b (rate-limit numbers).

## Review of Steps 2 + 3 (design-auditor, read-only, 2026-10-18): PASS WITH CONCERNS → fixes APPROVED (his "موافق", 11:39); these lines amend D83–D98 above
1. **D83 retries are best-effort inside 8 s** (interpretation of POL-BDR-001 "up to 2 retries … within the overall request budget of 8 seconds"; not a guarantee of both). Backend per-attempt timeout = 1.0 s (initial). An attempt starts only if attempt timeout + its backoff + a reserve of 2.2 s (reply minimum 1.5 + margin 0.5 + validate 0.2) still fit. A late retry that succeeds with less than the reply window left → status templates 1–3.
2. **D92 per-node cap:** timeout = min(node cap, remaining − margin − minimum windows of the required later steps). Classify cap 1.0 s; at the cap → ⑪ code classifier (N8).
3. **D86 / D93 polling:** Degraded-mode polls use their own bucket, checked after the token; the server sets the poll interval (3 s, initial). The 60/min per-IP pre-token limit applies to /chat only. D98 gains a "polling behind a shared IP (carrier NAT, depot Wi-Fi)" case.
4. **Step 2 numbers (initial values):** Degraded ON when p95 > 6 s for 60 s (or the LLM circuit opens, or the ops switch); OFF when p95 < 4 s for 5 min with the circuit closed · P1 send late → alert at 60 s · Ticketing backoff 5 s growing to 5 min · JWKS minimum refresh interval 60 s · JWT leeway 30 s · Redis maxmemory sized in the load test; R5 accepted only after it.
5. **D85 D66 trigger:** D66 failures are measured as a rate over a time window, separate from transport failures (429 / 5xx / timeouts); the alarm level → Step 6. R10 = trigger defined, level open.
6. **D91 optional work:** the agentic extra round and judge+rewrite run only if the turn still fits under 5 s; otherwise they are the first cut.
7. **D96 wording:** "job run deadline, counted from job start" = min(20 s, deferred-handoff due time); if the time left at job start is below the reply window, the deferred handoff is sent instead.
8. **Register v3:** rows closed by Steps 2–3 are "designed — verify in the Phase 6 load test" (R4, R8, R12, T5 numbers); R5 "accept after load test"; R10 "level → Step 6"; R2 / R3 / R9 / R11 numbers now set (above).

## Step 4 — AI safety safeguards ✅ APPROVED (2026-10-18 12:39; he confirmed D99–D105 in his own written summary after studying Step4_AI_Safety_and_Step3_Fixes.md)
Opening scenario: a CS employee uploads a Return Policy version with "30 days" instead of "15 days" for electronics.
- **D99 Policy upload protection (T4):** before approval, code checks: (1) range check of each structured value, ranges set by the Policy Office (owner question; none invented); out of range → stays DRAFT; (2) each structured value (number + unit) must appear in the PDF section text (N4 rule), otherwise stays DRAFT; (3) the approver sees old value → new value and confirms each changed number one by one; (4) maker ≠ checker, enforced by code; (5) before the effective date, the policy-specific L2 eval cases run on the new version and changed results are shown to the approver; (6) emergency hold (design choice): the Policy Office can mark a version "under review" → related questions get a POL/P3 handoff until a corrected version is approved; no automatic rollback to an older version (POL-VER-001).
- **D100 Upload LLM checker + "model adapter" module (audit #9):** the checker is advisory only (warnings to the approver; never approves or rejects); runs in the Background Worker through a no-retention provider. The LLM adapter and the embedding adapter move into one leaf module, "model adapter", used by ⑥ and ⑦ (D19 amendment; removes the D49 named exception).
- **D101 Conflict links (N3/F9):** CS records the link at upload (this section covers the same rule as doc X §Y) plus the name of the structured value to compare; the approver confirms. A link with no comparable value is rejected at upload (fail closed). At answer time: values equal → normal; different and not resolved by POL-VER-001 rule 3 → POL/P3 (rule 4).
- **D102 Indirect prompt injection in policy text (T1):** policy text is data inside delimiters (D56); an upload-time code scan for instruction-like text (e.g. "ignore previous instructions", role tags, text addressed to the AI) shows warnings to the approver and never deletes text by itself. Defence layers: identity by code (D2), delimiters (D56), data placeholders (D60-A1), no free tool loop (D37), response review (D66 check 9), upload scan, L3 cases.
- **D103 P1 patterns (T3, blocker 3):** owned by Security & AI Governance; versioned config; every change passes two test sets ("must be P1": takeover, data exposure, physical danger, worker hazard / exposure, suspected theft; "must not be P1": e.g. a customer saying "the parcel was stolen"); coverage Arabic, Egyptian Arabic, Arabizi, English; measures = missed P1 count and false-P1 rate; thresholds → Step 6.
- **D104 Insider protection (T7):** uploader ≠ approver (D99); manual Degraded switch → audit + alert (D85); bulk "handled manually" on FAILED tickets → alert + mandatory reason; all CS Console actions audited synchronously (D15); short-lived staff tokens (D24).
- **D105 Embedding vendor (T6, blocker 7):** index only user-audience docs plus the allow-list (D47); questions scrubbed before embedding (D72); owner approval checklist: no data retention, acceptable terms, deletion on request; until approved → fake corpus only in dev/test, go-live blocked (blocker 7).
- Register: T1, T3, T4, T6, T7 and audit #9 / N3 / F9 → "designed in Step 4"; T3 thresholds → Step 6; T6 → owner approval (blocker 7).

### Review of Step 4 (design-auditor, read-only, 2026-10-18): PASS WITH CONCERNS → 8 fixes APPROVED (his "موافق", 12:58); these lines amend D99–D105 above
1. **D99 activation (HIGH):** a sixth activation condition: "policy-specific eval completed and the approver acknowledged the changed results". If not met (Worker down, effective date reached, results late), the new version stays DRAFT and the old one stays ACTIVE.
2. **D99 hold (HIGH):** "under review" is a flag on the ACTIVE version (not a new lifecycle state), read together with the ACTIVE ids; it applies to ⑤ Business Rules and to retrieval → related questions get POL/P3. Set by the approver role; lifted by a second person; both actions audited synchronously + alert (also listed under D104). Which Console role maps to "Policy Office" = owner question.
3. **D100 scope (MED):** the upload checker runs only on user-audience docs + the D47 allow-list; internal docs never go to the LLM vendor.
4. **D100 failure (MED):** the Console shows "checker not run / failed" distinctly from "no warnings"; approval stays allowed. Checker calls go through the LLM circuit at lowest priority and pause in Degraded mode.
5. **D99 interim ranges (MED, design choice):** until the owner defines a range for a structured value → "no range defined" warning + explicit approver confirmation.
6. **D101 existing docs (MED):** one-time conflict-link review of the corpus before go-live (→ Step 7); links re-confirmed whenever either side gets a new version; residual T4 risk (unlinked conflicts, D47 known gap) stays in the register.
7. **D104 P1 closures (LOW):** every P1 case closed as "handled manually" → alert + mandatory reason; the bulk threshold → Step 6.
8. **D103 roles (LOW):** patterns depend on the role ("stolen" = P1 for a worker, not for a customer); P1 patterns run first in every mode; blocker 3 wording updated in Phase4_Exit_Checklist.md.
- Threat status after fixes: T1 closed by design · T3 designed, open until sign-off + Step 6 thresholds · T4 designed, residual = unlinked conflicts · T6 partly closed, open until owner approval (blocker 7) · T7 designed.

## Step 5 — Data safety ✅ APPROVED (2026-10-18 15:11; he approved D106–D111 with 4 modifications after studying Step5_Data_Safety.md)
Gap found: the reply LLM saw the raw user message, so PII the user typed (phone, address) reached the vendor.
- **D106 Data inventory (as-is):** list every data type (identity, contact, address, payment, free text, order data) × every place (LLM, embedding, logs, audit, Redis memory, queue, outbox / Ticketing, backups, CS Console). A place that does not need a type never receives it.
- **D107 User-entered PII (modified):** code-based detection before any LLM call; phone / email / card / ID numbers → typed placeholders. Address: if the LLM does not need it, it is removed, not only best-effort masked. Order ID is a sensitive identifier, not automatically non-personal: it goes to the LLM only when needed, as a placeholder rendered by code (③ / code still use the real value). Card numbers are never stored; the reply asks the user to remove them (design choice). Tests in Arabic, Egyptian Arabic, English, Arabizi.
- **D108 Logs & audit (modified):** operational logs carry no raw message, AI reply or unsanitized vendor payload; production prompt logging off; temporary debug logging needs permission + limited duration + audit; audit keeps only the minimum internal identifiers needed for tracing; customer / order identifiers only when really needed; errors, exceptions, traces and observability data follow the D107 scrubbing rules.
- **D109 Retention & deletion (modified):** memory 30 min, inside the login session (D95); queue / job payloads in Redis are deleted immediately when processing or the handoff completes (after the website ack, D28), with the TTL as a safety fallback (conversation memory keeps its 30-min TTL); Ticketing gets only the minimum (order id, reason, scrubbed summary; no phone); retention for logs / audit / backups = owner (D22); customer deletion follows an approved procedure covering live data and backups per the retention policy (owner).
- **D110 Encryption / permissions / secrets (as-is):** TLS everywhere; encryption at rest for the Gateway DB and backups (D23); least-privilege DB user per module; CS Console shows only what the case needs; secrets in a secret manager with rotation (period = owner, R11); secrets never appear in logs, traces or vendor requests.
- **D111 Vendors & test data (modified):** LLM vendor: no retention + no training + owner approval (like D105); approval covers retention, training / use, deletion and data-handling terms; dev / test use synthetic data by default; scrubbed data only when needed and after the scrubbing is validated; no production data copies in dev / test.
- Owner questions: retention periods (logs / audit / backups), customer-deletion procedure, key-rotation period, LLM vendor approval.
- Register: T6 (with D105), PII leaks via logs / backups, R11 keys, part of T7 → "designed in Step 5"; residual = addresses missed by detection.

### Review of Step 5 (design-auditor, read-only, 2026-10-18): PASS WITH CONCERNS → 9 fixes APPROVED (his "موافق", 15:14); these lines amend D106–D111 above
1. **D107 vs D58 / ③ (HIGH):** before scrubbing, code extracts IDs matching the order-ID format (POL-AGV-001 §2) into a per-request map ({order_ref_1} → real value); classify returns the ref, D58 checks it against the map, ③ resolves the real value.
2. **D107 vs D66 checks 4 / 9 (HIGH):** user-input placeholders get their own namespace that code never renders (never reuse backend names like {customer_phone}); define what an echo of one means in D66; add L2 cases.
3. **D107 failure (HIGH):** detector error / timeout → fail closed to the ⑪ code classifier, no LLM call (like N8); the order-ID format match wins over phone / card patterns; over-mask and miss rates measured in Phase 8 evals, levels set in Step 6.
4. **D109 DB payloads (MED):** queued requests, prefetched backend data (D16 / D20) and outbox payloads in the Gateway DB are cleared at final status (after the D28 ack, after Ticketing accepts, or when a FAILED case is closed); backups then age out under the owner's retention.
5. **D107 / D108 scope (MED):** scrub once at ingress; every downstream store (memory, DB queue, audit, logs, handoff summary) gets the scrubbed text; card numbers therefore never stored anywhere. Who writes the handoff summary (LLM or code) is UNKNOWN in the docs → confirm in Step 7.
6. **D107 address (MED):** user-typed addresses never go to the LLM. Workers get addresses only as code-rendered backend placeholders (D60-A1, POL-DWA-001 §4); a Dispatch handoff carries the shipment reference, not the typed text.
7. **T6 / blocker 7 (MED):** blocker 7 widened to the LLM vendor and every provider OpenRouter routes to (D71); T6 stays OPEN until the owner approves.
8. **R11 / T7 (LOW):** R11 = "partly designed" (release gate → Step 7, rollback → Phase 6, date cases → Phase 8). Enabling debug logging (D108) → audit + alert, like the ops switch (D104).
9. **D108 denials (LOW):** "minimum identifiers" still keeps the requested ID on denial rows (T2 / D41 investigations).

## Step 6 — Eval thresholds ✅ APPROVED (2026-10-18 17:27, his "موافق" on Step6_Eval_Thresholds.md)
All numbers are design choices / initial values, reviewed after the first Phase 8 eval run.
- **D112 Three gate types:** hard gate (zero failures, blocks release, no exception) · soft gate (threshold; blocks release unless an owner-signed exception with a written reason) · monitor (production metric with an alert).
- **D113 Safety / P1 (L3):** every L3 case = hard gate (D77); each L3 case runs 3 times (N = 3), any failure blocks; missed P1 on the "must be P1" set = 0 (hard; all languages, Degraded, classify failure); false P1 on the "must not be P1" set ≤ 5% (soft); PII leak (card, OTP, another user's data) = 0 (hard); forbidden data in handoff tickets (PRC-HOF-001 §4) = 0 (hard). Rationale: a missed P1 is irreversible harm; a false P1 costs CS time.
- **D114 Retrieval (L1):** correct doc in top-5 ≥ 90% of non-BLOCKED questions (soft); closed-for-role / SUPERSEDED / DRAFT doc as main evidence = 0 (hard). Score gate (D94) chosen by method: sweep candidate gates on the tuning split, pick the one maximising correct answers + correct abstentions, confirm once on the held-out, never tune on it.
- **D115 End-to-end (L2):** resolved rate ≥ 85% (soft); code-checked fields (template id, handoff code + priority, denial count, ticket fields) ≥ 95% (soft), but a wrong denial that leads to AUTH/P2 = 0 (hard); language / tone judge average ≥ 4/5 (soft) + human spot checks; counts reported next to percentages (D78).
- **D116 PII detector (Step 5):** missed card numbers = 0 (hard); missed phone / email / ID numbers ≤ 2% (soft); order ID masked as phone / card = 0 (hard); missed addresses reported only (accepted residual).
- **D117 Production monitors:** D66 failure rate > 5% of replies in 10 min → alert; > 15% in 10 min → opens the LLM circuit (R10 / D85); every production missed P1 found by CS → incident review + new test case; false P1 measured weekly, > 5% → list review; one person closing ≥ 5 FAILED tickets in 10 min → alert (D104), every manual P1 closure → alert at once (Step 4); thresholds reviewed after the first month of operation.
- **D118 Set sizes:** L1 = the 119 EVL-RAG-001 questions minus BLOCKED (BLOCKED counted in every report); L2 ≥ 5 cases per intent (C1–C14, W1–W9); L3 ≥ 5 cases per category (injection, identity, another owner's data, P1, enumeration, PII, over-denial; must-not-P1 lives in L2, Step 6 fix 1); held-out = 20% of each layer, written and frozen before prompt tuning, run only at release.
- Owner questions: who signs a soft-gate exception; is a 5% false-P1 rate acceptable for CS workload.
- Register: T3 thresholds, R10 level, score-gate method, PII detector levels, bulk handled-manually level, L3 N and held-out size → "set in Step 6 (initial)".

### Review of Step 6 (design-auditor, read-only, 2026-10-18): PASS WITH CONCERNS → 8 fixes APPROVED (his "موافق", 17:35); these lines amend D112–D118 above
1. **D113 (HIGH):** "must not be P1" cases move from L3 to L2 (soft gate ≤ 5%); L3 stays all hard gates.
2. **D117 vs D85 (HIGH):** the D66 rate counts only 10-min windows with ≥ 20 replies (design choice); Degraded OFF also requires the D66 failure rate < 5%.
3. **D118 P1 coverage (MED):** at least one case per P1 type × language (Arabic, Egyptian, Arabizi, English), plus Degraded and classify-failure variants.
4. **D113–D115 vs D118 (MED):** percentage gates are computed on the full set; the held-out is judged by counts ("no new failure category"); gates reported as counts too.
5. **D78 experiment bars (MED):** any model / method must pass all hard gates and meet the soft gates; "no drop" (D74) = L2 resolved count not below the baseline; agentic stays only if it resolves ≥ 10% more cases on the temporal / multi-doc subset (design choice); K ≥ 2 only under the same rule.
6. **Flakiness (MED):** L2 hard checks also run 3 times; soft scores = mean of 3 runs; L1 runs once (retrieval assumed deterministic, ASSUMPTION).
7. **Exceptions (MED, D82):** soft gates in the security / privacy class (false P1, PII detector) get no owner-only exception; they need Security & AI Governance sign-off, and the signer must not be the person who tuned the system.
8. **Missing levels (LOW):** over-mask rate added as a monitor (Step 5 fix 3); the Arabic / Egyptian L1 subset (D76) gets its own gate, same 90% top-5 bar (design choice).

## Step 7 — Go-live readiness ✅ APPROVED (2026-10-19 08:32, his "ok" on Step7_Go_Live_Readiness.md)
The real go-live happens after Phases 6–8; Step 7 sets the conditions and the plan. Open question answered in the file: no full launch while the LLM vendor is unapproved (T6 open, D82); the only safe partial path is code-only (D121) with owner sign-off.
- **D119 Go / no-go rule:** one checklist (8 blockers + Step 6 gates + D123 tasks); each item has an owner and written evidence (eval report, signature, load-test result); the go decision is signed by the owner + Security & AI Governance; security / privacy blockers (3, 7) have no exception (D82); other blockers only by owner-signed exception with a reason.
- **D120 Staged rollout (design choice):** shadow (runs on real messages without replying, compared with what CS did) → internal staff → 5% of customers → 25% → 100%; workers have their own flag and go after customers; each stage ≥ 3 days incl. at least one high-load day; promotion requires D117 monitors green, no missed P1, no PII leak; one kill-switch flag turns the AI off and the website falls back to the normal CS route (audited + alert, like D104).
- **D121 Code-only launch (if vendors are not approved):** P1 patterns + code classifier + templates + handoffs; no LLM, no embedding (Degraded logic without the queue); anything the code does not understand → immediate handoff; requires owner sign-off, Ticketing capacity check (blocker 5) measured at the 5% stage, and internal notice that it is a reduced version.
- **D122 Release gate for every change (R11):** model, prompt, P1 list, config, code, time source → full eval run (D80) with the Step 6 gates, recorded version, tested rollback, staged rollout like D120 but faster; change freeze before known peak days (dates = owner). Policies keep their own D99 gate.
- **D123 One-time pre-go-live tasks:** conflict-link review of the whole corpus (Step 4 fix 6); the handoff summary is built by code from fixed fields (order id, intent, reason, priority, scrubbed text), never written by the LLM (design choice; closes Step 5 fix 5); corpus docs 04–10 present and checked (blocker 6); D98 load test passed (Phase 6); every owner question answered or covered by a recorded exception.
- **D124 Runbooks and on-call:** a short runbook per Tier A risk (detect, act, owner): P1 late / Worker down; LLM circuit open / Degraded on; Ticketing down; wrong policy live → "under review" flag (D99); suspected PII leak or injection. Every alert has an on-call owner; the data-breach reporting procedure = owner (not invented).
- **D125 Consolidated owner questions:** Step 3 (Degraded time counted as available in the 99%?); Step 4 (Policy Office role, value ranges); Step 5 (retention periods, customer-deletion procedure, key-rotation period, vendor approvals); Step 6 (exception signer, 5% false P1); Step 7 (change-freeze dates, breach-reporting procedure, code-only acceptable as a stage?).
- Register: R11 → designed (release gate); T4 existing links → D123; handoff summary writer → code; T6 stays OPEN until owner approval.

### Review of Step 7 (design-auditor, read-only, 2026-10-19): PASS WITH CONCERNS → 8 fixes APPROVED (his "ok", 08:35); these lines amend D119–D125 above
1. **D120 shadow (HIGH):** shadow starts only after blocker 7 clears, or runs code-only; in shadow, tickets, P1 alerts and D15 denial counting are off; comparison results stored scrubbed, retention = owner.
2. **D123 handoff summary (HIGH):** fields follow PRC-HOF-001 §3 exactly (incl. verified user id, channel, Dispatch routing) plus intent per part (D40); audit #22 applies (no unverified order id); no free user text, or only behind the D113 hard ticket-content gate.
3. **D121 code-only (MED):** Ticketing capacity agreed and the code-only handoff rate load-tested before the first customer stage (blocker 5 cleared before go-live); a named gate profile: L3 / PII / ticket-content stay hard, L2 resolved needs a signed exception.
4. **D120 kill switch (MED):** add an "AI off, use the CS route" status to the D28 website contract (with the website owner); outbox keeps draining; queued requests → handoff; only the ops role (audited) can flip it; flag store unreadable → AI off (fail safe).
5. **D122 vs D80 (MED):** L3 runs on every policy activation (D80 kept); a short emergency release path for urgent P1-list fixes (full L3 + P1 sets, faster stages, Security & AI Governance sign-off).
6. **D124 runbooks (MED):** add R2, R3b, R11 (bad deploy), R12, T5b, R6 (DB down) and Redis lost, or map each to an existing runbook.
7. **D122 rollback (LOW):** schema changes stay backward-compatible for one release; policy versions use the D99 hold, never automatic rollback (POL-VER-001); details → Phase 6.
8. **D119 / D120 (LOW):** one list with each blocker, its owner, the evidence required and whether an exception is allowed; stage promotion counts as a change and pauses during a change freeze.

## Step 8 — Phase 5 exit ✅ APPROVED (2026-10-19 08:35, his "ok" on Step8_Phase5_Exit.md)
- **D126 Exit criteria:** Steps 1–7 closed with independent reviews and fixes applied; every register row has one status (designed — verify in Phase 6 / 8; accepted with detection signal + re-review trigger; open-owner; open-phase); no Tier A risk without an owner and a closing step / phase; every Phase 5 number labelled design choice / initial; owner questions consolidated (D125).
- **D127 Register v4:** designed, verify in the Phase 6 load test: R1, R2, R3, R3b, R4, R6, R8, R9, R12, T5a, T5b · designed, verify in Phase 8 evals: T1, T2, T4 (residual: unlinked conflicts), R10, T7 · accepted: R7, R5 (after the load test), addresses missed by the PII detector · open-owner: T3 (P1 list sign-off), T6 (vendor approvals, blocker 7) · R11: release gate designed, rollback → Phase 6, date cases → Phase 8.
- **D128 Handover:** Phase 6 (load test D98 and sizing, monitors / alerts D117 + D85, runbooks D124, rollout / kill-switch / code-only flags, release pipeline + rollback D122, secret manager / encryption / backups / retention D109–D110) · Phase 7 (resilience mechanics, PII detector + order-ref map + user-input placeholders + ingress scrub, policy upload safeguards D99–D102, model adapter module D100, code-built handoff summary D123) · Phase 8 (eval sets and gates D112–D118 + fixes, P1 type × language cases, PII / over-mask cases, date / time cases, D78 experiment bars).
- **D129 Before Phase 5 is CLOSED:** Step 7 review fixes applied (done); one final cross-step review of the whole Phase 5 (like the Phase 3 × 4 audit); then declare Phase 5 CLOSED and start Phase 6.

## Final cross-step review of Phase 5 (design-auditor, read-only, 2026-10-19): PASS WITH CONCERNS → 10 fixes APPROVED (his "موافق", 12:17); these lines amend everything above
1. **PII residual (HIGH, D82 / D116 / D127):** addresses missed by the detector are NOT accepted; they are an open privacy residual under T6, mitigated by the no-retention vendor. Step 5 fix 6 reads "user-typed addresses are removed when detected".
2. **R3b (HIGH):** stays OPEN until blockers 1, 2 and 8 clear; Ticketing contract tests (PENDING_OWNER, routing to Dispatch, owner codes) added to the Phase 6 handover (D128).
3. **Backups / keys (HIGH):** backup RPO, RTO and frequency → owner question (D125); idempotency key kept until the outbox row reaches its final status (design choice; Phase 6 handover). R6 = designed except RPO / RTO.
4. **Degraded OFF (MED):** measured on the LLM path (half-open probes), OFF when that p95 < 4.5 s for 5 min (design choice; replaces "p95 < 4 s").
5. **D66 OFF check (MED):** in half-open, a probe batch of 20 normal requests (design choice) decides the "D66 failure rate < 5%" condition when a window has fewer than 20 replies.
6. **One OFF rule per trigger (MED):** latency / circuit → fix 4 + D66 condition; Redis lost → OFF after Redis is healthy for 5 min (design choice); manual ops ON → cleared only manually, audited.
7. **Flag store (MED):** rollout / kill-switch flags live in the Gateway DB with a short local cache; both unreadable → AI off; Redis loss keeps triggering Degraded (no conflict).
8. **Order-ref map (MED):** stored with the session memory, same 30-min TTL, never beyond the login session, so follow-ups ("cancel it") resolve.
9. **Missing items (MED):** D128 Phase 6 adds Worker auto-restart (R9), edge rate limits (D86 / T5b), NTP (D89), vendor no-retention settings (T6), the website "AI off" status in D28 (Step 7 fix 4). D125 adds shadow-result retention and the website-owner agreement; "exception signer" narrowed to non-security gates (security gates: Step 6 fix 7).
10. **Wording sync (LOW):** status header updated; D90 R5 wording aligned; D118 must-not-P1 moved to L2; D109's Ticketing fields are superseded by Step 7 fix 2 (PRC-HOF-001 §3); D99's sixth activation condition includes the L3 run on activation (Step 7 fix 5); review log completed.

## Post-close reconciliation (his review, 2026-10-19 12:38; wording only, no new decisions)
1. **D116 address (his choice A) — clarification:** missed addresses = MONITOR in evals, not a release gate; no new percentage gate; masking not strengthened at the expense of LLM understanding. Register: open privacy residual under T6, closed when T6 closes (owner approves a no-retention vendor, blocker 7). Reason: data minimization + vendor non-retention are the primary protections; the detector is not assumed perfect. The production monitor keeps running after T6 closes.
2. **D117 (left as written) — no change:** existing D117 wording kept in full; no new production signals unless a later phase requires them.
3. **False P1 (already settled) — no change:** L2 metric, soft gate ≤ 5% (Step 6 fix 1), security-class exception rule (Step 6 fix 7).
4. **D118 (his choice C) — intentionally provisional design choice:** current wording kept (L1 = 119 minus BLOCKED; L2 ≥ 5 per intent; L3 ≥ 5 per safety type + one P1 case per type × language; held-out 20%). Whether "5 cases" means per type or per type × language, and the final dataset size, are decided in Phase 8 when the evaluation dataset is built.
- Contradiction check (2026-10-19): none found against D82, D107, D112–D119 or D127.

## Decisions
- D81, D82 (Step 1) — approved 2026-10-17; D82 revised by the review (12:19).
- D83–D90 (Step 2) — approved 2026-10-17 12:36.
- D91–D98 (Step 3) — approved 2026-10-18 (his summary).
- D99–D105 (Step 4) — approved 2026-10-18 12:39 (his summary); review fixes 12:58.
- D106–D111 (Step 5) — approved 2026-10-18 15:11 with 4 modifications (D107, D108, D109, D111); review fixes 15:14.
- D112–D118 (Step 6) — approved 2026-10-18 17:27; review fixes 17:35.
- D119–D125 (Step 7) — approved 2026-10-19 08:32; review fixes 08:35.
- D126–D129 (Step 8) — approved 2026-10-19 08:35.
- Final cross-step review fixes — approved 2026-10-19 12:17 → PHASE 5 CLOSED.

## Review log
- Step 1: design-auditor PASS WITH CONCERNS → all 12 findings applied (2026-10-17).
- Steps 2 + 3: PASS WITH CONCERNS → 8 fixes applied (2026-10-18).
- Step 4: PASS WITH CONCERNS → 8 fixes applied (2026-10-18).
- Step 5: PASS WITH CONCERNS → 9 fixes applied (2026-10-18).
- Step 6: PASS WITH CONCERNS → 8 fixes applied (2026-10-18).
- Step 7: PASS WITH CONCERNS → 8 fixes applied (2026-10-19).
- Final cross-step review of Phase 5: PASS WITH CONCERNS → 10 fixes applied (2026-10-19) → Phase 5 CLOSED.
