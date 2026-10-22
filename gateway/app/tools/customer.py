"""Customer tools 1–3 (D43). Tool 4 policy_search lives in app/rag (your part)."""
from __future__ import annotations

import re

from ..audit import record_denial
from ..backend_client import (BackendBadData, BackendClient, BackendError, BackendUnavailable, Deadline,
                              NotFoundOrNotYours)
from ..identity import Identity
from ..schemas import OrderSummaryView, OrderView
from . import ToolResult

ORDER_ID_RE = re.compile(r"^NC-\d{6}$")  # POL-AGV-001 §2 ("NC- followed by digits"); 6 digits in our backend


def _require_customer(identity: Identity) -> ToolResult | None:
    if identity.role != "customer":
        return ToolResult("denied", reason="wrong_role")
    return None


async def my_recent_orders(client: BackendClient, identity: Identity, deadline: Deadline) -> ToolResult:
    """Tool 1 — the customer's recent orders (for clue matching like "the watch")."""
    if (bad := _require_customer(identity)):
        return bad
    try:
        res = await client.recent_orders(identity, deadline)
    except BackendUnavailable:
        return ToolResult("unavailable", reason="backend_unavailable")
    except BackendBadData:
        return ToolResult("data_issue", reason="backend_schema_invalid")
    except BackendError:
        return ToolResult("unavailable", reason="backend_error")
    views = [OrderSummaryView(**o.model_dump(exclude={"customer_id"}))
             for o in res.orders if o.customer_id == identity.subject_id]  # ④ re-check, then strip (D38)
    return ToolResult("ok", data=views)


async def order_details(client: BackendClient, identity: Identity, order_id: str,
                        deadline: Deadline) -> ToolResult:
    """Tool 2 — one order (items with D44 flags + returns list)."""
    if (bad := _require_customer(identity)):
        return bad
    order_id = order_id.strip().upper()
    if not ORDER_ID_RE.match(order_id):
        return ToolResult("clarify", reason="invalid_order_id_format")  # not a denial (D15-j)
    try:
        o = await client.order(identity, order_id, deadline)
    except NotFoundOrNotYours:
        record_denial(identity, "record_not_found_or_not_yours", order_id)
        return ToolResult("denied", reason="not_found_or_not_yours")
    except BackendUnavailable:
        return ToolResult("unavailable", reason="backend_unavailable")
    except BackendBadData:
        return ToolResult("data_issue", reason="backend_schema_invalid")
    except BackendError:
        return ToolResult("unavailable", reason="backend_error")
    if o.customer_id != identity.subject_id:  # POL-AGV-001 §3 ownership check
        record_denial(identity, "record_not_found_or_not_yours", order_id)
        return ToolResult("denied", reason="not_found_or_not_yours")
    issues = []
    if o.status == "Delivered" and o.delivered_at is None:
        issues.append("delivered_without_delivered_at")  # POL-AGV-001 §3 consistency
    if any(i.sale_label is None or i.custom_made is None or i.pre_order is None for i in o.items):
        issues.append("item_flags_missing")  # D44: never guess, hand off
    view = OrderView(**o.model_dump(exclude={"customer_id"}), data_issues=issues)
    return ToolResult("data_issue" if issues else "ok", data=view, reason=",".join(issues) or None)


async def check_eligibility(kind: str, order: OrderView) -> ToolResult:
    """Tool 3 — ⑤ Business Rules (return / exchange / cancel). Built in Milestone 2.

    The eligibility answer is ALWAYS computed by code from ACTIVE structured values (D6, D13),
    never by the LLM. Input = the validated OrderView from order_details, never LLM arguments.
    """
    return ToolResult("not_implemented", reason="business_rules_milestone_2", details={"kind": kind})
