# Progress log (newest first)

## 2026-10-25 (night, later) — embedding latency: early embedding
- Measured INSIDE the gateway container (32 calls): query embedding p50 1.10 s, p95 1.17 s, first (cold) call 1.50 s. So about 75% of the 1.5 s RAG window (D91) before any search.
- DECISION (عبدالرحمن), option أ: early embedding. /chat starts embedding the user message when it arrives, in parallel with classify (BoundTools.prefetch_embedding); policy_search / procedure_search reuse it only when query is the exact same text; retrieve waits for it at most the RAG window (shield, then fallback); BoundTools.close() cancels an unused one. PREFETCH_TIMEOUT_S = 2.5 (classify cap 1.0 + window 1.5, PROPOSAL). Agent contract unchanged.
- Costs accepted: every message goes to the embedding vendor, also messages that need no policy (against data minimisation, D105). The ingress scrub (D107, M2) does not exist yet, so the text is NOT scrubbed: dev with synthetic data only (D111), must be fixed before go-live. Rejected for now: (ب) Redis cache (helps repeats only, repeat rate unknown), (ج) warm-up (only the first call), (د) faster model (voyage-4-lite: weaker Arabic 9/12, Arabizi 8/12).
- RESULT (container, simulated 1.0 s classify, 12 questions each): retrieval time after classify p50 1.11 s -> 0.12 s (max 1.51 s -> 0.19 s); no_retrieval 2/12 -> 0/12.
- Tests: 84 passed. Next: score gate from the eval set (keep raw cosine), commit.

