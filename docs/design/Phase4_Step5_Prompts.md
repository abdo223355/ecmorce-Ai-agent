# Phase 4 — Step 5: Prompts & Context ✅ CLOSED (2026-10-15, after analysis + review; D57 extended at the Phase 4 exit; audit errata applied 2026-10-16/17)

Phase 4 = what/why; numbers = Phase 5; code = Phase 7. Earlier: Step 1 claude/Phase4_AI_Design.md · Step 2 claude/Phase4_Step2_Agents.md · Step 3 claude/Phase4_Step3_Tools.md · Step 4 claude/Phase4_Step4_RAG.md.
Audit errata (claude/Phase3_4_Audit.md): round 1 (2026-10-16) — #1 classify failure and P1, #4 day counts as placeholders, #5 policy numbers, #15 delivery instructions and the judge+rewrite query; round 2 (2026-10-17) — N1 narrow P1 patterns, N4 number matching, N8 full code classifier.

## D54 — Prompt types
- Per agent: classify / judge+rewrite (only when the D50 score gate opens) / reply. Versioned in git like templates; engineering-owned; reviewed by Customer Operations AND Security and AI Governance (owner of POL-AIS/PRV/AKU-001).
- Every request records the prompt version id next to policy versions (⑩ / metrics); a prompt change ships only after the Step 9 evaluation runs.

