# Phase 4 — Step 3: Tools & contracts ✅ CLOSED (2026-10-15; D43 note added at the Phase 4 exit; audit errata applied 2026-10-16/17)

Phase 4 = what/why; numbers = Phase 5; code = Phase 7. Step 1: claude/Phase4_AI_Design.md · Step 2: claude/Phase4_Step2_Agents.md.
Audit errata (claude/Phase3_4_Audit.md): round 1 (2026-10-16) — #6 queued-job rule, #11 module ownership of shaping / templates, #13 query-denial evidence, #23 item flags; round 2 (2026-10-17) — N2 one shared denial recorder, N5 queued-job gaps, N10 worker id only, N11 item flags labelled an assumption.

## Rule taught
List tools run only when the item is NOT identified by ID (a description like "the watch" → list first; "S-50" → details directly). A list-first lookup on a typed ID wastes time and can miss a non-today shipment of the worker.

## D43 — Tool lists (the only "buttons" each agent has; CODE calls them, D37)
| Agent | Tool | Backed by | Notes |
|---|---|---|---|
| Customer | 1 my_recent_orders | Flask endpoint 1 | Clue matching on product names |
| Customer | 2 order_details(order_id) | Flask endpoint 2 | Also holds the returns list; a bare return_id is matched inside his recent orders' returns; no match → ask for the order ID (never "does not exist") |
| Customer | 3 check_eligibility(kind, record) | ⑤ (code) | kind = return / exchange / cancel; code passes ④'s validated record, never LLM arguments (D6); ⑤ also applies the holiday extensions and special-case structured values (audit #3) |
| Customer | 4 policy_search(query) | ⑥ | ACTIVE + Audience includes Customers + allow-list (POL-SPC-001, D47-a) |
| Worker | A my_shipments_today | Flask endpoint 3 | ⑤ access window + deny-list on EVERY row; cut to GDL-DTS-001 §2 shape (count / list / pending-completed) |
| Worker | B shipment_details(shipment_id, requested_fields) | Flask endpoint 4 | requested_fields = explicit enum checked by code against the deny-list (D35/D41); ⑤ access window |
| Worker | C procedure_search(query) | ⑥ | ACTIVE + Audience includes Delivery Workers |
- No handoff tool: ⑦ returns "needs handoff + reason", ⑪ calls ⑨ (D19).
- customer_id / assigned_worker_id are compared by ④ then stripped before results reach the LLM (D38, POL-PRV-001 §3).
- Worker query-type enum (Phase 4 exit, F2): includes "another worker's list / shipments", so a request like "give me 4413's list" (Q085) is mapped by the LLM to that value. It is counted as a resource denial (D41) only when code finds another worker's ID ("4413") word-for-word in the message; a name alone is never evidence (audit #13, N10). Otherwise the same neutral reply, not counted. The neutral replies use the D68 denial templates 16–17.

## Module ownership of handlers and templates (added, audit #11; denial recording added, N2)
Phase 3 D19 says the fallback and handoff paths never depend on the AI, and ⑪ renders templates. So:
- The **filtering and shaping** of tool results is library code below ⑦: ④ (response schemas, always-forbidden fields), ⑤ (access window, deny-list result, GDL-DTS-001 §2 shape).
- **Denial recording is part of that shared library (N2):** one function, called wherever a lookup is denied (backend 404 on a specific record, worker assignment mismatch, D35/D41 field and query denials), writes the sync audit event (D15) and returns the denial type. It is used by BOTH paths: the MCP handlers in ⑦ (now thin wrappers that call ④/⑤/⑥) and ⑪'s template path (Degraded status templates, the classify-failure fast path). So an attacker probing order IDs through a status template during a sale is counted exactly as on the agent path, and the third denial gives AUTH/P2 (D15).
- **⑪ owns** template rendering, the code classifier and the P1 pattern check. ⑪ calls ④ (template data, already allowed in the Phase 3 call table) and ⑤ directly, using the SAME shaping and denial functions as the handlers, so both paths filter and count identically (scenario S16) and the fallback path still works when ⑦ is down.
- Was (Phase 4 exit): "Degraded-mode templates are filled through these same tool handlers" — replaced by "through the same ④/⑤ shaping functions"; the intent (never a raw backend call) is unchanged. Was (round 1): "the MCP handlers … add the denial bookkeeping" — moved into the shared library (N2).

## Queued Degraded-mode jobs (added, audit #6; gaps closed, N5)
How the agent graph runs inside a job taken from the 3-minute Degraded queue (customers only; workers never queue, D16):
- **At enqueue (live request, inside the 8 s budget, D20):**
  - The P1 pattern check has already run (every mode).
  - Prefetch endpoint 2 (one order) when the message has a typed order ID (POL-AGV-001 §2 format) OR ③ already resolved the reference (an order selected earlier in this chat, or a bare "2" mapped by ③) — this keeps D20's "the order selected"; otherwise endpoint 1 (recent orders).
  - A prefetch 404 is a live denial (counted, Phase 3 "Queued messages and denials"): the user gets template 14 (customer) at once and nothing is queued; a third denial takes the AUTH/P2 path.
