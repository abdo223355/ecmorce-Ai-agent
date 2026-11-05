"""① API — Milestone 1 Gateway.

What works now: token verification (②), the backend client (④) and the agent tools.
What comes later (Milestone 2+): ③ Redis state/memory, ⑤ Business Rules, ⑧ circuit breakers +
Degraded mode, ⑨ outbox/Ticketing, ⑩ audit tables, ⑪ P1 patterns / PII scrub / D66 validate / templates.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .agent import AgentContext, AgentRejected, run_agent
from .backend_client import BackendClient, Deadline
from .agent import pending as pend
from .config import settings
from .memory import MemoryStore
from .events import EventStore, build_event, public_answer
from .handoffs import HandoffStore, keep_the_promise
from .identity import AuthError, Identity, JwksCache, verify_token
from .rag import retrieve
from .rag.embeddings import EmbeddingAdapter, get_embedder
from .rag.store import PolicyStore
from .scrub import scrub_order_numbers
from .tools import ToolResult, customer, worker

# The nodes log one JSON line each at INFO (counts, template ids, latency, tokens; never message text, D108).
# Without a handler and a level the root logger drops them, so a successful model call left no trace.
logging.basicConfig(format="%(message)s")
logging.getLogger("gateway").setLevel(logging.INFO)


class BoundTools:
    """Implements agent.Tools: binds identity + deadline so the agent never touches them."""

    def __init__(self, client: BackendClient, identity: Identity, deadline: Deadline,
                 store: PolicyStore | None = None, embedder: EmbeddingAdapter | None = None):
        self._c, self._id, self._d = client, identity, deadline
        self._store, self._embedder = store, embedder
        self._prefetch: tuple[str, asyncio.Task] | None = None

    def prefetch_embedding(self, text: str) -> None:
        """Start embedding the user message now, in parallel with classify, so the embedding call hides behind it.

        The cost is that every message goes to the embedding vendor, including ones that need no policy.
        The ingress scrub (Milestone 2) doesn't exist yet, so the text is not scrubbed: use synthetic data only.
        """
        if self._embedder is None:
            return
        timeout = min(retrieve.PREFETCH_TIMEOUT_S, self._d.remaining() - settings.reserve_after_backend_s)
        if timeout > 0:
            self._prefetch = (text, asyncio.create_task(self._embedder.embed_query(text, timeout_s=timeout)))

    def close(self) -> None:
        """Called at the end of a request: cancel an early embedding that nobody used."""
        if self._prefetch and not self._prefetch[1].done():
            self._prefetch[1].cancel()

    async def my_recent_orders(self):
        return await customer.my_recent_orders(self._c, self._id, self._d)

    async def my_returns(self):
        return await customer.my_returns(self._c, self._id, self._d)

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
        """The audience comes from the verified token's role, never from the agent."""
        if self._id.role != role:
            return ToolResult("denied", reason="wrong_role")
        if self._store is None or self._embedder is None:
            return ToolResult("unavailable", reason="policy_store_not_configured")
        # The early embedding only applies to the exact text it was made from.
        task = self._prefetch[1] if self._prefetch and self._prefetch[0] == query else None
        return await retrieve.search(query, audience, self._d, self._store, self._embedder, english_query,
                                     prefetched=task)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)  # D93: 1,000 characters


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.backend = BackendClient()
    app.state.jwks = JwksCache(settings.jwks_url)
    # Open the policy store without waiting, so the Gateway still starts if the database is late.
    # A search while it is down returns ToolResult("unavailable") instead of crashing.
    app.state.store = PolicyStore()
    await app.state.store.open()
    app.state.embedder = get_embedder()
    app.state.handoffs = HandoffStore()
    await app.state.handoffs.open()
    try:
        await app.state.handoffs.ensure_schema()
    except Exception as e:                                       # noqa: BLE001  without the table every handoff falls back (no promise is made)
        logging.getLogger("gateway.handoffs").error('{"event": "schema_failed", "error": "%s"}', type(e).__name__)
    app.state.memory = MemoryStore(settings.redis_url)
    app.state.events = EventStore()
    await app.state.events.open()
    try:
        await app.state.events.ensure_schema()
    except Exception as e:                                       # noqa: BLE001  the chat must start even if the table could not be made
        logging.getLogger("gateway.events").warning('{"event": "schema_failed", "error": "%s"}', type(e).__name__)
    from .agent.runner import system
    system()                       # import LangGraph and compile the agent graphs now, not on the first user request (~1.8 s)
    yield
    await app.state.store.close()
    await app.state.events.close()
    await app.state.handoffs.close()
    await app.state.memory.aclose()
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
async def chat(body: ChatIn, background: BackgroundTasks, authorization: str | None = Header(default=None)):
    identity = await current_identity(authorization)
    deadline = Deadline(settings.request_budget_s)
    tools = bound_tools(identity, deadline)
    message, order_refs = scrub_order_numbers(body.message)      # D107 first slice: typed order numbers become {order_ref_N}
    chat_id = f"{identity.subject_id}:{identity.session_id}"
    memory = getattr(app.state, "memory", None)
    card = await memory.get(chat_id) if memory is not None else None            # D61: the pending clarification, if any
    pending = card.get("pending") if isinstance(card, dict) and pend.valid(card.get("pending")) else None
    ctx = AgentContext(role=identity.role, message=message, order_refs={**order_refs, **pend.order_refs_for(pending)},   # TODO M2: the rest of the scrub (phones, emails, cards)
                       chat_id=chat_id, pending=pending,
                       deadline_at=deadline.end)
    started = time.monotonic()
    tools.prefetch_embedding(ctx.message)        # the agent passes this same text as `query` to policy_search
    try:
        result = await run_agent(ctx, tools)
    except AgentRejected:
        raise HTTPException(403, "no agent for this role") from None         # D36: any other role gets no agent
    finally:
        tools.close()
    result = await keep_the_promise(app.state.handoffs, identity.role, identity.subject_id, result, body.message)   # D14: written BEFORE the answer
    background.add_task(app.state.events.record, build_event(identity.role, result, time.monotonic() - started))
    new_card = result.memory.get("pending")
    if memory is not None and (new_card or pending):             # a new card, or the old one is finished or replaced
        background.add_task(memory.put, chat_id, {"pending": new_card} if new_card else None)
    return {"status": "ok", "result": public_answer(result)}  # TODO M2: D66 validate + render placeholders


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
            "my_returns": lambda: t.my_returns(),
            "order_details": lambda: t.order_details(arg or ""),
            "my_shipments_today": lambda: t.my_shipments_today(arg or "list"),
            "shipment_details": lambda: t.shipment_details(arg or "", (fields or "").split(",") if fields else []),
            "policy_search": lambda: t.policy_search(arg or "", en),          # ?arg=<question>&en=<English query>
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
