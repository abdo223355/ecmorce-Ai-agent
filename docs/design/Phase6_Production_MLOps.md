# Phase 6 — Production / MLOps (Adaptive AI Gateway, NovaCart)

Status: CLOSED 2026-10-21 17:55 (D130–D160 + review fixes + final cross-step review). Started 2026-10-19 14:18 (his "يلا بينا"). Phase 6 turns the design into a system that can be deployed, observed, released and operated. Code = Phase 7; running the evals = Phase 8. Phases 3–5 (D1–D129 + reconciliation) are constraints. Guiding rule from him (2026-10-19): learning first, portfolio second — no enterprise over-engineering; every choice needs a clear reason.

## Input (handover from Phase 5, D128 + final review fix 9)
Load test D98 and sizing (Redis, queue, Worker rate, DB pools) · monitors / alerts D117 + D85 · runbooks D124 · rollout / kill-switch / code-only flags (flags in Gateway DB) · release pipeline + rollback D122 (schema backward-compatible one release) · secret manager, encryption, backups, retention D109–D110 · Ticketing contract tests (blockers 1, 2, 8) · Worker auto-restart (R9) · edge rate limits (T5b) · NTP (D89) · vendor no-retention settings (T6) · website "AI off" status in D28.

## Roadmap (estimate; may change; numbering continues from D130)
1. Deployment topology & environments — where it runs, dev / staging / prod, containers, config and secrets (≈ 5).
2. Release pipeline (CI/CD) — build, eval gate in CI (D122), versioning of prompts / models / config / P1 list, flags and staged rollout, migrations, rollback (≈ 6).
3. Observability — logs, metrics, traces, LLM tracing and cost, dashboards for D117 / D85, alert routing (≈ 6).
4. Load test execution — tool, mock LLM / backend / Ticketing, scenarios of D98, sizing outputs (≈ 4).
5. Operations — runbooks D124, on-call for a solo project, backups and restore drill, Worker auto-restart, NTP, edge limits (≈ 4).
6. LLMOps lifecycle — prompt / model registry, scheduled eval runs, drift and quality monitoring, feedback loop, policy re-index pipeline (≈ 5).
7. Exit checklist.
Total ≈ 30.

## ALL STEPS APPROVED in one batch (2026-10-21 17:27, his "ok agree" on Phase6_All_Steps.md; he asked for all steps in one file instead of the step-by-step question). Numbers = design choices.