- **Inside the job:**
  - Backend data comes from the snapshot stored at enqueue; the handlers read the snapshot and make NO ④ call (CP-44: "④ is replaced by a reader of the stored snapshot").
  - No denial counting inside a queued job ("a data miss inside a queued job is never a denial").
  - A needed record missing from the snapshot (e.g. a return question with only endpoint-1 data) → the chat's merged deferred handoff (D28) is sent NOW with the collected context; no second ticket is opened. Later queued messages of that chat end HANDED_OFF, exactly as on the timeout path (Phase 3 D28).
  - ACTIVE policy version ids are resolved when the job starts, not at enqueue (POL-VER-001: answers use the version active now).
  - Job deadline = the earlier of the configured job deadline and the deferred handoff's due time (D28); numbers → Phase 5.
- A P1 in a later queued message follows the interim rule in Exit §6 (owner question).

## D44 — Missing data
- D25 is not changed in shape for orders/shipments, except the item flags below. Two cases:
  - A contract field that comes back null / inconsistent (e.g. Delivered without delivered_at) → POL-AGV-001 rules, P3 (POL-AGE-001 §2), migration note if order_date is before 2026-06-15 (POL-SPC-001 §8).
  - A field D25 never had → never guess (POL-AKU-001 §5, POL-AIS-001 §2.8): explain what is known + the policy's conditions, hand off per that policy's escalation clause; priority = owner question (POL-ESC-001 UNVERIFIED).
- Exchange stock (his choice): explain the conditions, hand off to CS to check stock (POL-EXC-001 §8). Cost accepted: every exchange question reaching the stock condition is a human case.
- **Item category and flags (revised, audit #23):** one field cannot hold both a product category and a sale label, because return windows depend on the product category (POL-RET-001 §2, e.g. electronics 15 days, standard goods 30) while Final Sale / Clearance is a label "at purchase" that applies across categories (§6). In the mock backend (which we own), each endpoint-2 item carries:
  - `category` = the product category (incl. `gift_card` / digital goods);
  - `sale_label` = none / final_sale / clearance (set at purchase);
  - `custom_made` = true / false;
  - `pre_order` = true / false.
  ⑤ uses them; hand off only when the data is really missing. Was (2026-10-15): category values `final_sale`, `gift_card`, `custom_made`, `pre_order` in one field — withdrawn.
  **ASSUMPTION (N11):** these flags assume the real NovaCart backend stores a sale label set at purchase and the custom-made / pre-order facts. BRD: the existing backend is not redesigned, so this is an owner question for the backend owner (Exit §6); until confirmed, a missing flag → hand off per D44's "field never had" rule, never a guess.
- Cancellation timestamps: Processing always goes to CS review (POL-CAN-001 §7), so no extra handoffs; ⑤ never substitutes last_updated for processing_started_at.

## D45 — Customer denials
- Customer tools return only his own data → no customer field enum.
- Another customer's order ID → backend 404 (or ④ customer_id mismatch) → same neutral reply, counted each (D32, D41), recorded by the shared denial function (N2). Format check first: a malformed ID is a clarification, not a denial (D15-j).
- A request for worker or internal data → neutral reply (C13), not counted (nothing reached a filter).

## D46 — MCP in V1 (his choice, for learning; my recommendation was "no MCP")
- One MCP server per role (customer tools / worker tools), owned by ⑦, running INSIDE the Gateway process with in-memory transport (no stdio, no HTTP, no new container — D10/D12 unchanged).
- The MCP client is the plan-executor code (D37), never the LLM.
- Handlers call ④/⑤/⑥ (④ stays the only door to Flask, D19); deny-list checks, shaping and denial recording live in the shared ④/⑤ library (audit #11, N2).
- Token and identity are server-side request context only — never in MCP messages, arguments or _meta, never logged (D2, D20).
- ⑪'s remaining deadline reaches the handlers; SDK default timeouts off (D27). Typed errors and denial types are preserved through isError (retries stay transient-only).
- Learning value recorded honestly: teaches tool schemas + list/call; not LLM-driven tool discovery or cross-process interop. Extra layer with no production job = accepted learning cost.

## D47-a — POL-SPC-001 customer allow-list (his approval)
- POL-SPC-001's Audience excludes Customers, but customers need its sections (holidays, promotions, damaged goods, delivered-not-received, migration, duplicates, gifts). It is added BY NAME to the customer retrieval allow-list. The filter is NOT widened to "AI Gateway" (that would expose internal engineering rules such as POL-AGE-001). Amends D34's customer filter. D66 check 2 accepts this by-name exception. (Name note: D47-a is a Step 3 decision; D47 in Step 4 is chunking — separate decisions.)

## Review log
- design-auditor on D43–D46: FAIL (fixable) → fixes applied (worker list access window per row; D44 split; D45 neutral mismatch + id stripping; return_id fallback; MCP guardrails). Two owner choices decided (POL-SPC-001 allow-list; category values). These two small additions will be re-checked in the first Step 4 review batch.
- Phase 4 exit (2026-10-16, approved): "another worker's list" enum value; Degraded templates use the tool handlers.
- Phase 3+4 cross-phase audit round 1 (2026-10-16): FAIL (errata) → applied: #6 queued-job rule; #11 shaping in ④/⑤, templates + code classifier + P1 check owned by ⑪; #13 evidence for query denials; #23 item flags.
- Round 2 (2026-10-17, his "موافق"): N2 shared denial recorder for both paths; N5 prefetch keeps ③-resolved orders, missing record → merged deferred handoff, prefetch 404 → template 14 at once; N10 worker id only; N11 item flags = assumption for the backend owner.
