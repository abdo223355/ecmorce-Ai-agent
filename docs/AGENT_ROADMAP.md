# Agent + RAG roadmap (عبدالرحمن's part)

Each step: what we build, which design doc to read first, what he writes himself, and how we know it
works. Claude Code explains the step first (real world → our Gateway), asks the design questions
one at a time, then builds with him. Order = from simple to hard.

## A0 — Setup (Claude Code does it; no questions — backend rule 2b in CLAUDE.md)
- Goal: run the stack with `docker compose up --build`, check /health, run the tests, and call
  one tool through /dev/tools.
- Claude Code: runs and fixes the setup itself. Then shows him, in a few lines, what the agent
  will receive from a tool: the ToolResult statuses, and why customer_id is never inside.
- He writes: nothing in A0.
- Done when: the stack is up, and he has seen one tool result. Then go to A1 (first teaching step).

## A1 — LLM adapter (the "model adapter", D27 / D100)
- Goal: one class that calls OpenRouter with a timeout = remaining time − margin (D92), returns
  structured output, and maps errors (429 / timeout / bad JSON) to typed errors.
- Read: docs/design/Phase4_Step8_Model_Cost.md (D71 model per node), Phase 5 D92.
- He writes: the interface (abstract base class) and decides sync vs async.
- Done when: a unit test with a fake LLM passes, and one real cheap call works.

## A2 — RAG ingestion (chunking + embeddings + pgvector)
- Goal:
  - load the policy PDFs;
  - split them by section (D47), with metadata: doc_id, version, status, audience, section;
  - embed the chunks and store them in pgvector (D48).
  - Index only user / worker audience docs plus the allow-list (D105).
- Read: docs/design/Phase4_Step4_RAG.md (D47–D53, D47-b), Phase 5 D105.
- He writes: the chunking rule and the chunk data class.
- Done when: every ACTIVE customer policy is in the table, and a SUPERSEDED or DRAFT doc is
  never returned.

## A3 — Retrieval (policy_search / procedure_search)
- Goal:
  - filter ACTIVE + Audience (+ the allow-list);
  - top-k 5;
  - keyword-only fallback when embeddings are down (D49);
  - return ToolResult with chunks.
- Read: Phase4_Step4_RAG.md (D51, D52), Phase 5 D94 / D114.
- He writes: the filter query and the fallback decision.
- Done when: a few L1 questions from EVL-RAG-001 return the expected doc in the top 5.

## A4 — State + graph skeleton (LangGraph)
- Goal: the per-request state (D38) and the graph shape:
  classify → safety gate → plan → reply → (validate is infrastructure).
  Nodes are stubs at first.
- Read: docs/design/Phase4_Step2_Agents.md (the graph, D36–D42).
- He writes: the State class (TypedDict or Pydantic — his choice, with reasons) and the edge
  functions.
- Done when: a fake message walks through the graph and the printed state is right at each node.

## A5 — Classify node
- Goal: structured output with:
  - intents + extracted arguments for the first 3 parts (D40, D93);
  - a safety flag and escalation flags for EVERY part (D42).
  - Classify failure → code classifier path (N8).
- Read: Phase4_AI_Design.md (C1–C14, W1–W9), Phase4_Step5_Prompts.md (D58), Phase 5 Step 5 fix 1
  (order_ref map).
- He writes: the output schema and the classify prompt text.
- Done when: about 15 sample messages (Arabic, Egyptian, Arabizi, English) classify correctly.

## A6 — Plan executor (customer agent)
- Goal: a fixed tool plan per intent, executed by code.
  - Example: C2 return → order_details → check_eligibility → policy_search.
  - Clarify when the order is ambiguous.
  - Handoff results.
- Read: Phase4_Step3_Tools.md (D43–D45), Phase4_AI_Design.md (per-intent plans).
- He writes: the intent → plan mapping (a data structure — he chooses which) and one plan.
- Done when: scenarios S1–S5 of docs/design/Phase4_Scenario_Tests.md behave as written.

## A7 — Worker agent
- Goal: W1–W9 with the worker tools.
  - Query enum (list / count / pending / completed).
  - Requested-field enum.
  - Denials (D41).
- Read: Phase4_Step3_Tools.md, Phase4_Step2_Agents.md D41.
- He writes: the worker plan mapping + the field enum mapping from the classify output.
- Done when: the worker scenarios pass (another worker's shipment → neutral denial).

## A8 — Reply node + placeholders
- Goal: one reply call for the System 2 parts (D73).
  - Numbers as placeholders (D60-A1).
  - Cited sections recorded for validate (D66 check 2).
- Read: Phase4_Step5_Prompts.md (D54–D60-A1), Phase4_Step7_Guardrails.md (D66, D68).
- He writes: the reply prompt and the citation format.
- Done when: replies never contain a raw number from policy text, and citations match the
  retrieved chunks.

## A9 — Agentic RAG round + judge+rewrite (bounded)
- Goal:
  - at most 1 extra retrieval round (D50, D94);
  - judge+rewrite on a scrubbed English query (Phase4_Step5 audit #15);
  - only when the turn stays under 5 s (Phase 5 fix 6).
- He writes: the "is the context enough?" decision.
- Done when: a temporal / multi-doc question improves, and the latency budget is respected.

## A10 — Memory cards (with the Redis store from Milestone 2)
- Goal: per-turn cards (D61), a code-built summary (D62), "why?" follow-ups re-fetch the cited
  section, lost-context rule (D65).
- Read: docs/design/Phase4_Step6_Memory.md.
- He writes: the card data class and the summary builder.
- Done when: a 3-turn conversation with a follow-up works.

## A11 — Integration
- Goal: run_agent() wired into /chat with:
  - the Milestone 2 guardrails (P1 check, PII scrub, D66 validate, templates);
  - the first eval run (Phase 8 layers L1 / L2 / L3 on a small set).
- Done when: the 17 design scenarios run end to end.
