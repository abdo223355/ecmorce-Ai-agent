# Live system on free hosting (real AI, open to everyone)

The recorded demo (`docs/DEPLOY_DEMO.md`) shows saved answers. This guide puts the **real system** online: the real model, the real
rules, the real database, so a visitor can type any question.

```
visitor -> Streamlit Community Cloud (ui/public_app.py, the chat screen only)
              |  HTTPS
              v
           Render: novacart-gateway  --->  Render: novacart-backend
              |  |                              |
              |  +-- OpenRouter (the model)     +-- Neon: database `novacart`
              +-- Neon: database `gateway` (policy search, events, handoffs)
              +-- Upstash Redis (optional: the chat's short memory)
```

**Status: written and checked locally, not yet run on these hosts.** Free-plan terms change often (sleep rules, database
expiry, card requirements): read each provider's current free-plan page before you rely on it.

## Before you publish anything: protect the model key

A public site spends your key on every message, and the demo password is public. So:

1. In the OpenRouter dashboard set a **spending limit** on this key (for example 5 USD). This is the hard stop.
2. The Gateway also refuses too much use by itself (`RATE_LIMIT_PER_MIN`, default 10 per account; `RATE_LIMIT_PER_DAY`, default
   300 for the whole Gateway). Its counters live in memory, so a restart resets them: the spending limit above is what
   really caps the bill.
3. The admin pages, the cases console and the Lab are NOT on the public screen, and the developer endpoints stay closed
   (`DEV_TOOLS=0`).

## Steps (done by the repository owner: the secrets are yours to type)

### 1. Neon (database)
1. Create a project at https://neon.tech. Create two databases in it: `novacart` and `gateway`.
2. Copy the connection string of each (it ends with `?sslmode=require`). Keep them private.

### 2. Render (backend and Gateway)
1. At https://render.com choose New > Blueprint, pick this repository. It reads `render.yaml` and creates two web services.
2. When asked for the values marked `sync: false`, type:
   - backend `DATABASE_URL`: the Neon string of `novacart`;
   - gateway `GATEWAY_DATABASE_URL`: the Neon string of `gateway`;
   - gateway `OPENROUTER_API_KEY`: your key;
   - gateway `BACKEND_URL`: the public address of the backend service (for example `https://novacart-backend.onrender.com`);
   - gateway `JWKS_URL`: that address plus `/.well-known/jwks.json`.
   The Blueprint does not ask for `REDIS_URL`: the chat then works without its short memory. To add it later, create an
   Upstash Redis database and add `REDIS_URL` (a `rediss://...` address) in the gateway's Environment tab.
   If the name `novacart-backend` is already taken on Render, the address gets a random suffix: after the backend is created,
   copy its real address from its page and correct `BACKEND_URL` and `JWKS_URL` of the gateway.
3. The first start of the backend fills the database with the demo data (a few minutes). A service on the free plan sleeps when
   idle, so the first message after a pause takes 30 to 60 seconds.

### 3. Load the policy documents for the RAG (once, from your computer)
The corpus lives in `../Rag_files/NovaCart_RAG_Corpus/` (outside the repository) and `pdftotext` (poppler) must be installed.
```
cd gateway
set GATEWAY_DATABASE_URL=<the Neon string of `gateway`>
set OPENROUTER_API_KEY=<your key>
python -m app.rag.ingest
```
Without this step policy questions get the honest "the policy is not confirmed" answer.

### 4. Streamlit Community Cloud (the screen)
1. New app > this repository > branch `main` > main file `ui/public_app.py` > Python 3.12.
2. Advanced settings > Secrets:
```
BACKEND_URL = "https://<your-backend>.onrender.com"
GATEWAY_URL = "https://<your-gateway>.onrender.com"
```
3. Deploy, then put the address in the README.

### 5. Check it
Sign in as `c-100005` (password in the README) and ask `ينفع ألغي NC-100014؟`, then `ما هي سياسة الاسترجاع؟`. Send 11 messages in
a minute and the screen should answer that you are going too fast (HTTP 429 from the Gateway).

## Keeping it healthy
- The demo data is dated the day it was seeded; the edge cases (return windows) drift as the days pass. Re-seed now and then.
- Watch the OpenRouter usage page after you share the link.
- To switch it off in a hurry: suspend the Render gateway service. The screen then answers that the service is not available.
