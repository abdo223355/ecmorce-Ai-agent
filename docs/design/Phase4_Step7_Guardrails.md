# Phase 4 — Step 7: Output control & Guardrails ✅ CLOSED (2026-10-16; D66/D68/D70 extended at the Phase 4 exit; audit errata applied 2026-10-16/17)

Phase 4 = what/why; numbers = Phase 5; code = Phase 7. Learning deck: Step7_Guardrails_Explained.pptx (16 slides, delivered in chat 2026-10-16; describes the pre-exit version — this doc is the source of truth).
Core rule: the LLM proposes, code decides what leaves (POL-AIS-001 §4, §6).
Audit errata (claude/Phase3_4_Audit.md): round 1 (2026-10-16) — #1 template 15, #4/#5 check 3, #7 static fallback scope, #11 rendering owner, #17 template 9, #18 severity scope, #20 template 19; round 2 (2026-10-17) — N1 P1 no-data flag scope, N4 number matching, template 5 interim label.

## D66 — validate-reply (code, content level)
Runs on every reply part, LLM-written or template, before anything is sent. Checks:
1. Every fact about a transaction comes from validated ④ data through a placeholder (POL-AIS-001 §2.1, §4).
2. Every rule is tied to a (doc_id, version, section) from the set retrieved in this turn (a "why?" follow-up re-fetches the card's section first, D62, audit #14), and that doc's Audience includes the caller's role (POL-AIS-001 §2.2–2.3, §4; D34). By-name exceptions are honoured exactly: POL-SPC-001 for customers (D47-a); Glossary entries only once the Policy Office approves them, per (doc_id, section) (D47-b).
3. **Numbers (revised by audit #4/#5, tightened by N4):** every number in the reply is placed in a way code can verify:
   - a number about the user's case (days left, amounts, eligibility) is a placeholder filled from ⑤ / ④ (day counts included, D60-A1);
   - a number that equals a D13 structured value of the cited version must be a placeholder filled by code; a typed digit equal to such a value FAILS, even if it appears in the section;
   - any other policy number the LLM writes (e.g. "EGP 40", "5 to 10 business days") passes only if the same number AND unit appear in that segment's cited retrieved section, compared as normalised tokens (Arabic-Indic = Latin digits; units through a fixed Arabic/English synonym table, e.g. EGP = جنيه).
   Any other digit typed by the LLM fails check 3. (Design choice.)
4. Placeholders only from the intent's allowed fields (POL-AIS-001 §4 "no unauthorized field").
5. No promise of an outcome a human has not approved (POL-AIS-001 §4). Interpretation (design choice): no free-text dates or compensation; backend dates/ETAs via placeholders are allowed.
6. Reply language = language from classify (design choice, D53/D57; Arabizi → Arabic counts as a match). Checked on the text with placeholders and identifiers removed; in Degraded mode and after a classify failure a code-based script detector is used (no LLM).
7. No claim of non-existence ("this order doesn't exist") in Arabic or English (POL-AIS-001 §2.7, POL-BDR-001 §2 404 rule).
8. A user-vs-backend conflict is stated with fixed neutral wording: plan sets a conflict flag (POL-AIS-001 §2.5).
9. Block forbidden patterns in the reply: card numbers, OTPs, passwords (PRC-HOF-001 §4), and threshold / denial-count wording (D67).

How it is enforced: the reply LLM returns structured segments; each segment carries a citation (doc_id, version, section) or placeholders. Digits typed by the LLM outside placeholders pass check 3 only when (a) they do not equal a D13 structured value of the cited version and (b) the same normalised number and unit appear in that segment's cited section. Promise detection by word list is best effort; the real guard is "dates only from placeholders".

On failure — two classes (revised at the exit, his approval):
- **Security failure** in ANY part (check 2 Audience, check 4 unauthorized field, check 9 forbidden pattern / possible personal data, injection signs) → the whole reply is dropped → handoff. All parts come from one LLM call, so the other parts are suspect too.
- **Content failure** (missing citation, number not placed or not verifiable by code, language, promise wording) → per part (D30): that part's D68 template if one exists, otherwise a handoff for that part; the reply is rebuilt in written order.
- No retry loop in either class (same model and context tend to repeat the error; tokens and time; POL-AIS-001 §2.8/§6; matches D27 "no live retry").

## D67 — Internal-rule topics
- "Internal" = content whose doc Audience does not include the caller's role (D34). Worker-audience procedures are NOT internal for workers.
- Plus a fixed list in code, always internal (design choice): prompts / system instructions, escalation thresholds and denial counting, fraud signals (fraud flags backed by PRC-HOF-001 §4).
- Classifier only tags topic=internal_rule; code chooses the neutral D68 "internal rule" template. Because a tag can be dodged by injected text, D66 check 9 also scans outgoing text. Closes the D34 Step-7 item.

## D68 — Templates
Chosen by intent / outcome code (not by LLM matching), filled by code with values from ④/⑤/⑥ only, through the same ④/⑤ shaping functions the tool handlers use (access window, deny-list, shared denial recording). **Rendered by ⑪** (Phase 3 duty; audit #11), so the fallback path never depends on ⑦. Closes the Phase-3 "template matching" item.
Set:
1–3. Status templates (fast path D73 + Degraded mode): order status / return status / worker shipment list. (Renamed at the exit, F1; were called "Degraded answers".)
4. Degraded clarification ("which order?" with the user's own list).
5. Handoff acknowledgement — customer: a CS agent will continue, what will be shared, expected reply time (PRC-HOF-001 §5, POL-BUS-001). For a PENDING_OWNER handoff no reply time is promised until go-live blocker 1 is cleared (audit #7) — an **interim deviation** from PRC-HOF-001 §5, which ends before go-live.
6. Handoff acknowledgement — worker: Dispatch/CS notified; "what to do meanwhile" only from a worker-audience procedure, else omitted (PRC-HOF-001 §6).
7. After hours: ticket created + next opening time as a structured value (PRC-HOF-001 §7, D34).
8. P1 emergency (emergency line, PRC-HOF-001 §7). The P1 no-data flag on the login session (CP-44) is set only for account takeover and data exposure (POL-PRV-001 §5 "stops sharing further data"); a physical-danger P1 gets the emergency line and the SAFE handoff without blocking the session's data (narrowed, audit N1; design choice).
9. Out of scope (D31). For sign-in / login problems it points to the website help page and CS contact (D29, audit #17).
10. Action outside V1: what V1 can do + direct to Customer Service (POL-AIS-001 §3; SCOPE).
11. Information unavailable (backend value missing / BKD, POL-AIS-001 §3).
12. Policy could not be confirmed (POL, POL-AIS-001 §3); also used for conflicting ACTIVE documents (POL-VER-001 §3 rule 4, audit #3).
13. Internal rule (D67).
14. Not found among your recent orders — worded as "no matching record", never as non-existence (D32, POL-AIS-001 §2.7).
15. Classification failure (D58 fail-closed) — **always carries the emergency line** for urgent safety issues plus the offer of a human (revised, audit #1; CP-43).
16. Worker: "no shipment with this number among your assigned shipments" (worker 404 / another worker's shipment; Phase 3 quality-scenario wording; D35, D41). Added at the exit, F2.
17. Field not available: neutral "this information can't be shared", plus the permitted alternative ONLY when the policy text gives one (POL-DWA-001 §6, e.g. phone; POL-AIS-001 §2.3). Added at the exit, F2.
18. "I couldn't finish this part right now" + offer of a human; a ticket is opened only if the user accepts (C6). Used when a System 2 part runs out of time and has no template (D75). Added at the exit, F5 (design choice).
19. REVIEW_REQUIRED (added, audit #20): the rule changed since the order was placed and Customer Service will review the request (D21, POL-VER-001 §4 "customers are not retroactively disadvantaged"); never a final no; POL/P3 handoff called by ⑪.
Wording: reviewed by Customer Operations (design choice, not a policy rule) and re-reviewed whenever a cited policy version changes (POL-VER-001).

## D69 — No streaming in V1
The whole reply passes D66 before any word leaves (POL-AIS-001 §4); a shown word cannot be taken back. Matches D27 (non-streaming adapter). Latency handled in Step 8 (typing indicator). Closes the parked streaming item.

## D70 — Reason codes
- Use PRC-HOF-001 §2 codes (BKD, POL, AUTH, INFO, SCOPE, SAFE, CMP) where the policy defines them.
- Codes not defined → owner questions (Customer Operations), kept in config, never invented: user asks for a human; human-now button; queue timeout; unclassified intent (incl. an unrecognised worker message in Degraded mode); delivered-not-received; worker complaint; validation failed with no template.
- Priorities that POL-AGE-001 already gives are used now (e.g. unclassified intent after 2 attempts = P4). "User asks for a human" (§3 optional) has no priority → owner question.
- Interim runtime rule: the ticket is created with code = PENDING_OWNER and the policy priority (if any); a handoff never waits on an unanswered owner question. Note (audit #7): PENDING_OWNER is outside D26's "7 reason codes" contract, so until the contract test passes such a ticket may end FAILED; therefore template 5 promises no reply time for it.
- **Severity scope (clarified, audit #18):** when several codes apply to the SAME case or part, the highest-severity code wins (a P1 / SAFE signal is never sent as PENDING_OWNER; scenario S14). Different parts of one message keep D33: different reason codes → separate tickets (e.g. a mandatory SCOPE/P4 is not dropped next to a CMP).
- **Static fallback scope (revised, audit #7):** handoffs are sent asynchronously through the outbox (D14), so FAILED is known only after the user was answered. The static fallback (CS contact + hours) is shown on the live path only when the Ticketing circuit is open or the Gateway DB is down (as in Phase 3). A handoff that later ends FAILED appears in the CS Console for follow-up (Phase 3); who watches FAILED after hours is an open Phase 3 question (Exit §6). Was: "a handoff that ends FAILED shows the static fallback" — withdrawn (could not work on the live path).
- Go-live blockers: a contract test with the Ticketing owner proving PENDING_OWNER (and a missing priority) is accepted AND routed to a real queue; the owner's decision on the "talk to a human" code; the queue-timeout and human-now codes (audit #8). Closing Phase 4 with PENDING_OWNER is an exception to the Phase 3 gate, signed by عبدالرحمن on 2026-10-16.

## Review log
- design-auditor on D66–D70: PASS WITH CONCERNS → all fixes applied: per-part failure (D30); handoff acknowledgement split customer / worker / after-hours; D66 checks 7–9 and role-audience in check 2; structured segments for enforceability; D67 internal = not in caller's Audience (worker procedures allowed) + outgoing scan; D68 added templates 4, 10, 11, 12; D70 priorities from POL-AGE-001 + PENDING_OWNER; language check in Degraded mode; design choices labelled.
- Exit-checklist erratum (2026-10-16): template 15 cited D57; the fail-closed rule is D58.
- Phase 4 exit analysis + scenario tests (2026-10-16, approved): two failure classes; check 3 rewritten (F3); by-name exceptions in check 2; templates renamed (F1) and 16–18 added (F2, F5); highest severity wins; FAILED → static fallback; go-live blockers.
- Phase 3+4 cross-phase audit round 1 (2026-10-16): FAIL (errata) → applied: #1 template 15 emergency line; #4/#5 check 3 rewritten; #7 static fallback scope + no reply time for PENDING_OWNER; #11 templates rendered by ⑪; #14 check 2 with re-fetched sections; #17 template 9 login pointer; #18 severity scope; #20 template 19 REVIEW_REQUIRED. Template count is now 19.
- Round 2 (2026-10-17, his "موافق"): N4 check 3 — structured-value numbers must be placeholders, other numbers matched as normalised number + unit; N1 P1 no-data flag only for takeover / data exposure (template 8); template 5 labelled an interim deviation; unrecognised worker message in Degraded mode under the "unclassified" owner code.