## 2026-10-25 (night) — contract changed (option ب) and RAG wired into the agent tools
- DECISION (عبدالرحمن), option ب: policy_search(query, english_query=None) and procedure_search(query, english_query=None). query = scrubbed user text for the meaning search, english_query = English query from classify (D53) for the keyword search. Optional, so calls with query only keep working before A5. Rejected: (أ) one English text for both (a bad translation would break both searches), (ج) a SearchQuery object (extra class for two fields today).
- Wired: agent/__init__.py Tools protocol, main.py BoundTools._rag (audience from the token role; policy_search = customers only, procedure_search = workers only, else denied wrong_role), PolicyStore opened in the FastAPI lifespan (no wait: DB down -> unavailable, not a crash), /dev/tools/policy_search and procedure_search (?arg=...# Progress log (newest first)en=...). rag/__init__.py contract text updated.
- LIVE (gateway in Docker, real tokens): customer Arabic + English -> hybrid, POL-RET-001 §2 first; customer Arabizi only -> vector_only, PRC-MIS-001 §4 first; worker damaged parcel -> PRC-DMG-001 §4 first; worker calling policy_search -> denied wrong_role. Total latency 1.05-1.36 s, no embedding timeout in this run.
- Note for the score gate (D114): RRF scores (~0.016) are rank-based, not similarity. The gate will need the raw cosine score kept in the result.
- Tests: 80 passed. Next: latency (p95 of query embedding, query-embedding cache), score gate from the eval set, commit.

## 2026-10-25 (later) — A3: retrieve.py written (his fallback part still TODO)
- retrieve.search(question, audience, deadline, store, embedder, english_query=None) -> ToolResult: window = min(1.5 s D91, remaining - 2.2 s reserve); embed_query and keyword search run in parallel; vector search; Reciprocal Rank Fusion (PROPOSAL, RRF_K=60; design says "fused score" without a method); top 5 (D94); customer allow-list POL-SPC-001 (D47-a); DB errors -> ToolResult unavailable. No score gate yet (D114: from evals).
- Keyword search fixed: any word may match (OR), more matches rank higher. "return window shirt" now finds Return Window.
- DECISION (عبدالرحمن), option ب: Strategy pattern. FallbackPolicy (ABC, apply(embed, keyword_hits) -> FallbackOutcome) with KeywordOnlyFallback (an English query exists: return keyword hits marked mode=keyword_only) and NoAnswerFallback (no English query: return [] with mode=no_retrieval so the agent hands off). choose_fallback(english_query) picks. Same principle applied to the normal path: no English query -> no keyword search at all (mode=vector_only), to avoid chance matches of English words in Arabic text. Cost accepted: until classify gives the English query (A5), an embedding timeout on any question means a handoff. Claude wrote the code to his design; the earlier "he writes on_embedding_failure" plan was replaced by this.
- REAL EVENT: first live run hit the fallback: embed_query timed out at the 1.5 s window on a cold connection. Measured 10 calls: 1 timeout (the first, cold), the rest 0.44-1.31 s, so a warm call still uses most of the RAG window.
- Tests: 72 passed (host venv, real pgvector).
- Not done: wiring policy_search / procedure_search in main.py BoundTools (needs the contract decision: one query text or two).
- Second live run (after option ب): ALL 3 queries hit the embedding timeout at 1.5 s and went keyword_only. Results: return question -> POL-RET-001 §2 first (right); worker damage -> PRC-DMG-001 (right doc, §2 before §4); Arabizi missing parcel -> POL-CAN-001 first, the right PRC-MIS-001 second (keyword-only is weaker, as expected). Embedding latency vs the 1.5 s window is now the main RAG risk (1 of 10 timeouts in one run, 3 of 3 in another).
- Tests: 76 passed.
- Next: contract decision (Tools.policy_search: one text or two), wiring in main.py, then the latency problem (measure p95, consider a query-embedding cache).

## 2026-10-25 — A3 started (explanation + first question), RAG report PDF
- Made D:ecmorce Ai agentRAG_Design_Report.pdf (6 pages, outside the repo): RAG steps so far vs BRD v1.3 FR-01..FR-14 and design decisions D47..D114.
- .claude/launch.json at the session root (D:ecmorce Ai agent.claude) with gateway :8080 and backend :8000 in attach mode (no command: Docker owns the ports).
- A3 explained. Found a contract gap to decide WITH him: Tools.policy_search(query) takes ONE text, but D51/D53 need two (the scrubbed original for vector search + the English search query from classify for full-text).
- His answer to the fallback question: "use semantic search; the LLM translates the request, embeds it and searches via the agentic RAG". Graded WEAK: semantic search needs the embedding call, which is exactly what failed in the scenario; an extra LLM translation adds latency; the agentic round (D50) is for weak scores, not for a failed provider; D49 says keyword-only when the embedding provider is down. Correct answer NOT given yet (he did not ask for it), he ended the session.
- Open question (exact wording): "عميل سأل: \"عندي كام يوم أرجّع القميص؟\". embed_query() رجّع timeout بعد 1.2 ثانية. retrieve.py يعمل إيه في الحالة دي بالظبط، وليه؟ فكّر في 3 حاجات: هل نعيد المحاولة؟ نستخدم أنهي بحث بداله؟ ونقول للـ agent إيه عن جودة النتيجة؟"
- Next: his revised answer, then the contract decision (one query or two), then build retrieve.py + wire policy_search / procedure_search in main.py BoundTools.

## 2026-10-24 — store.py started (explanation only) + sliding window for long sections
- Explained D48 for store.py: version status lives ONCE in policy_versions, chunks point to it by version_id, search JOINs them (no drift). His question answered by Claude (he asked "جاوب"). No store code yet; gateway has no DB driver yet (psycopg + pgvector to add).
- DECISION (عبدالرحمن): sections longer than MAX_WORDS (400) are cut with a SLIDING WINDOW of 400 words, overlap 50 words (PROPOSAL, TODO(عبدالرحمن) WINDOW_OVERLAP_WORDS), replacing the paragraph split. Same section, so citation is unchanged; windows after the first get no context_before. Real corpus unchanged: 185 chunks, no section above 400 words today.
- Tests: chunking 12 passed (scratchpad venv, Docker Desktop did not start in time). Full gateway suite NOT re-run after this change.
- store.py WRITTEN: policy_versions (status + audience live ONLY here) and policy_chunks (vector(768), generated English tsvector + GIN index, UNIQUE(version_id, section, part)); replace_version() = one transaction (upsert version, delete its chunks, insert, indexing_status DONE); set_status() = one row; search_vectors() (cosine, JOIN filter ACTIVE + DONE + audience or by-name allow-list, same embedding_model_id) and search_keywords() (websearch_to_tsquery english, ts_rank_cd). Own pool with statement_timeout (RAG_STATEMENT_TIMEOUT_MS = 1000, PROPOSAL). No vector index yet (exact scan on ~130 chunks; HNSW later, 768 < 2000).
- Deps added: psycopg[binary]==3.3.6, psycopg-pool==3.3.3. tests/conftest.py sets the Windows selector event loop (psycopg async cannot use ProactorEventLoop on a Windows host).
- Tests (host, Python 3.10 scratch venv): 47 passed, 8 SKIPPED. The 8 skipped are the store integration tests (drift, transaction rollback, audience, allow-list, model filter, keywords): NOT verified yet because Docker Desktop did not start today.
- VERIFIED 2026-10-24: store integration tests pass against the real pgvector (host: 11 passed; inside the rebuilt Linux gateway image: full suite 55 passed, 0 skipped). Gateway image rebuilt with psycopg; /health ok. Test schemas are dropped after each test (0 left).
- ingest.py WRITTEN and RUN (from his machine: corpus is outside the repo and pdftotext is only on the host; running it in the container would need poppler-utils + a corpus mount = infra change, not done). Rules: ACTIVE + Customers/Delivery Workers audience only; Evaluation/Adversarial folders never read; NEVER_INDEX = POL-AIS-001, POL-AGE-001, POL-AKU-001, POL-VER-001; SUPERSEDED/DRAFT already in the store get set_status; two ACTIVE versions of one doc = index neither; embedding retried 3x (offline job only, PROPOSAL); --dry-run.
- Result: indexed 20 docs / 129 chunks, skipped 12 (4 SUPERSEDED/DRAFT, 4 internal, 4 without a user audience: POL-COM-001, REF-GLO-001, POL-BDR-001, POL-AGV-001). Store: ACTIVE 20 versions / 129 chunks.
- Real search check: Arabic return question -> POL-RET-001 §2 first; Arabizi missing parcel (customer) -> PRC-MIS-001 first but only 0.002 above an unrelated chunk; worker damaged parcel (Arabic) -> PRC-DMG-001 §4 first. Query embedding 1.1-1.9 s (budget risk stays).
- FINDINGS for A3: (1) keyword search uses websearch_to_tsquery = all words must match, so "return window shirt" missed the Return Window section (no "shirt" in it): needs OR-style matching. (2) some section titles absorb a table header from -layout text ("Examples Result", "Outcome Handling Required Behavior"): chunker title bug, cosmetic for search, matters for display.
- Tests: 63 passed (host venv, DB up). Next: A3 retrieve.py.

## 2026-10-23 (night) — embedding model test (36 queries: 12 EVL-RAG-001 single-document questions x English / Egyptian Arabic / Arabizi)
- Setup: 129 chunks from 20 ACTIVE docs with customers or delivery_workers audience; metric = expected document in the top-5 chunks (document level, not section). Arabic and Arabizi versions were written by Claude, not taken from the eval set. Small sample, one run.
- hit@5 en / ar / arabizi: gemini-embedding-001 12/12 / 12/12 / 12/12 (MRR ar 0.90, arabizi 0.81, query p50 0.77 s, dim 3072); bge-m3 12 / 10 / 7; text-embedding-3-small 12 / 10 / 6; voyage-4-lite 12 / 9 / 8; multilingual-e5-large (with query:/passage: prefixes) 11 / 11 / 4; qwen3-embedding-4b 12 / 10 of 11 / 6 (p50 2.48 s, 1 failure); bge-base-en-v1.5 (English-only baseline) 12 / 4 / 8; qwen3-embedding-8b timed out twice (240 s).
- Caveats: gemini dim 3072 is above the pgvector index limit (2000 for vector) — D49 requires checking; with 129 chunks an exact scan needs no index, or reduce dimensions. Query embedding p50 0.77 s is half of the 1.5 s backend+RAG budget (D91), measured from his machine. Vendor retention not verified (D111).
- DECISION (عبدالرحمن): EMBEDDING_MODEL = google/gemini-embedding-001 (set in llm/models.py). No prefixes needed (QUERY_PREFIX / DOCUMENT_PREFIX stay empty, tested without). Open: 3072 dimensions vs pgvector index limit, vendor retention (D111), query latency 0.77 s vs the 1.5 s budget.
- Dimension problem (3072 > 2000): the API accepts `dimensions` (tested 768, 1536). Added OpenRouterEmbedder(dimensions=...) and env EMBED_DIMENSIONS (0 = full size). pgvector in the container is 0.8.7 (halfvec exists). Test on 36 queries, document in top 5: 1536 -> 34/36, 768 -> 35/36, 512 -> 36/36 (3072 gave 36/36 earlier but timed out twice at 240 s in the second round: provider variance or large payload). Differences are 1 question, so inside noise. Query p50 was 1.1-1.2 s in these runs (0.77 s in the first run): the 1.5 s budget (D91) is at risk, measure again before relying on it. Decision pending: which size to store.
- DECISION (عبدالرحمن): store 768 dimensions (EMBEDDING_DIMENSIONS = 768 in llm/models.py; EMBED_DIMENSIONS env overrides). The store column must be vector(768); changing it later means re-embedding every chunk.
- CORRECTION: the embedding timeouts seen in the model and dimension tests (e5, qwen3-8b, 3072, 512) were NOT provider flakiness. httpx.AsyncClient() has a hidden 5 s default timeout that cut long calls before our own deadline; the test scripts and the adapters used it. Fixed: adapters and client.py now use httpx.AsyncClient(timeout=None) (deadline = asyncio.wait_for only), plus a regression test. Re-run after the fix: gemini at 768 = 35/36 again (same as before); qwen3-embedding-8b at 768 = 30/36 (ar 10, arabizi 8), e5 unchanged 26/36. The 3072 size was not re-tested (decision already 768). Query latency p50 about 1.2 s, p95 about 3 s from his machine: still above what the 1.5 s budget (D91) allows, measure again and consider a query cache.

## 2026-10-23 (later) — A2: embedding adapter written
- Decision (عبدالرحمن): two methods, embed_documents() and embed_query(). Reason not given; Claude's reason: model-specific prefixes stay inside the adapter.
- Built: rag/embeddings.py (EmbedResult, EmbeddingAdapter, OpenRouterEmbedder with batching of 32, unit-length vectors so one metric = cosine, FakeEmbedder), tests/test_embeddings.py. Gateway tests: 41 passed. No real call made yet.
- Embedding model NOT chosen: EMBEDDING_MODEL in llm/models.py is empty on purpose (env EMBED_MODEL overrides). Needs a multilingual test: English documents vs Arabic / Arabizi questions. Also check each candidate token limit (many listed models have a 512-token context; our MAX_WORDS=400 cap may exceed it).
- TODO(عبدالرحمن): QUERY_PREFIX / DOCUMENT_PREFIX in embeddings.py, depend on the chosen model.
- Still open: merge of short sections (not implemented). Next: pick the embedding model by test, then rag/store.py (pgvector) and rag/ingest.py.

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
