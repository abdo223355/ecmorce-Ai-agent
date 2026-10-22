# Progress log (newest first)

## 2026-10-23 — GitHub repo connected (local only)
- Repo: https://github.com/abdo223355/ecmorce-Ai-agent (public; had one "Initial commit" with only README). Local git initialised in novacart-gateway, origin added, history aligned with origin/main. NOTHING committed or pushed yet.
- Added docs/process/ (BRD v1.2/v1.3, system analysis, phase 3 docs, phase 5 and 6 step files) and a README section "design first, then code" so the repo shows the work before the code.
- Checked: .env is ignored; no OpenRouter key pattern in the text files that would be added (docx files not scanned).
- Correction: a stray `merged_sections` field was briefly added to rag/models.py and removed again. Chunking is still WITHOUT merging short sections (his decision to merge was not implemented, he stopped that edit).
- Push is his to do (needs his GitHub login).

## 2026-10-22 (night) — A2 started: chunking written (rag/models.py, rag/chunking.py, tests/test_rag.py)
- He asked for overlap (small). Implemented as: last sentence of the previous piece, max 15 words, stored in Chunk.context_before and used ONLY in embed_text (not in the cited text). No overlap when the previous section ends with a table row.
- Rule per section: 1 numbered section = 1 chunk (D47). PROPOSALS (not in design): max 400 words per chunk then split at blank lines (longest real section = 308 words, so no split happens today); short sections (< 25 words, 20 of 185) are NOT merged. His decision on merging is still OPEN.
- audience tags parsed from the metadata block: customers / delivery_workers. Glossary is chunked as normal sections: one-chunk-per-row (D47) needs real table extraction, not done.
- Checked on the real corpus with pdftotext -layout: 31 PDFs, 185 chunks, section counts equal the table of contents in every file, no errors. Gateway tests: 32 passed.
- Not done: ingest (PDF reading, which docs to index, embeddings, pgvector). Note: container has no pdftotext, ingest must read PDFs another way (pypdf is on the host, not in requirements) and its text must be checked against this chunker.
- Open question (exact wording): "الأقسام القصيرة دي (51 من 200): تفضّل تسيبها منفصلة ولا تدمجها مع القسم اللي قبلها؟ ولازم تقول ليه."
- Next: his answer on short sections and the overlap value (15 words is my PROPOSAL, TODO(عبدالرحمن) in chunking.py), then ingest + embeddings + pgvector.

