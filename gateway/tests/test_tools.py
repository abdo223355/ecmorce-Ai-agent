"""Gateway tests against a fake backend (httpx.MockTransport). Run: pytest gateway/tests"""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.backend_client import BackendClient, Deadline
from app.identity import Identity
from app.tools import customer, worker

CUST = Identity("C-100001", "customer", "s1", "tok")
WORK = Identity("W-2001", "worker", "s2", "tok")
NOW = datetime.now(timezone.utc)


def order_json(order_id="NC-100001", owner="C-100001", status="Delivered", delivered=True):
    return {"order_id": order_id, "customer_id": owner, "order_date": NOW.isoformat(), "status": status,
            "delivered_at": NOW.isoformat() if delivered else None, "last_updated": NOW.isoformat(),
            "items": [{"item_id": 1, "name": "Phone", "category": "electronics", "qty": 1,
                       "sale_label": "none", "custom_made": False, "pre_order": False}],
            "returns": [], "email": "x@y.z", "payment_method": "card"}


def ship_json(sid="S-700001", worker_id="W-2001", delivered_hours_ago=None):
    delivered = (NOW - timedelta(hours=delivered_hours_ago)).isoformat() if delivered_hours_ago else None
    return {"shipment_id": sid, "order_id": "NC-100001", "assigned_worker_id": worker_id,
            "customer_name": "Sara Ali", "customer_phone": "+201000000000", "address": "1 St",
            "delivery_instructions": None, "status": "Delivered" if delivered else "Out for Delivery",
            "scheduled_delivery_date": NOW.date().isoformat(), "delivered_at": delivered,
            "cod_amount": "100.00", "last_updated": NOW.isoformat()}


def client_with(handler):
    return BackendClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://b"))


def run(coro):
    return asyncio.run(coro)


def test_invalid_order_id_is_clarification_not_denial():
    calls = []
    c = client_with(lambda r: calls.append(r) or httpx.Response(200, json={}))
    res = run(customer.order_details(c, CUST, "12345", Deadline(8)))
    assert res.status == "clarify" and not calls  # no backend call (POL-AGV-001 §2)


def test_404_is_neutral_denial():
    c = client_with(lambda r: httpx.Response(404, json={"error": "not_found"}))
    assert run(customer.order_details(c, CUST, "NC-100099", Deadline(8))).status == "denied"


def test_owner_id_stripped_and_forbidden_fields_dropped():
    c = client_with(lambda r: httpx.Response(200, json=order_json()))
    res = run(customer.order_details(c, CUST, "nc-100001", Deadline(8)))
    dumped = res.data.model_dump()
    assert res.ok and "customer_id" not in dumped and "email" not in dumped


def test_delivered_without_date_is_data_issue():
    c = client_with(lambda r: httpx.Response(200, json=order_json(delivered=False)))
    res = run(customer.order_details(c, CUST, "NC-100001", Deadline(8)))
    assert res.status == "data_issue" and "delivered_without_delivered_at" in res.reason


def test_retry_on_503_then_success():
    n = {"i": 0}

    def handler(r):
        n["i"] += 1
        return httpx.Response(503) if n["i"] == 1 else httpx.Response(200, json=order_json())
    c = client_with(handler)
    assert run(customer.order_details(c, CUST, "NC-100001", Deadline(8))).ok and n["i"] == 2


def test_no_retry_when_budget_too_small():
    n = {"i": 0}

    def handler(r):
        n["i"] += 1
        return httpx.Response(503)
    c = client_with(handler)
    assert run(customer.order_details(c, CUST, "NC-100001", Deadline(3))).status == "unavailable"
    assert n["i"] == 1  # 1 s backoff + 1 s attempt + 2.2 s reserve does not fit in ~3 s


def test_worker_field_enum_denies_email():
    c = client_with(lambda r: httpx.Response(200, json=ship_json()))
    res = run(worker.shipment_details(c, WORK, "S-700001", ["email"], Deadline(8)))
    assert res.status == "denied" and res.reason == "field_not_allowed"


def test_worker_access_window_closed_after_24h():
    c = client_with(lambda r: httpx.Response(200, json=ship_json(delivered_hours_ago=30)))
    res = run(worker.shipment_details(c, WORK, "S-700001", ["address"], Deadline(8)))
    assert res.ok and res.data.window_closed and res.data.fields == {}


def test_customer_cannot_use_worker_tools():
    c = client_with(lambda r: httpx.Response(200, json={}))
    assert run(worker.my_shipments_today(c, CUST, "list", Deadline(8))).status == "denied"


# ---------- my_returns (night 123) ----------
def returns_json(*ids):
    return {"returns": [{"return_id": rid, "order_id": "NC-100001", "status": "Received", "created_at": NOW.isoformat(),
                         "last_updated": NOW.isoformat(), "item": "Watch", "customer_id": "C-100001", "reason": "x"}
                        for rid in ids]}


def test_my_returns_gives_the_rows_and_calls_one_endpoint():
    seen = []
    c = client_with(lambda r: seen.append(r.url.path) or httpx.Response(200, json=returns_json("R-500001", "R-500002")))
    res = run(customer.my_returns(c, CUST, Deadline(8)))
    assert res.ok and [r.return_id for r in res.data] == ["R-500001", "R-500002"] and seen == ["/customer/returns"]
    assert "customer_id" not in str(res.data[0].model_dump()) and "reason" not in str(res.data[0].model_dump())


def test_my_returns_is_for_customers_only_and_maps_backend_failures():
    called = []
    c = client_with(lambda r: called.append(r) or httpx.Response(200, json=returns_json()))
    assert run(customer.my_returns(c, WORK, Deadline(8))).status == "denied" and not called
    assert run(customer.my_returns(client_with(lambda r: httpx.Response(500)), CUST, Deadline(8))).status == "unavailable"
    assert run(customer.my_returns(client_with(lambda r: httpx.Response(200, json={"nope": 1})), CUST, Deadline(8))).status == "data_issue"