## D55 — Context (minimum necessary, POL-PRV-001 §1.1/§3, D17)
- **Classify** sees the message + the pending clarification as option indexes with non-personal labels only (e.g. "option 2: order with 2 items"); no backend values, no identity. Pure "2" / "the second" replies are resolved by CODE against ③'s mapping without the LLM (if ③ has no mapping: lost context, D65).
- **Judge+rewrite** sees only the English search query, scrubbed with the D72 rules before the call (audit #15), + the retrieved chunks; no raw message, no personal data.
- **Reply** sees the message, intents, non-personal facts (status, eligibility result), ⑤ result as typed placeholders for every number (day counts included, audit #4), retrieved sections with IDs, and typed placeholders for personal/payment values (D60-A1); never identity, token, customer_id / worker_id.

## D56 — Prompt injection (POL-AIS-001 §5, POL-AGV-001 §2)
- Every untrusted text is wrapped as DATA with a delimiter generated fresh per request: the user message and retrieved policy text.
- **Free-text backend fields** (e.g. delivery instructions typed by the customer, POL-DAD-001 §2) are ALWAYS placeholders, never sent to the LLM (revised, audit #15: they can carry personal details and injected text; the old "or wrapped as data" option is withdrawn).
- Delimiter strings and braces in user text are stripped/escaped. Security is still enforced by code.

## D57 — Reply style
- Reply in the user's language; the language comes from an enum field in the classify JSON (code detects it from the script if classify fails).
- Arabizi (Arabic written in Latin letters, "3ayez…") → reply in Arabic script (Egyptian) when classify flags Arabizi with confidence; otherwise English. The D66 language check treats Arabizi → Arabic as a match. (Design choice, approved by him at the Phase 4 exit.)
- Arabizi coverage everywhere patterns are used (added at the Phase 4 exit): the P1 pattern list, the injection patterns and the code classifier include Arabizi variants (e.g. "7ad da5al 3ala el account"); Arabizi L2/L3 eval cases (D76).
- Neutral, polite, no blame; Egyptian Arabic allowed for Arabic users (from D53, not from a policy; POL-COM-001 style rules UNVERIFIED until docs 04–10 are added).
- Handoff wording covers PRC-HOF-001 §5 (who continues, what is shared, when to expect a reply from POL-BUS-001 facts) and §6 for workers (nothing beyond the approved procedure).

## D58 — Classify output
- Strict JSON validated by code: per-part safety + escalation flags, intents from the agent's own catalog only, arguments, English search query, language enum (incl. Arabizi flag), needs_explanation flag per part (D73).
- Extracted order/shipment IDs must appear word-for-word in the message or ③'s mapping and match the POL-AGV-001 §2 format.
- **P1 never depends on classify (audit #1, narrowed by N1):** a code P1 pattern check in ⑪ runs on every message in every mode BEFORE the agent; a hit forces the P1 path whatever classify says (CP-43, CP-44, POL-BUS-001 §3). The patterns cover only the three P1 cases of POL-AGE-001 §2 — account takeover, data exposure, physical danger — as phrases, not single words (a customer's stolen parcel is C12, not P1); for delivery workers also the procedure-defined P1 cases — hazardous / leaking shipment (PRC-DMG-001 §2) and suspected theft of a shipment (PRC-MSG-001 §5). Classify's own safety flag still catches P1 cases the patterns miss. The list is signed off by Security & AI Governance (go-live blocker 3), and false P1s are counted in ⑩.
- Invalid JSON or timeout = classification failure → FAIL CLOSED on the LLM path: no LLM plan path, no backend calls through the agent. The message goes through ⑪'s FULL code classifier (the same one Degraded mode uses, N8): fast-path intents → status templates; rule-detected complaint → CMP handoff; rule-detected out-of-V1 action → mandatory SCOPE/P4 handoff (POL-AGE-001 §2); anything else → for customers template 15, which always carries the emergency line and offers a human (POL-AIS-001 §6); for delivery workers a handoff to Dispatch / CS with template 6 (Step 8). A system classify failure is not counted as the user's unclassified attempt (N8) — an interpretation of POL-AGE-001 §2 "after 2 attempts" (design choice). (Revised, audit #1: before, the fallback offered only a human and nothing could detect P1.)
- Provider structured-output / JSON mode used if available on hosts that meet D17's no-retention rule (checked in Step 8: D71 gate); the fallback stays either way.

## D59 — Token budget
- Caps on chunks and fields are TOTALS across all agentic rounds of a request, not per round (numbers Phase 5).
- Static system prompt first for provider prompt caching; caching only where allowed under no-retention (decided in Step 8, D74).

## D60-A1 — Placeholder rendering (my analysis, adjusted by review)
- The reply LLM never sees POL-PRV-001 §2 personal or payment values (customer name/phone/address, COD amount, order/shipment IDs). It writes typed placeholders ({customer_phone}, {order_id}…); CODE substitutes real values after validation.
- Each placeholder carries a state: present / masked / unavailable (POL-DWA-001 §4 access window, POL-AIS-001 §3).
- Placeholders are scoped to one entity (no value swapping in multi-order lists); code substitutes only fields this intent is authorized to show; code formats dates and digits for the reply language.
- **Day counts are placeholders (revised, audit #4):** {days_left}, {days_since_delivery} and similar ⑤ results are placeholders; CODE renders the number with correct Arabic number agreement (e.g. يوم / يومين / أيام / يوماً) and English plural. The eligibility result (eligible / not eligible / review required / unknown) is a typed field from ⑤, written by code-chosen wording. Was: "Day counts and the eligibility result stay plain text so Arabic grammar works" — withdrawn, because it contradicted D66 check 3 (the LLM would type the number).
- **Policy numbers (revised, audit #5; tightened, N4):** a number that is a policy rule is placed in one of two code-verified ways:
  - (a) a number that equals a D13 structured value of the cited version (numbers used in calculations, e.g. a window length) MUST be a placeholder filled by code — the LLM may not type it even if it appears in the section (so "electronics: 30 days" cannot slip through because 30 appears elsewhere in POL-RET-001 §2);
  - (b) any other policy number (e.g. "EGP 40", "5 to 10 business days", "within 30 minutes") may be copied by the LLM only if the same number AND unit appear in the cited retrieved section. Code compares normalised tokens: Arabic-Indic and Latin digits are equal ("٤٠" = "40"), and units are matched through a small fixed synonym table (e.g. EGP = جنيه, business days = أيام عمل, minutes = دقيقة/دقائق). A number with no matching unit fails.
  - D13 is not widened. (Design choice.)
- Benefits: minimum data to the third-party LLM; values cannot be altered by the LLM; simpler validation; fewer tokens.

## Carried to Step 6
- Multi-turn references ("and the other one?") need prior-turn context → Memory.

## Review log
- design-auditor on D54–D59 + my amendments: PASS WITH CONCERNS, ready after fixes 1–5 → applied (free-text backend fields as data; classify sees indexes + non-personal labels; fail closed; ID checks; judge+rewrite context). A1–A6 accepted/adjusted as above.
- Phase 4 exit (2026-10-16, approved): Arabizi rule + keyword coverage; policy numbers as structured-value placeholders.
- Phase 3+4 cross-phase audit round 1 (2026-10-16): FAIL (errata) → applied: #1 P1 check before classify + code classifier on classify failure + template 15 emergency line; #4 day counts as placeholders; #5 verbatim policy numbers; #15 free-text backend fields always placeholders, judge+rewrite query scrubbed.
- Round 2 (2026-10-17, his "موافق"): N1 P1 patterns for takeover / exposure / danger only; N4 structured-value numbers must be placeholders, other numbers matched as number + unit across Arabic and English; N8 full code classifier incl. complaint rule, classify failure not a user attempt.
