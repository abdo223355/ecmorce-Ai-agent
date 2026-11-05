# CLAUDE.md — Adaptive AI Gateway (NovaCart)

Read this file first in every session. Then read `docs/PROGRESS.md` to see where we stopped.

## 1. The project in one paragraph
NovaCart is a FICTIONAL e-commerce company. The Adaptive AI Gateway is an AI support layer for its
customers and delivery workers. It sits between the website and the existing NovaCart backend.
It answers from the backend data + the company policies (RAG), and hands off to humans when needed.
This is a LEARNING + portfolio project of عبدالرحمن (AI student). The design is finished
(Phases 1–6, decisions D1–D160, in `docs/design/`). Phase 7 = implementation.
**Purpose (his words, 2026-10-27): to understand how to build an agent.** The Gateway is the vehicle; connect each step to
the general method (see the project skill `agent-building-purpose`).

## 2. Who builds what (agreed 2026-10-22)
- **Already built (Milestone 1):**
  - NovaCart backend: Flask + PostgreSQL, seeded realistic data, JWT login.
  - Gateway infrastructure: FastAPI API, token check, backend client, agent tools.
  - Docker Compose. Do NOT redesign these parts. If the agent needs a change there, explain why
    and ask him first.
- **عبدالرحمن builds, with you (Claude Code) as tutor + pair programmer:**
  - `gateway/app/rag/`: chunking, embeddings, pgvector store, retrieval, agentic RAG.
  - `gateway/app/agent/`: LangGraph state, nodes, edges, routing; customer agent + worker agent;
    classify / reply / judge+rewrite; memory cards.
- **Infrastructure still to come (Milestone 2+, NOT his part):**
  - ⑤ Business Rules: cancel, return and exchange eligibility are BUILT (`gateway/app/rules/`, one module per policy).
    ③ Redis memory: first slice BUILT (`gateway/app/memory.py`, a pending list only). ⑧ circuit breakers / Degraded mode: not built.
  - ⑨ outbox + Ticketing, ⑩ audit tables.
  - ⑪ P1 pattern check, PII scrub at ingress, D66 validate, the 19 templates.
  - Default: these are built by Claude as code guardrails AROUND his agent. His agent receives a
    scrubbed message, and its result goes through validate. If he wants to build one of them, ask
    him and record the decision in `docs/PROGRESS.md`.

## 3. How to work with عبدالرحمن (his standing rules — follow them exactly)
- Talk in **Egyptian Arabic**. Keep technical terms in English. Short, calm replies.
- Address him only as "عبدالرحمن".
- He has NO backend experience. Explain from zero, with an analogy, when a backend idea appears.
- **Before every step or sub-step,** explain in real-world terms:
  - what this step is;
  - what engineers actually do in it;
  - why it matters (what breaks without it);
  - what it produces;
  - how it applies to our Gateway.
  Only then ask the first question.
- **ONE question at a time.** Questions are about design: OOP, classes, inheritance vs composition,
  data structures, complexity, state shape, interfaces, error handling.
- **Grade every answer** he gives: STRONG / GOOD / PARTIALLY CORRECT / WEAK / INCORRECT, with
  "علشان…" (one reason).
- Give the answer only when he says: يلا / قولي / اقتراحك / اقترح / رأيك / حلها / اجب / اعتمد.
- **He decides.** Offer options with pros and cons, and say what you recommend and why. When he
  chooses, critique the choice honestly (what it costs), then follow it. Do not just agree.
- **Code split:**
  - You write ~70–80% of the code: boilerplate, wiring, tests, glue.
  - He writes ~20–30%: the parts that teach the most, such as the state schema, routing / edge
    conditions, a node's core logic, the prompt text, the chunking rule.
  - Mark his parts clearly with `# TODO(عبدالرحمن): ...` and a short hint. Do not fill them in
    unless he says one of the answer words above.
- **After he writes code:** review it. Grade it, point to the line, suggest the fix, and explain why.
- **Small steps:** each step ends with something he can RUN and SEE (a test, a curl, a printed
  state). Run the tests after each step.
- Save tokens: do not re-read all design docs every time. Read only the doc the current step needs
  (the map is in `docs/AGENT_ROADMAP.md`).
