# NovaCart — Adaptive AI Gateway

An AI support gateway for a fictional e-commerce company (NovaCart). Customers and delivery workers
chat with it. It answers from live backend data and company policies (RAG), applies the rules in
code, and hands off to humans when it should.

Learning + portfolio project. The full design (decisions D1–D160) is in `docs/design/`.

## How it was built: design first, then code
This is not "vibe coding". The system was analysed, designed and reviewed in phases before any
implementation. Every phase has written artifacts, and the decisions are numbered (D1–D160) so code
and tests can point back to them (for example D27 "no live retry" in the LLM adapter).

| Phase | What was done | Where |
|---|---|---|
| 1. Business | Business requirements (v1.2 → v1.3) | `docs/process/1-business/` |
| 2. System analysis | Actors, flows, requirements | `docs/process/2-system-analysis/` |
| 3. Architecture | System context, containers, quality attributes, audit | `docs/process/3-architecture/`, `docs/design/Phase3_*` |
| 4. AI design | Agents, tools, RAG, prompts, memory, guardrails, model/cost, evaluation, scenario tests | `docs/design/Phase4_*` |
| 5. Reliability and safety | Resilience, latency budget, data safety, eval thresholds, go-live readiness | `docs/design/Phase5_*`, `docs/process/5-reliability-and-safety/` |
| 6. Production | Deployment, MLOps decisions | `docs/design/Phase6_*`, `docs/process/6-production/` |
| 7. Implementation | In progress (see below) | `backend/`, `gateway/` |
| 8–9. Testing and optimization | Not started | |

Working method for the AI part: small steps, each ending with something that runs (`docs/AGENT_ROADMAP.md`),
and a session log of what was decided and what is still open (`docs/PROGRESS.md`). Measured choices are
recorded with their numbers, for example the model speed test in `docs/PROGRESS.md`.

Implementation status: backend, Gateway infrastructure and agent tools (Milestone 1); LLM adapter with
per-node model and latency budget; RAG chunking. Not built yet: embeddings and pgvector store, retrieval,
the LangGraph agents, memory, evaluation runs.

## What is in Milestone 1
- **backend/** — the "existing" NovaCart backend:
  - Flask + PostgreSQL, JWT (RS256) login + JWKS, and 4 data endpoints.
  - Realistic synthetic data, with hand-made policy edge cases (`backend/SEED_SCENARIOS.md`).
- **gateway/** — FastAPI Gateway:
  - token verification;
  - backend client (retries inside the 8 s budget);
  - agent tools: recent orders, order details, today's shipments, shipment details (with denials,
    access window and field allow-list);
  - the contracts for the agent and the RAG (the next part to build).
- **docker-compose.yml** — postgres (+pgvector), redis, backend, gateway.

## Run
```
cp .env.example .env          # add your OpenRouter key later (agent steps)
docker compose up --build
```
- Backend: http://localhost:8000/health · Gateway: http://localhost:8080/health

## Demo accounts
- Password for all demo accounts: `NovaCart#2026` (demo only).
- Customers: `c-100001` … `c-100010`. Workers: `w-2001` … `w-2005`.
- What each account is good for: `backend/SEED_SCENARIOS.md`. Inside Docker, the file is
  regenerated for the day of the seed in the `backend_keys` volume.

## Try it
```
curl -s -X POST localhost:8000/auth/login -H "content-type: application/json" \
     -d '{"username":"c-100003","password":"NovaCart#2026"}'
curl -s "localhost:8080/dev/tools/order_details?arg=NC-100007" -H "Authorization: Bearer <token>"
```

## Tests
```
cd backend && pip install -r requirements.txt && pytest -q
cd gateway && pip install -r requirements.txt && pytest -q
```

## Working with Claude Code
Open this folder in Claude Code. It reads `CLAUDE.md` automatically. Paste the prompt from
`docs/START_PROMPT.md` in the first session.