### Step 1 — Deployment topology & environments
- **D130 Where it runs:** Docker Compose on one host (his laptop for dev; one small VM for an optional online demo); 2 Gateway instances behind nginx to prove statelessness (D11). Not Kubernetes (too heavy for one person / 16 GB; teaches little about the Gateway). Lost: full auto-scaling / self-healing, partly replaced by restart policies + healthchecks (D154).
- **D131 Environments:** dev (laptop, mocks for backend / Ticketing / website; LLM mock or a cheap OpenRouter model) · staging (same Compose with prod-like config, fake corpus, mock vendors, run in CI) · demo (optional VM, synthetic data only; ASSUMPTION: the demo is not real NovaCart, so blocker 7 does not apply to it; real go-live stays blocked until blockers 1–8 clear, D119).
- **D132 Containers:** one image for Gateway and Worker (different command); pinned versions; non-root; liveness + readiness endpoints; mocks as separate containers (Flask backend; Ticketing with 4xx / 5xx / slow modes; website; LLM with 429 / slow / bad-output modes); official Redis and PostgreSQL + pgvector images.
- **D133 Config & secrets:** behaviour config (P1 list, templates, thresholds, model + route) as versioned files in git; environment differences as env vars; secrets: .env never committed (dev), Docker secrets (demo, design choice) = the simple form of D110's secret manager; secret scanning in CI.
- **D134 Network & edge:** nginx in front = load balancer + TLS (Let's Encrypt on the demo) + edge rate limit (T5b); only nginx is exposed; Redis and PostgreSQL on an internal network.

### Step 2 — Release pipeline (CI/CD)
- **D135 CI:** GitHub Actions on every PR: lint, type check, unit tests, image build, secret scan, dependency scan.
- **D136 Eval gate:** every PR = deterministic code checks + an L3 smoke subset (cheap model or mock); every release tag = full eval (D80; L1 / L2 / L3, ×3 runs per D113) with the Phase 5 Step 6 gates; any hard-gate failure stops the release; a cost cap per eval run set by him (design choice).
- **D137 Versioning:** code (git tag, semver), prompts (files with ids), model + route, P1 list, templates, config; every audited reply records these versions (D77).
- **D138 Flags:** table in the Gateway DB + short local cache (Phase 5 final fix 7): ai_enabled (kill switch), rollout_percent per role, code_only_mode, shadow_mode; changed only by the ops role (CLI or CS Console), audited + alert; unreadable → AI off.
- **D139 Migrations:** Alembic, expand / contract, schema backward-compatible for one release (D122); migration runs as its own job before the deploy.
- **D140 Deploy & rollback:** pull new image tag → migrate → rolling restart of Gateway instances one at a time; rollback = previous tag; policies use the D99 hold, never rollback; emergency path for the P1 list (L3 + P1 sets, faster stages, Security & AI Governance sign-off).

### Step 3 — Observability
- **D141 Stack:** Prometheus + Grafana + Loki in Compose; per-node timings as metric histograms instead of distributed tracing; OpenTelemetry / Tempo optional in Phase 9.
- **D142 Logs:** JSON with request_id + versions, no PII or message text (D108), stdout → Loki.
- **D143 Metrics:** p95 per node and per request; D66 failure rate, circuit states, Degraded on/off; queue length, oldest PENDING (P1 separate), FAILED count; invalid-token rate, JWKS refreshes, rate-limit rejections; Redis memory / evictions, DB pool wait; over-mask rate, weekly false P1; daily cost.
- **D144 LLM observability & cost:** one row per LLM call in our own table (model, route, tokens, latency, cost, versions, D66 pass / fail; no message text), shown in Grafana; Langfuse self-hosted optional later.
- **D145 Dashboards:** Health · AI quality · Queue / Outbox.
- **D146 Alerts:** Grafana alerting to one channel (Telegram or email — his choice); immediate = P1-related, PII, circuit open, Worker down; the rest in a daily digest; every alert links its runbook (D124); Worker watched from outside with a dead man's switch (D87).

### Step 4 — Load-test execution
- **D147 Tool:** Locust (Python, one language for the project).
- **D148 Mocks:** never a real vendor in load tests (cost, T6); controllable mock LLM (latency, 429 share, bad-output share for R10) and mock Ticketing (slow, 5xx, 4xx for R3 / R3b).
- **D149 Where / how big:** normal scenario (20–50 users) fully on the laptop; peak either on a temporary VM or scaled down with the ratio written next to the result (ASSUMPTION); all D98 scenarios + shared-IP polling + code-only.
- **D150 Outputs:** sizing report (Redis maxmemory, queue size, Worker rate, DB pools, re-tuned Degraded / circuit numbers, R5 acceptance) recorded as evidence for the go / no-go (D119).

### Step 5 — Operations
- **D151 Runbooks:** markdown files in the repo (runbooks/), one per D124 item: signal, check, action, rollback, owner.
- **D152 On-call:** he is on-call (one person); only immediate alerts wake him; the rest in the daily digest; demo support hours written in the README.
- **D153 Backups:** daily encrypted pg_dump of the Gateway DB stored off the host + policy PDFs (D23); restore drill before every important release, recorded as evidence; real RPO / RTO = owner (D125); demo values RPO 24 h, RTO 1 h (design choice, learning only).
- **D154 Basic self-healing:** restart policy unless-stopped + healthchecks for Gateway and Worker (closes Worker auto-restart, R9); NTP on the host (D89); edge rate limit in nginx (D134).

### Step 6 — LLMOps
- **D155 Prompt / model registry:** in git as files with ids; no separate registry tool; every change via PR + release gate (D122).
- **D156 Scheduled evals:** nightly canary of ~20 cases (design choice) to catch silent provider changes (R10); weekly full L3; full eval on every change; cost cap set by him (D136).
- **D157 Quality monitoring & feedback:** weekly review of D66 failures, handoff rate per intent, false P1, over-mask; review of a small sample of scrubbed conversations only, retention = owner (D109); a customer 👍/👎 button needs the website owner's agreement (owner question); every real failure becomes a new test case.
- **D158 Policy re-index:** on activation the Worker embeds the sections (D49) with visible indexing status; an embedding-model change → full re-index into a new index, L1 run on it, one atomic switch (blue / green), old index kept until confirmed.
- **D159 Cost control:** daily cost limit with an alert (value set by him, design choice); existing limits D59 (tokens per session) and D86 (rate limits); over the limit → alert and his decision (continue or temporary code_only_mode).

### Step 7 — Exit
- **D160 Exit criteria:** every D128 handover item has a decision here; Ticketing contract tests (blockers 1, 2, 8) written as a plan, run against the mock now and the real Ticketing later; every number labelled design choice; independent review of Phase 6 + a final cross-step review; then Phase 7 Implementation.

### Review of Phase 6 (design-auditor, read-only, 2026-10-21): PASS WITH CONCERNS → 8 fixes + LOW notes APPROVED (his "موافق", 17:32); these lines amend D130–D160 above
1. **Missing handover items (HIGH, D138 / D151 / D160):** (a) the D28 website contract gains an "AI off, use the CS route" status; when ai_enabled is off the outbox keeps draining and queued requests become handoffs; (b) OpenRouter configured with a provider allow-list and no-retention / no-training settings (D71, D111, T6); (c) the idempotency key is kept until the outbox row reaches its final status (Phase 5 final fix 3); (d) D151 runbooks explicitly include R2, R3b, R11, R12, T5b, R6 and Redis lost (Step 7 fix 6).
2. **Shadow mode (HIGH, D138):** while blocker 7 is open, shadow_mode forces code-only (no LLM / embedding vendor); in shadow, Ticketing tickets, P1 alerts and D15 denial counting are off (Step 7 fix 1).
3. **Flag changes (MED-HIGH, D138):** the CLI calls an authenticated Gateway admin endpoint (ops role only) that writes the sync audit row in the same transaction; no direct DB writes.
4. **Immediate alerts (MED, D146):** also immediate: D66 failure rate > 5% (D117), bulk FAILED closures (D104), every flag change and every debug-logging enable (D104, Step 5 fix 8).
5. **Alert channel content (MED, D146):** alerts carry only the alert name, counts, request_id and the runbook link — no PII or message text (D108); business P1 escalation stays in Ticketing only.
6. **Public demo (MED, D131 / D159):** seeded fake accounts only + a visible "do not enter real data" banner; a hard credit limit on the provider key; reaching the daily cost limit switches to code_only_mode automatically (then alert).
7. **Exposure (MED, D134 / D141):** Grafana, Prometheus, Loki and /metrics have no public route (SSH tunnel only); default Grafana credentials changed; /metrics blocked at nginx.
8. **Backups (MED, D153):** demo backup retention value (design choice, set with D125 answers; backups age out, D109 fix 4); the encryption key stored apart from the backups; the restore runbook sets ai_enabled = off until ops turns it back on.
- **LOW:** an eval run that hits its cost cap counts as incomplete and blocks the release (never fewer than D113's ×3 runs); soft gates still need signed exceptions (D112); the CI LLM key has a spend limit and is not available to fork PRs.

### Final cross-step review of Phase 6 (design-auditor, read-only, 2026-10-21): PASS WITH CONCERNS → 6 fixes APPROVED (his "موافق", 17:55) → PHASE 6 CLOSED
1. **D110 / D109 coverage (MED-HIGH, D133 / D153):** one least-privilege DB user per module (built in Phase 7); a daily Worker job deletes final-status payloads and expired LLM-call rows (D144) per D109 retention; secret rotation = manual, steps in a runbook; written demo exceptions: no TLS inside the single host (internal network only), live-DB encryption via VM disk encryption (design choice).
2. **Cost guard actor (MED, fix 6 / D138 / D159):** the cost guard may only turn code_only_mode ON, through the same audited admin endpoint, actor = "system"; it never turns flags off. D159 reads: demo = automatic switch; production = the owner decides.
3. **Flag precedence (MED, D138):** ai_enabled off > shadow_mode > code_only_mode > rollout_percent.
4. **More immediate alerts (MED, D146 + fix 4):** manual Degraded switch (D85 / D104) and setting or lifting the D99 "under review" hold.
5. **Release vs D122 (MED, D140):** rollback rehearsed in staging on every release; after each deploy a 1-hour watch of the D117 monitors (design choice) = the "faster stages"; change-freeze dates = owner.
6. **Open questions (LOW):** added below — demo backup retention, provider hard credit limit, CI key spend limit.

### Open questions
- For him (demo owner): cost cap per eval run and per day; online demo VM or local only; alert channel Telegram or email; demo backup retention; provider key hard credit limit; CI LLM key spend limit.
- For the real owner (added to D125): customer feedback button on the website; retention of review samples.
