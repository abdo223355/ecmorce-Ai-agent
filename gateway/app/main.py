"""① API — Milestone 1 Gateway.

What works now: token verification (②), the backend client (④) and the agent tools.
What comes later (Milestone 2+): ③ Redis state/memory, ⑤ Business Rules, ⑧ circuit breakers +
Degraded mode, ⑨ outbox/Ticketing, ⑩ audit tables, ⑪ P1 patterns / PII scrub / D66 validate / templates.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .agent import AgentContext, run_agent
from .backend_client import BackendClient, Deadline
from .config import settings
from .identity import AuthError, Identity, JwksCache, verify_token
from .rag import retrieve
from .rag.embeddings import EmbeddingAdapter, get_embedder
from .rag.store import PolicyStore
from .tools import ToolResult, customer, worker


class BoundTools:
    """Implements agent.Tools: binds identity + deadline so the agent never touches them."""

    def __init__(self, client: BackendClient, identity: Identity, deadline: Deadline,
                 store: PolicyStore | None = None, embedder: EmbeddingAdapter | None = None):
        self._c, self._id, self._d = client, identity, deadline
        self._store, self._embedder = store, embedder
        self._prefetch: tuple[str, asyncio.Task] | None = None

    def prefetch_embedding(self, text: str) -> None:
        """Early embedding (option أ): start embedding the user message now, in parallel with classify.
        Cost accepted: every message goes to the embedding vendor, also the ones that need no policy (D105).
        Until the ingress scrub exists (D107, Milestone 2) this text is NOT scrubbed: synthetic data only (D111)."""
        if self._embedder is None:
            return
        timeout = min(retrieve.PREFETCH_TIMEOUT_S, self._d.remaining() - settings.reserve_after_backend_s)
        if timeout > 0:
            self._prefetch = (text, asyncio.create_task(self._embedder.embed_query(text, timeout_s=timeout)))

    def close(self) -> None:
        """End of the request: stop an early embedding nobody used."""
        if self._prefetch and not self._prefetch[1].done():
            self._prefetch[1].cancel()

    async def my_recent_orders(self):
        return await customer.my_recent_orders(self._c, self._id, self._d)

    async def order_details(self, order_id: str):
        return await customer.order_details(self._c, self._id, order_id, self._d)

    async def check_eligibility(self, kind: str, order):
        return await customer.check_eligibility(kind, order)

    async def my_shipments_today(self, query: str):
        return await worker.my_shipments_today(self._c, self._id, query, self._d)

    async def shipment_details(self, shipment_id: str, requested_fields: list[str]):
        return await worker.shipment_details(self._c, self._id, shipment_id, requested_fields, self._d)

    async def policy_search(self, query: str, english_query: str | None = None):
        return await self._rag("customer", "customers", query, english_query)

    async def procedure_search(self, query: str, english_query: str | None = None):
        return await self._rag("worker", "delivery_workers", query, english_query)

    async def _rag(self, role: str, audience: str, query: str, english_query: str | None):
        """The audience comes from the verified token's role, never from the agent (D1, D47)."""
        if self._id.role != role:
            return ToolResult("denied", reason="wrong_role")
        if self._store is None or self._embedder is None:
            return ToolResult("unavailable", reason="policy_store_not_configured")
        # The early embedding is only valid for the exact text it was made from.
        task = self._prefetch[1] if self._prefetch and self._prefetch[0] == query else None
        return await retrieve.search(query, audience, self._d, self._store, self._embedder, english_query,
                                     prefetched=task)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)  # D93: 1,000 characters


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.backend = BackendClient()
    app.state.jwks = JwksCache(settings.jwks_url)
    # Policy store (D48): opened without waiting, so the Gateway starts even if the DB is late;
    # a search while it is down returns ToolResult("unavailable") instead of crashing.
    app.state.store = PolicyStore()
    await app.state.store.open()
    app.state.embedder = get_embedder()
    yield
    await app.state.store.close()
    await app.state.backend.aclose()


def bound_tools(identity: Identity, deadline: Deadline) -> "BoundTools":
    return BoundTools(app.state.backend, identity, deadline, app.state.store, app.state.embedder)


app = FastAPI(title="NovaCart Adaptive AI Gateway", lifespan=lifespan)


async def current_identity(authorization: str | None) -> Identity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "unauthorized")
    try:
        return await verify_token(authorization.removeprefix("Bearer ").strip(), app.state.jwks)
    except AuthError:
        raise HTTPException(401, "unauthorized") from None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(body: ChatIn, authorization: str | None = Header(default=None)):
    identity = await current_identity(authorization)
    deadline = Deadline(settings.request_budget_s)
    tools = bound_tools(identity, deadline)
    ctx = AgentContext(role=identity.role, message=body.message,  # TODO M2: scrub at ingress (D107)
                       chat_id=f"{identity.subject_id}:{identity.session_id}",
                       remaining_s=deadline.remaining())
    tools.prefetch_embedding(ctx.message)        # same text the agent passes as `query` to policy_search
    try:
        result = await run_agent(ctx, tools)
    except NotImplementedError:
        return {"status": "not_ready", "message": "The agent is not built yet (docs/AGENT_ROADMAP.md)."}
    finally:
        tools.close()
    return {"status": "ok", "result": asdict(result)}  # TODO M2: D66 validate + render placeholders


# ---- developer-only endpoints to try the tools without an agent (disabled when DEV_TOOLS=0) ----
import os  # noqa: E402

if os.getenv("DEV_TOOLS", "1") == "1":
    @app.get("/dev/tools/{name}")
    async def dev_tool(name: str, arg: str | None = None, fields: str | None = None, en: str | None = None,
                       authorization: str | None = Header(default=None)):
        identity = await current_identity(authorization)
        t = bound_tools(identity, Deadline(settings.request_budget_s))
        calls = {
            "my_recent_orders": lambda: t.my_recent_orders(),
            "order_details": lambda: t.order_details(arg or ""),
            "my_shipments_today": lambda: t.my_shipments_today(arg or "list"),
            "shipment_details": lambda: t.shipment_details(arg or "", (fields or "").split(",") if fields else []),
            "policy_search": lambda: t.policy_search(arg or "", en),          # ?arg=<question>&en=<english query>
            "procedure_search": lambda: t.procedure_search(arg or "", en),
        }
        if name not in calls:
            raise HTTPException(404, "unknown tool")
        res = await calls[name]()
        data = res.data
        if isinstance(data, list):
            data = [d.model_dump(mode="json") if hasattr(d, "model_dump") else d for d in data]
        elif hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        return {"status": res.status, "reason": res.reason, "details": res.details, "data": data}
