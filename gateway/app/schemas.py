"""④ Response schemas for the NovaCart backend (D25) and the tool views the agent receives.

Backend models validate what Flask returns (POL-AGV-001 §3: schema, required fields, valid values).
Tool views are what the agent gets: owner ids are stripped (D38) and only allowed fields remain.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

# ASSUMPTION: REF-OST-001 / REF-RST-001 are missing from the corpus; lists match the mock backend.
OrderStatus = Literal["Pending", "Confirmed", "Processing", "Packed", "Shipped", "Out for Delivery",
                      "Delivered", "Failed Delivery", "Cancelled"]
ReturnStatus = Literal["Requested", "Approved", "Rejected", "Picked Up", "Received", "Refunded"]
ShipmentStatus = Literal["Shipped", "Out for Delivery", "Delivered", "Failed Delivery"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


# ---------- backend responses ----------
class BackendRecentOrder(_Strict):
    order_id: str
    customer_id: str
    order_date: datetime
    status: OrderStatus
    product_names: list[str]
    last_updated: datetime


class BackendRecentOrders(_Strict):
    orders: list[BackendRecentOrder]


class BackendItem(_Strict):
    item_id: int
    name: str
    category: str
    qty: int
    sale_label: Literal["none", "final_sale", "clearance"] | None = None
    custom_made: bool | None = None
    pre_order: bool | None = None


class BackendReturn(_Strict):
    return_id: str
    status: ReturnStatus
    created_at: datetime
    last_updated: datetime
    item: str | None


class BackendOrder(_Strict):
    order_id: str
    customer_id: str
    order_date: datetime
    status: OrderStatus
    delivered_at: datetime | None
    items: list[BackendItem]
    returns: list[BackendReturn]
    last_updated: datetime


class BackendShipment(_Strict):
    shipment_id: str
    order_id: str
    assigned_worker_id: str
    customer_name: str
    customer_phone: str
    address: str
    delivery_instructions: str | None
    status: ShipmentStatus
    scheduled_delivery_date: date
    delivered_at: datetime | None
    cod_amount: str
    last_updated: datetime


class BackendShipmentsToday(_Strict):
    date: date
    shipments: list[BackendShipment]


# ---------- tool views (what the agent receives) ----------
class OrderSummaryView(_Strict):
    order_id: str
    order_date: datetime
    status: OrderStatus
    product_names: list[str]
    last_updated: datetime


class OrderView(_Strict):
    order_id: str
    order_date: datetime
    status: OrderStatus
    delivered_at: datetime | None
    items: list[BackendItem]
    returns: list[BackendReturn]
    last_updated: datetime
    data_issues: list[str] = []  # POL-AGV-001 §3 consistency flags; agent must escalate, never guess


class ShipmentView(_Strict):
    """Only the fields the worker may see right now (POL-DWA-001 §4 window + requested fields)."""
    shipment_id: str
    order_id: str
    status: ShipmentStatus
    fields: dict[str, str | None]
    window_closed: bool = False  # True → only order_id + status are allowed (CP-47)


class TodayView(_Strict):
    """GDL-DTS-001 §2 shapes."""
    query: Literal["list", "count", "pending", "completed"]
    date: date
    count: int
    rows: list[dict[str, str | None]]