## 2026-10-22 (later) — A1 started: LLM adapter (in progress)
- Decisions by عبدالرحمن:
  - The adapter is async (reason not given yet; Claude's reason: LLM call is the slowest part, run_agent and Tools are already async).
  - Errors come back as a result object, option (ج), not exceptions (same pattern as ToolResult).
- Built so far (Claude): gateway/app/llm/__init__.py with LLMResult (status: ok / timeout / rate_limited / bad_output / unavailable) and the LLMAdapter ABC.
- UPDATE: عبدالرحمن said generate() needs no design, so Claude wrote all of A1: generate(prompt, schema: pydantic model, timeout_s, system=None) -> LLMResult; llm/errors.py (dict table), fake.py, openrouter.py (json_schema response_format, one call, no retry), config (OPENROUTER_API_KEY, LLM_MODEL, LLM_BASE_URL; no default model), tests/test_llm.py. Gateway tests: 18 passed (9 old + 9 new). NOT done: one real call (needs LLM_MODEL set in .env). The OOP question below is still open but optional now.
- UPDATE 2: model names moved from .env to gateway/app/llm/models.py (classify = openai/gpt-oss-20b, reply = anthropic/claude-haiku-5.5; env LLM_MODEL_<NODE> or LLM_MODEL overrides). Tests: 19 passed. Real call result: the adapter reached OpenRouter and returned auth_failed (403) because the API key has a $0 usage limit ("Key limit exceeded", limit 0 USD). Fix is on his side: raise the key limit in OpenRouter settings and make sure the account has credit. Then re-run the smoke test.
- UPDATE 3: LLM module finished. Agent code only needs: `from app.llm.client import ask` then `await ask("classify"|"reply", prompt, PydanticSchema, remaining_s=ctx.remaining_s, system=...)` -> LLMResult (D27 no retry). budget.py computes the timeout (D91 caps 1.0/2.0 s, D92 margin 0.5, minimum windows 0.8/1.5; below minimum no call is made and status=timeout reason=below_minimum_window). client.set_adapter(FakeAdapter(...)) for tests. Gateway tests: 21 passed. Still not verified live: the API key had limit 0 on the last check.
- UPDATE 4: first REAL calls succeeded (key limit now 2 USD). classify openai/gpt-oss-20b: ok, 2.44 s, 92 in / 146 out tokens. reply anthropic/claude-haiku-5.5: ok, 2.69 s. FINDING: both are slower than the design caps (classify 1.0 s, reply 2.0 s, D91), measured with a timeout of 8 s, one cold call each. With ask() they would time out today. To investigate in A5/A8 bake-off: warm connection, reasoning tokens of gpt-oss, other candidate models, a lower-latency provider setting.
- UPDATE 5 (speed test, 10 short classify-style calls per model, sequential, timeout 8 s, from his machine): gemma-3-12b-it p50 0.89 s / p95 2.01 s; haiku-5.5 p50 1.76 / p95 2.41; deepseek-v4-flash p50 1.64 / p95 2.72; gpt-oss-20b p50 1.88 / p95 4.21 (130 out tokens avg). All 10/10 valid JSON. Caps: classify 1.0 s, reply 2.0 s (D91). Only gemma is near the classify cap; none is safely under p95. Small sample, no quality check, not production network. Decision pending: classify model in llm/models.py.
- DECISION (عبدالرحمن): classify model = google/gemma-3-12b-it (was gpt-oss-20b). Cost: lower capability, accuracy on hard intents not measured yet. Re-check in A5 on real messages.
- Design constraint found: D27 "no live retry" — the adapter never re-sends a request; model name is config (D71); timeout = remaining time − margin (D92).
- .env created from .env.example (gitignored). OPENROUTER_API_KEY is set (format checked only, not tested live). The first key was pasted in chat by mistake, so it must be revoked on OpenRouter if not done yet.
- Planned files for A1 (proposal): llm/errors.py (his: status mapping, dict vs if/elif), llm/fake.py, llm/openrouter.py (his: _parse), config.py (model name, key, margin), tests/test_llm.py.
- His job now: write the generate() signature in LLMAdapter (async; prompt, schema, timeout_s; returns LLMResult). Marked TODO(عبدالرحمن) in the file.
- Open question (exact wording): "لو عندك class OpenRouterAdapter و class FakeAdapter للـ tests، وإنت عايز الـ nodes تشتغل مع الاتنين من غير ما تتغيّر. إيه الحاجة اللي لازم الاتنين يتفقوا عليها بالظبط؟ وإنت شايفها مكتوبة فين؟"
- Setup notes: host port for Postgres is 5433 (5432 is used by a local Windows Postgres). Stack is up via `docker compose up -d`; tests run in a throwaway container with a mount (they are not inside the images).
- He wants to write the OOP and data-structure parts himself; Claude only brainstorms and challenges.
- Next: review his generate() signature, then errors.py, fake.py, openrouter.py, tests, one real cheap call.


## 2026-10-22 — A0 done (setup)
- Stack up with `docker compose up --build -d`: postgres, redis, backend, gateway all healthy
  (containers: novacart-gateway-{postgres,redis,backend,gateway}-1).
- Fix: host port 5432 was taken by a local Windows Postgres, so docker-compose.yml now maps
  postgres to host 127.0.0.1:5433 (containers still talk on 5432 inside the network).
- /health = ok. Tests: gateway 9 passed, backend 8 passed. The tests are NOT inside the images,
  so we ran them with a temporary mount (see commands in the chat); host Python is 3.9, project needs 3.12.
- Tool smoke test: order_details NC-100007 with c-100003 token returned status ok, no customer_id in data.
- Decisions by عبدالرحمن: none in A0.
- Open question: none (A0 has no teaching questions). First A1 question not asked yet.
- Next: A1 — LLM adapter (docs/design/Phase4_Step8_Model_Cost.md D71 + Phase 5 D92 first).


## 2026-10-22 07:33 — his rule
- No teaching questions about backend / infrastructure code. Claude Code builds and fixes those parts itself and explains in 1–3 lines. Questions only for RAG + agents (CLAUDE.md §2b).

## 2026-10-22 — Milestone 1 delivered (from the design chat)
- Built:
  - NovaCart backend (Flask + PostgreSQL, 5 endpoints + login, JWT RS256 + JWKS).
  - Seed: 200 customers, 30 workers, ~1,000 orders, returns, shipments, plus hand-made policy edge
    cases in backend/SEED_SCENARIOS.md.
  - Gateway M1: token check with the JWKS rules of D88, backend client with the D83 retries, agent
    tools D43 with denials / access window / field enum, /chat stub, /dev/tools.
  - Docker Compose: postgres + pgvector, redis, backend, gateway.
- Tests: backend 8 passed, gateway 9 passed. Also smoke-tested against a real PostgreSQL 16.
- Work split agreed:
  - Claude builds the backend and infrastructure.
  - عبدالرحمن builds RAG + agents with Claude Code as tutor.
- Default for P1 check / PII scrub / D66 validate: built as infrastructure around his agent (he can
  change this).
- Open question for him (exact wording):
  "في كل خطوة، تحب أبدألك إزاي؟ (أ) هيكل الملف وإنت تملاه (ب) شرح المطلوب بس وإنت تكتب من الصفر
  (ج) مثال صغير شبه المطلوب" — superseded by his later choice: Claude Code writes ~70–80%, he writes
  ~20–30%.
- Next: roadmap step A0 (setup + warm-up).
