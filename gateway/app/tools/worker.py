"""Worker tools A–B (D43). Tool C procedure_search lives in app/rag (your part).

Rules: GDL-DTS-001 §2 query shapes; POL-DWA-001 §4 access window (after it, only order id + status);
requested_fields is an explicit enum checked by code (D35 / D41); another worker's shipment → 404 →
neutral denial, counted (D41).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from ..audit import record_denial
from ..backend_client import (BackendBadData, BackendClient, BackendError, BackendUnavailable, Deadline,
                              NotFoundOrNotYours)
from ..config import settings
from ..identity import Identity
from ..schemas import BackendShipment, ShipmentView, TodayView
from . import ToolResult

SHIPMENT_ID_RE = re.compile(r"^S-\d{6}$")  # mock backend format (ASSUMPTION: not defined in the corpus)
TodayQuery = Literal["list", "count", "pending", "completed"]
ShipmentField = Literal["customer_name", "customer_phone", "address", "delivery_instructions",
                        "scheduled_delivery_date", "cod_amount", "last_updated"]
ALLOWED_FIELDS: set[str] = set(ShipmentField.__args__)  # anything else is denied by code


def _require_worker(identity: Identity) -> ToolResult | None:
    return None if identity.role == "worker" else ToolResult("denied", reason="wrong_role")


def _window_closed(sh: BackendShipment, now: datetime | None = None) -> bool:
    if sh.status != "Delivered" or sh.delivered_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now - sh.delivered_at > timedelta(hours=settings.worker_access_window_h)


async def my_shipments_today(client: BackendClient, identity: Identity, query: TodayQuery,
                             deadline: Deadline) -> ToolResult:
    """Tool A — today's shipments in the GDL-DTS-001 §2 shape for `query`."""
    if (bad := _require_worker(identity)):
        return bad
    try:
        res = await client.shipments_today(identity, deadline)
    except BackendUnavailable:
        return ToolResult("unavailable", reason="backend_unavailable")
    except BackendBadData:
        return ToolResult("data_issue", reason="backend_schema_invalid")
    except BackendError:
        return ToolResult("unavailable", reason="backend_error")
    mine = [s for s in res.shipments if s.assigned_worker_id == identity.subject_id]  # ④ re-check
    if query == "list":
        rows = [{"order_id": s.order_id, "customer_name": s.customer_name, "customer_phone": s.customer_phone,
                 "address": s.address} for s in mine]
    elif query == "count":
        rows = []
    elif query == "pending":  # "pending" = not yet delivered, NOT order status Pending (GDL-DTS-001 §3)
        rows = [{"order_id": s.order_id, "status": s.status} for s in mine
                if s.status in ("Out for Delivery", "Failed Delivery")]  # exactly GDL-DTS-001 §2
    else:  # completed
        rows = [{"order_id": s.order_id, "status": s.status} for s in mine if s.status == "Delivered"]
    count = len(mine) if query in ("list", "count") else len(rows)
    return ToolResult("ok", data=TodayView(query=query, date=res.date, count=count, rows=rows))


async def shipment_details(client: BackendClient, identity: Identity, shipment_id: str,
                           requested_fields: list[str], deadline: Deadline) -> ToolResult:
    """Tool B — one shipment, only the requested + allowed fields."""
    if (bad := _require_worker(identity)):
        return bad
    shipment_id = shipment_id.strip().upper()
    if not SHIPMENT_ID_RE.match(shipment_id):
        return ToolResult("clarify", reason="invalid_shipment_id_format")
    denied = [f for f in requested_fields if f not in ALLOWED_FIELDS]
    if denied:  # e.g. email, payment, history (POL-DWA-001 §5) — code decides, not the LLM
        record_denial(identity, "field_denied", shipment_id)
        return ToolResult("denied", reason="field_not_allowed", details={"fields": denied})
    try:
        sh = await client.shipment(identity, shipment_id, deadline)
    except NotFoundOrNotYours:
        record_denial(identity, "record_not_found_or_not_yours", shipment_id)
        return ToolResult("denied", reason="not_found_or_not_yours")
    except BackendUnavailable:
        return ToolResult("unavailable", reason="backend_unavailable")
    except BackendBadData:
        return ToolResult("data_issue", reason="backend_schema_invalid")
    except BackendError:
        return ToolResult("unavailable", reason="backend_error")
    if sh.assigned_worker_id != identity.subject_id:  # POL-AGV-001 §3
        record_denial(identity, "record_not_found_or_not_yours", shipment_id)
        return ToolResult("denied", reason="not_found_or_not_yours")
    closed = _window_closed(sh)
    raw = sh.model_dump(mode="json")
    fields = {} if closed else {f: raw.get(f) for f in requested_fields}
    view = ShipmentView(shipment_id=sh.shipment_id, order_id=sh.order_id, status=sh.status,
                        fields=fields, window_closed=closed)
    return ToolResult("ok", data=view, reason="access_window_closed" if closed else None)
