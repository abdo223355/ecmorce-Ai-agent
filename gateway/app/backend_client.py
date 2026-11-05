"""④ Backend Client — the ONLY door from the Gateway to the NovaCart backend (D19).

- Sends only the user's token + an id (D25). Never a customer_id / worker_id from the LLM.
- Retries (D83 + Step 2/3 fix 1): transient errors only (timeout, 503, network), up to 2 retries,
  backoff 1 s then 2 s, best-effort inside the request budget: an attempt starts only if
  attempt timeout + its backoff + a 2.2 s reserve still fit before the deadline.
- No retry on 400 / 401 / 403 / 404 / 422. One re-request on a malformed response.
- 404 = "not found or not yours" (D4) → NotFoundOrNotYours. The caller records the denial.
- Circuit breaker (D84) comes in Milestone 2 (needs Redis).
"""
from __future__ import annotations

import asyncio
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import settings
from .identity import Identity
from .schemas import BackendOrder, BackendRecentOrders, BackendReturns, BackendShipment, BackendShipmentsToday

M = TypeVar("M", bound=BaseModel)
TRANSIENT_STATUS = {502, 503, 504}


class BackendError(Exception):
    """Base class. The agent never sees these; tools turn them into typed results."""


class NotFoundOrNotYours(BackendError):
    pass


class BackendUnavailable(BackendError):
    """Out of retries or out of time → status templates / BKD handoff (POL-BDR-001)."""


class BackendBadData(BackendError):
    """Schema still invalid after one re-request (POL-AGV-001 §3) → safe failure / escalation."""


class Deadline:
    def __init__(self, seconds: float):
        self.end = time.monotonic() + seconds

    def remaining(self) -> float:
        return self.end - time.monotonic()


class BackendClient:
    def __init__(self, http: httpx.AsyncClient | None = None, base_url: str | None = None):
        self.http = http or httpx.AsyncClient(base_url=base_url or settings.backend_url)

    async def aclose(self):
        await self.http.aclose()

    async def _get(self, identity: Identity, path: str, model: type[M], deadline: Deadline,
                   params: dict | None = None) -> M:
        headers = {"Authorization": f"Bearer {identity.token}"}
        attempt, malformed_retry_used = 0, False
        while True:
            try:
                resp = await self.http.get(path, headers=headers, params=params,
                                           timeout=min(settings.backend_attempt_timeout_s,
                                                       max(deadline.remaining(), 0.05)))
                if resp.status_code == 404:
                    raise NotFoundOrNotYours(path)
                if resp.status_code in TRANSIENT_STATUS:
                    raise httpx.HTTPStatusError("transient", request=resp.request, response=resp)
                if resp.status_code >= 400:
                    raise BackendError(f"backend {resp.status_code}")  # no retry (D83)
                try:
                    return model.model_validate(resp.json())
                except (ValidationError, ValueError):
                    if malformed_retry_used:
                        raise BackendBadData(path) from None
                    malformed_retry_used = True  # one re-request (POL-BDR-001)
                    continue
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt >= settings.backend_max_retries:
                    raise BackendUnavailable(path) from exc
                backoff = settings.backend_backoffs_s[attempt]
                needed = backoff + settings.backend_attempt_timeout_s + settings.reserve_after_backend_s
                if deadline.remaining() < needed:
                    raise BackendUnavailable(path) from exc  # best effort inside 8 s (fix 1)
                attempt += 1
                await asyncio.sleep(backoff)

    # ---- the four data endpoints (D25) ----
    async def recent_orders(self, identity: Identity, deadline: Deadline) -> BackendRecentOrders:
        return await self._get(identity, "/customer/orders/recent", BackendRecentOrders, deadline,
                               params={"limit": settings.recent_orders_limit})

    async def returns(self, identity: Identity, deadline: Deadline) -> BackendReturns:
        return await self._get(identity, "/customer/returns", BackendReturns, deadline)

    async def order(self, identity: Identity, order_id: str, deadline: Deadline) -> BackendOrder:
        return await self._get(identity, f"/customer/orders/{order_id}", BackendOrder, deadline)

    async def shipments_today(self, identity: Identity, deadline: Deadline) -> BackendShipmentsToday:
        return await self._get(identity, "/worker/shipments/today", BackendShipmentsToday, deadline)

    async def shipment(self, identity: Identity, shipment_id: str, deadline: Deadline) -> BackendShipment:
        return await self._get(identity, f"/worker/shipments/{shipment_id}", BackendShipment, deadline)