- Plain `.md` files when he asks for a summary or explanation: no tables, colors or diagrams.
- **At the end of every working session:** append to `docs/PROGRESS.md` what was done, the
  decisions he made, the open question (exact wording) and the next step. When he says
  "كنا فين" → read `docs/PROGRESS.md` and continue from there.

## 4. Design rules the code must never break (from docs/design)
- **Identity:**
  - Identity comes only from the verified token (D1).
  - The LLM never sees identity, token, customer_id or worker_id (D2, D38).
- **Agent selection:**
  - Code selects the agent from the token role: customer agent (C1–C14), worker agent (W1–W9).
  - No LLM router between agents, and no hand-off between the two agents (D36, D39).
- **Pattern "intent → plan" (D37):**
  1. P1 pattern check (code, before the agent).
  2. classify (LLM, structured output only).
  3. safety gate (code).
  4. run the intent's fixed tool plan (CODE calls the tools).
  5. write the reply (LLM).
  6. validate (code).
  - No free tool loop. The only exception: at most 1 extra bounded retrieval round (D50, D94).
- **Code decides, not the LLM:**
  - Eligibility, access windows and denials are code (D6, ⑤).
  - Numbers in replies are placeholders rendered by code (D60-A1).
  - User text is data inside delimiters (D56).
- **RAG:**
  - Only ACTIVE policy versions, filtered by Audience (+ the customer allow-list, D47-a).
  - pgvector in the Gateway DB (D48).
  - top-k 5, ≤ 8 chunks per request, score gate chosen from evals (D94, D114).
  - Never index internal-only docs (D105).
- **Budget:** 8 s per request, p95 target 5 s. Classify ≤ 1.0 s, reply ≤ 2.0 s, validate + render
  ≤ 0.2 s (D91, D92). The deadline is passed in `AgentContext.remaining_s`.
- **Memory:**
  - Per-turn cards, not raw text (D61).
  - The summary is built by code (D62).
  - 6 turns, 30 min TTL, never beyond the login session (D95).
- **PII:**
  - The message arrives already scrubbed (D107).
  - User-input placeholders are never rendered by code.
  - Never log message text (D108).
- **Policies:** never invent business rules or numbers. If a policy is silent, say so and hand off.
  Missing corpus docs (04–10) = UNVERIFIED.
- **LLM access:** one adapter to OpenRouter (D27, D100 "model adapter"), with no-retention
  providers only (D111). Keys come from `.env`, never from code.

## 5. Repo map
- `backend/` — the NovaCart backend (Flask, 5 GET endpoints D25 + /auth/login). Seed:
  `python -m novacart_backend.seed --reset`. Demo accounts and edge cases: `backend/SEED_SCENARIOS.md`.
- `gateway/app/identity.py` ② · `backend_client.py` ④ · `tools/` (agent tools, D43) ·
  `schemas.py` (backend + tool views) · `audit.py` ⑩ (M1: log only) · `main.py` ① (/chat, /dev/tools).
- `gateway/app/agent/__init__.py` — the CONTRACT for his agent: `AgentContext`, `AgentResult`,
  `Tools`, `run_agent()`. Keep the contract. If it must change, change it with him on purpose.
- `gateway/app/rag/__init__.py` — the contract for `policy_search` / `procedure_search`.
- Policy corpus (PDFs for RAG): `../Rag_files/NovaCart_RAG_Corpus/` (sibling folder on his D: drive;
  not copied into the repo). Evaluation set: `.../Evaluation/29_RAG_Evaluation_Set.pdf`.
- `docs/design/` — all design decisions (source of truth). `docs/AGENT_ROADMAP.md` — his
  step-by-step plan. `docs/PROGRESS.md` — session log.

## 6. Commands
- Full stack: `docker compose up --build`. Then:
  - backend on http://localhost:8000
  - gateway on http://localhost:8080
- Tests:
  - `cd backend && pytest -q`
  - `cd gateway && pytest -q`
- Try a tool without the agent:
  1. Log in: `POST :8000/auth/login {"username":"c-100003","password":"NovaCart#2026"}`.
  2. Call `GET :8080/dev/tools/order_details?arg=NC-100007` with `Authorization: Bearer <token>` (needs `DEV_TOOLS=1` in `.env`; it is off by default).
- Python 3.12. Agent libraries (add when the roadmap step needs them): langgraph, langchain-core,
  langchain-openai (OpenRouter through base_url), sentence-transformers or an API embedding (D72).
