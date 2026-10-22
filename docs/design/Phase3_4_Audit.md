# Cross-phase audit — Phase 3 (D1–D29) × Phase 4 (D30–D80)

Date: 2026-10-16/17 · Requested by عبدالرحمن ("اعمل فحص phas 3+4") · Reviewers: independent design-auditors (did not author the design)
Status: **Round 1 FAIL → 23 errata approved (2026-10-16 19:32) and applied. Round 2 re-verification PASS WITH CONCERNS → N1–N11 approved (2026-10-17 00:41) and applied. Round 2 re-check (fresh reviewer) PASS WITH CONCERNS → consistency fixes F1–F5, F8, F9 applied; F6 / F7 approved (2026-10-17 10:27) and applied. AUDIT CLOSED.**

## Round 1 verdict: ❌ FAIL (no redesign needed)
The architecture is sound and small text changes fix every ❌, but 4 findings broke a binding Phase 3 rule or an ACTIVE policy, and one of them (#1) affected P1 safety. Under the verify-design rule, a FAIL reopens the affected Phase 4 decisions as errata before Phase 5 starts.

Checked against the sources myself (#3, #4):
- POL-RET-001 v2.1 §9: "Orders delivered between 2026-11-15 and 2026-12-31 may be returned until 2027-01-31 … The longer of the two windows applies." §11: "Customer requests an exception to the window. Only Customer Service may grant exceptions."
- POL-SPC-001 §2 says the same, adds a holiday exchange extension until 2027-01-15.
- Step 5 D60-A1 said "Day counts and the eligibility result stay plain text so Arabic grammar works", which contradicted D66 check 3.

## Round 1 findings and the approved decisions (all APPLIED; where each landed: Exit checklist §4b)
| # | Sev | Finding | Approved decision | Round 2 status |
|---|---|---|---|---|
| 1 | ❌ | P1 not detected when classify fails in normal mode; template 15 had no emergency line | P1 check in every mode before classify; classify failure → code classifier; template 15 always carries the emergency line | RESOLVED (refined by N1) |
| 2 | ❌ | Unrecognised worker messages entered the 3-minute queue (contradicts D16) | Customers only; worker → handoff, template 6 | RESOLVED |
| 3 | ❌ | Holiday extensions, exception requests and conflicting ACTIVE documents had no design | ⑤ computes holiday windows (longer wins); exception → CS; conflict → POL/P3 by code via links | RESOLVED (refined by N3) |
| 4 | ❌ | D60-A1 plain-text day counts vs D66 check 3 | Day counts are placeholders rendered by code | RESOLVED |
| 5 | ⚠️ | Policy numbers without structured values | Verbatim from the cited section, checked by code; D13 not widened | RESOLVED by N4 |
| 6 | ⚠️ | Graph inside a queued job undefined | Snapshot, no denials, prefetch rule, ACTIVE ids at job start, deadline | RESOLVED by N5 |
| 7 | ⚠️ | PENDING_OWNER vs D26; FAILED → static fallback impossible on the live path | Static fallback only on circuit open / DB down; no reply time for PENDING_OWNER | RESOLVED |
| 8 | ⚠️ | Phase 3 open questions dropped | All five in Exit §6; blockers 2 and 8 | RESOLVED (N6) |
| 9 | ⚠️ | Impossible LLM-checker recommendation | Withdrawn; "model adapter" module → Phase 5 | RESOLVED (moved) |
| 10 | ⚠️ | No per-node latency budget | p95 in D78; budget + cut order → Phase 5 | RESOLVED (moved) |
| 11 | ⚠️ | Fallback path depended on ⑦ code | Shaping in ④/⑤; ⑪ owns templates, code classifier, P1 check | RESOLVED by N2 |
| 12 | ⚠️ | Embedding provider = 4th external system | Own circuit; index only user-audience docs; blocker 7 | RESOLVED (owner) |
| 13 | ⚠️ | Denial definition widened silently | Labelled interpretation, D15 amendment; evidence rule | RESOLVED (N10) |
| 14 | ⚠️ | "Why?" from memory fails check 2 | Re-fetch the cited section; re-derive on version change | RESOLVED |
| 15 | ⚠️ | Personal data leaks | Free-text fields always placeholders; scrub before judge+rewrite; narrow clue field | RESOLVED |
| 16 | ⚠️ | Missing docs not a blocker | Blocker 6; D32 and C7 tagged | RESOLVED |
| 17 | ⚠️ | No intent for account problems after login | C14; template 9 help-page pointer | RESOLVED |
| 18 | ⚠️ | "Highest severity wins" vs D33 | Within one case or part only | RESOLVED |
| 19 | ⚠️ | Superseded text still current | Phase 3 amendments table; notes; Exit counts | RESOLVED (N7, F3) |
| 20 | ⚠️ | D52 vs D21 | D52 = never retrieved or shown; template 19 | RESOLVED |
| 21 | ⚠️ | Provider fallback vs no live retry | Routing inside one adapter call | RESOLVED |
| 22 | ⚠️ | Unverified order ID in tickets | Only if in the user's own list | RESOLVED |
| 23 | ⚠️ | One field for category and sale label | Separate flags | RESOLVED (N11) |

## Round 2 — new findings N1–N11 (APPROVED 2026-10-17 00:41, APPLIED)
| # | Sev | Finding | Applied decision |
|---|---|---|---|
| N1 | ⚠️ high | Broad P1 keyword list over-triggers in normal mode | Phrase patterns only for takeover / data exposure / physical danger (+ worker procedure P1 cases: hazardous PRC-DMG-001 §2, suspected theft PRC-MSG-001 §5); no-data flag only for takeover / data exposure (template 8); "must not trigger" cases; false-P1 count; sign-off = blocker 3 |
| N2 | ⚠️ high | Denials not counted on ⑪'s template path | One shared ④/⑤ denial recorder for both paths; L3 enumeration case |
| N3 | ⚠️ med | "Same rule" link escalated agreeing documents | Code compares linked structured values; escalate only when different |
| N4 | ⚠️ med | Check 3 number matching | Structured-value numbers must be placeholders; other numbers matched as normalised number + unit (Arabic / English) |
| N5 | ⚠️ med | Queued-job gaps | ③-resolved prefetch; missing record → merged deferred handoff now; prefetch 404 → template 14, not queued |
| N6 | ⚠️ | P1 in a later queued message | Interim design choice: deferred ticket carries the sibling line + "hold" note |
| N7 | ⚠️ med | Stale status docs | Fixed (CP-107, CP-108) |
| N8 | ⚠️ low | Classify-failure path incomplete | Full code classifier incl. complaint → CMP and out-of-V1 → SCOPE/P4; classify failure not a user attempt (labelled interpretation) |
| N9 | ⚠️ low | Step 0 wording | Step 0 runs in ⑪ before the agent |
| N10 | ⚠️ low | Name as evidence | Worker ID only |
| N11 | ⚠️ low | D44 flags assume backend data | Labelled ASSUMPTION; backend-owner question |

## Round 2 re-check (2026-10-17, fresh independent reviewer, read-only) — PASS WITH CONCERNS
All N-findings were in the text; no invented policy rule; counts correct (19 templates, C1–C14 / W1–W9, 9 checks, 8 blockers). Fixes applied the same night (consistency only, no new decision):
- F1 classify failure for workers → template 6 handoff, now also in Step 2 and D58.
- F2 diagram: step 0 (⑪ P1 patterns) before classify; classify-failure branch (template 15 for customers); "status template" name.
- F3 status records, dates (round 2 = 2026-10-17), "keyword" → "pattern" in the scenario doc.
- F4 "classify failure is not a user attempt" labelled an interpretation of POL-AGE-001 §2.
- F5 Phase 3 amendments row now cites D68 template 8 for the no-data flag.
- F8 later queued messages end HANDED_OFF when the merged handoff is sent early.
- F9 links without comparable structured values → Phase 5 upload safeguards (Exit §7).
**Approved by him ("موافق", 2026-10-17 10:27) and applied as recommended:**
| # | Question | My recommendation |
|---|---|---|
| F6 | Worker P1 cases from the procedures (hazardous / leaking shipment, suspected theft): which reason code, and how does Dispatch hear about it? | Design choice: reason code SAFE for both (P1 safety signal; never PENDING_OWNER, D70), the ticket uses the Dispatch routing field (PRC-MSG-001 §5 "always notify Dispatch", blocker 8), and the worker's reply carries the procedure's "meanwhile" step only from the worker-audience procedure (e.g. PRC-DMG-001 §2) via template 6 + template 8. Exact code for suspected theft added to the Customer Operations owner question |
| F7 | Does the "hold" note on a merged deferred handoff apply to every P1? | Only when the P1 sets the no-data flag (account takeover, data exposure); a physical-danger P1 leaves the queued case as normal |

## Process note (2026-10-17)
While the round 2 re-verification was running, some docs (Phase 3 doc, Step 1) and the agent-graph diagram (versions 6–8) were changed by someone other than the main session, before his approval — most likely the reviewer agent, although it reported no edits. Every changed text was re-read and checked against the approved N1–N11 batch; all of it matched, and the docs were then rewritten by the main session. Reviewers are launched strictly read-only from now on.

## Checked and passed (still true)
- Identity never reaches the LLM; MCP token server-side only; agents chosen by code (D36).
- ④ is the only door to Flask; ⑥ is the only module touching the Vector Store.
- Retrieval filtered by version_id + ACTIVE + Audience; D23 change explicit in D48.
- D69 vs D27/D28; D66 no retry vs D27; D75 shared deadline and circuit check (POL-BDR-001).
- Memory inside D22; denial counts and the P1 flag stay in the DB.
- Bounded execution (D40, D42, 3 clarification rounds); policy citations accurate; no invented numbers.

## Decision log
- 2026-10-16 19:32 — round 1 fix batch approved ("موافق") and applied (CP-107).
- 2026-10-17 00:41 — round 2 N1–N11 approved ("موافق") and applied (CP-108); re-check fixes F1–F5, F8, F9 applied.
- 2026-10-17 10:27 — F6 and F7 approved ("موافق") and applied (Step 1 W7, Step 2, Step 8, Exit §6) (CP-109). Audit closed.
