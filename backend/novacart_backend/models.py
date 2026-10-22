"""NovaCart backend data model (the "existing" e-commerce system the Gateway talks to).

The data is synthetic but shaped like a real business (Phase 3 D25, Phase 4 D44):
customers, delivery workers, orders with items, returns and shipments.
Status values follow the NovaCart corpus. REF-OST-001 / REF-RST-001 are not in the
project files, so the exact lists are an ASSUMPTION (see STATUS_* below).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ASSUMPTION: order statuses seen in POL-CAN-001 v1.0 / GDL-DTS-001 (REF-OST-001 missing).
ORDER_STATUSES = (
    "Pending", "Confirmed", "Processing", "Packed", "Shipped",
    "Out for Delivery", "Delivered", "Failed Delivery", "Cancelled",
)
# ASSUMPTION: return statuses (REF-RST-001 missing from the corpus).
RETURN_STATUSES = ("Requested", "Approved", "Rejected", "Picked Up", "Received", "Refunded")
SHIPMENT_STATUSES = ("Shipped", "Out for Delivery", "Delivered", "Failed Delivery")
CATEGORIES = ("electronics", "apparel", "home", "beauty", "books", "toys", "gift_card")
SALE_LABELS = ("none", "final_sale", "clearance")


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    customer_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # C-100001
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(160))  # never leaves the backend (D25)
    city: Mapped[str] = mapped_column(String(60))
    address: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Worker(Base):
    __tablename__ = "workers"
    worker_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # W-2001
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    zone: Mapped[str] = mapped_column(String(60))


class Order(Base):
    __tablename__ = "orders"
    order_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # NC-100001 (POL-AGV-001 §2)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), index=True)
    order_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_method: Mapped[str] = mapped_column(String(16))  # never leaves the backend
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # never leaves the backend
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    customer: Mapped[Customer] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", order_by="OrderItem.item_id")
    returns: Mapped[list["Return"]] = relationship(back_populates="order", order_by="Return.return_id")
    shipment: Mapped["Shipment | None"] = relationship(back_populates="order", uselist=False)


class OrderItem(Base):
    __tablename__ = "order_items"
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), index=True)
    product_name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(24))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # D44 flags (ASSUMPTION N11: owner of the real backend must confirm these exist)
    sale_label: Mapped[str] = mapped_column(String(16), default="none")
    custom_made: Mapped[bool] = mapped_column(Boolean, default=False)
    pre_order: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[Order] = relationship(back_populates="items")


class Return(Base):
    __tablename__ = "returns"
    return_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # R-500001
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("order_items.item_id"))
    status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order: Mapped[Order] = relationship(back_populates="returns")
    item: Mapped[OrderItem] = relationship()


class Shipment(Base):
    __tablename__ = "shipments"
    shipment_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # S-700001
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), unique=True)
    assigned_worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"), index=True)
    status: Mapped[str] = mapped_column(String(24))
    scheduled_delivery_date: Mapped[date] = mapped_column(Date, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    address: Mapped[str] = mapped_column(String(240))
    delivery_instructions: Mapped[str | None] = mapped_column(String(240), nullable=True)
    cod_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order: Mapped[Order] = relationship(back_populates="shipment")


class UserAccount(Base):
    """Login accounts for the demo website (sign-in stays outside the Gateway, D29)."""
    __tablename__ = "user_accounts"
    username: Mapped[str] = mapped_column(String(60), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))  # customer | worker
    subject_id: Mapped[str] = mapped_column(String(16))  # customer_id or worker_id
