"""① API — Milestone 1 Gateway.

What works now: token verification (②), the backend client (④) and the agent tools.
What comes later (Milestone 2+): ③ Redis state/memory, ⑤ Business Rules, ⑧ circuit breakers +
Degraded mode, ⑨ outbox/Ticketing, ⑩ audit tables, ⑪ P1 patterns / PII scrub / D66 validate / templates.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .agent import AgentContext, run_agent
from .backend_client import BackendClient, Deadline
from .config import settings
from .identity import AuthError, Identity, JwksCache, verify_token
from .tools import ToolResult, customer, worker


class BoundTools:
    """Implements agent.Tools: binds identity + deadline so the agent never touches them."""

    def __init__(self, client: BackendClient, identity: Identity, deadline: Deadline):
        self._c, self._id, self._d = client, identity, deadline

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

    async def policy_search(self, query: str):
        return ToolResult("not_implemented", reason="rag_not_built")

    async def procedure_search(self, query: str):
        return ToolResult("not_implemented", reason="rag_not_built")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)  # D93: 1,000 characters


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.backend = BackendClient()
    app.state.jwks = JwksCache(settings.jwks_url)
    yield
    await app.state.backend.aclose()


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
    tools = BoundTools(app.state.backend, identity, deadline)
    ctx = AgentContext(role=identity.role, message=body.message,  # TODO M2: scrub at ingress (D107)
                       chat_id=f"{identity.subject_id}:{identity.session_id}",
                       remaining_s=deadline.remaining())
    try:
        result = await run_agent(ctx, tools)
    except NotImplementedError:
        return {"status": "not_ready", "message": "The agent is not built yet (docs/AGENT_ROADMAP.md)."}
    return {"status": "ok", "result": asdict(result)}  # TODO M2: D66 validate + render placeholders


# ---- developer-only endpoints to try the tools without an agent (disabled when DEV_TOOLS=0) ----
import os  # noqa: E402

if os.getenv("DEV_TOOLS", "1") == "1":
    @app.get("/dev/tools/{name}")
    async def dev_tool(name: str, arg: str | None = None, fields: str | None = None,
                       authorization: str | None = Header(default=None)):
        identity = await current_identity(authorization)
        t = BoundTools(app.state.backend, identity, Deadline(settings.request_budget_s))
        calls = {
            "my_recent_orders": lambda: t.my_recent_orders(),
            "order_details": lambda: t.order_details(arg or ""),
            "my_shipments_today": lambda: t.my_shipments_today(arg or "list"),
            "shipment_details": lambda: t.shipment_details(arg or "", (fields or "").split(",") if fields else []),
        }
        if name not in calls:
            raise HTTPException(404, "unknown tool")
        res = await calls[name]()
        data = res.data
        if isinstance(data, list):
            data = [d.model_dump(mode="json") for d in data]
        elif hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        return {"status": res.status, "reason": res.reason, "details": res.details, "data": data}
