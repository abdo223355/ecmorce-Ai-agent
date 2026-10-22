"""NovaCart backend (Flask): the existing e-commerce system the Gateway reads from.

Five fixed GET endpoints (Phase 3 D25) + login for the demo website.
Rules kept from the design:
- Identity comes only from the token (D1). The caller never passes a customer_id / worker_id.
- "Not found" and "not yours" both return 404 (D4), so an ID cannot be probed.
- Forbidden fields (email, payment method, internal notes, other orders) never leave this service.
- Dates are ISO-8601 in Africa/Cairo; "today" = the Cairo date (GDL-DTS-001 §3).
"""
from __future__ import annotations

import os
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

import jwt
from flask import Flask, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .auth import KeyStore, check_password
from .db import make_engine, make_session_factory
from .models import Order, Shipment, UserAccount

CAIRO = ZoneInfo("Africa/Cairo")
RECENT_LIMIT_DEFAULT = int(os.getenv("RECENT_ORDERS_LIMIT", "5"))  # config (Phase 3: limit is config)
RECENT_LIMIT_MAX = 20


def iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:  # SQLite drops tz info; stored values are UTC
            value = value.replace(tzinfo=ZoneInfo("UTC"))
        return value.astimezone(CAIRO).isoformat()
    return value.isoformat()


def cairo_today():
    return datetime.now(CAIRO).date()


def create_app(database_url: str | None = None, key_dir: str | None = None) -> Flask:
    app = Flask(__name__)
    engine = make_engine(database_url)
    Session = make_session_factory(engine)
    keys = KeyStore(key_dir or os.getenv("KEY_DIR", "/app/keys"))
    app.config["SESSION_FACTORY"] = Session
    app.config["KEYS"] = keys

    def require_role(role: str):
        def decorator(fn):
            @wraps(fn)
            def wrapper(*args, **kwargs):
                header = request.headers.get("Authorization", "")
                if not header.startswith("Bearer "):
                    return jsonify(error="unauthorized"), 401
                try:
                    claims = keys.verify(header.removeprefix("Bearer ").strip())
                except jwt.PyJWTError:
                    return jsonify(error="unauthorized"), 401
                if claims.get("role") != role:
                    return jsonify(error="forbidden"), 403
                g.subject_id = claims["sub"]
                return fn(*args, **kwargs)
            return wrapper
        return decorator

    # ---------- auth ----------
    @app.post("/auth/login")
    def login():
        body = request.get_json(silent=True) or {}
        username, password = body.get("username", ""), body.get("password", "")
        with Session() as s:
            account = s.get(UserAccount, username)
            if account is None or not check_password(password, account.password_hash):
                return jsonify(error="invalid_credentials"), 401
            token = keys.issue(account.subject_id, account.role)
        return jsonify(access_token=token, token_type="Bearer", role=account.role,
                       expires_in=int(os.getenv("TOKEN_TTL_SECONDS", "1800")))

    @app.get("/.well-known/jwks.json")
    def jwks():
        return jsonify(keys.jwks())

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    # ---------- endpoint 1: recent orders ----------
    @app.get("/customer/orders/recent")
    @require_role("customer")
    def recent_orders():
        try:
            limit = int(request.args.get("limit", RECENT_LIMIT_DEFAULT))
        except ValueError:
            return jsonify(error="bad_request"), 400
        limit = max(1, min(limit, RECENT_LIMIT_MAX))
        with Session() as s:
            rows = s.scalars(
                select(Order).options(selectinload(Order.items))
                .where(Order.customer_id == g.subject_id)
                .order_by(Order.order_date.desc()).limit(limit)
            ).all()
            orders = [{
                "order_id": o.order_id, "customer_id": o.customer_id, "order_date": iso(o.order_date),
                "status": o.status, "product_names": [i.product_name for i in o.items],
                "last_updated": iso(o.last_updated),
            } for o in rows]
        return jsonify(orders=orders)

    # ---------- endpoint 2: one order ----------
    @app.get("/customer/orders/<order_id>")
    @require_role("customer")
    def order_details(order_id: str):
        with Session() as s:
            o = s.scalars(
                select(Order).options(selectinload(Order.items), selectinload(Order.returns))
                .where(Order.order_id == order_id)
            ).first()
            if o is None or o.customer_id != g.subject_id:  # D4: same 404 for both
                return jsonify(error="not_found"), 404
            items_by_id = {i.item_id: i for i in o.items}
            body = {
                "order_id": o.order_id, "customer_id": o.customer_id, "order_date": iso(o.order_date),
                "status": o.status, "delivered_at": iso(o.delivered_at),
                "items": [{
                    "item_id": i.item_id, "name": i.product_name, "category": i.category, "qty": i.qty,
                    "sale_label": i.sale_label, "custom_made": i.custom_made, "pre_order": i.pre_order,
                } for i in o.items],
                "returns": [{
                    "return_id": r.return_id, "status": r.status, "created_at": iso(r.created_at),
                    "last_updated": iso(r.last_updated),
                    "item": items_by_id[r.item_id].product_name if r.item_id in items_by_id else None,
                } for r in o.returns],
                "last_updated": iso(o.last_updated),
            }
        return jsonify(body)

    def shipment_view(sh: Shipment) -> dict:
        customer = sh.order.customer
        return {
            "shipment_id": sh.shipment_id, "order_id": sh.order_id,
            "assigned_worker_id": sh.assigned_worker_id,
            "customer_name": customer.full_name, "customer_phone": customer.phone,
            "address": sh.address, "delivery_instructions": sh.delivery_instructions,
            "status": sh.status, "scheduled_delivery_date": iso(sh.scheduled_delivery_date),
            "delivered_at": iso(sh.delivered_at), "cod_amount": str(sh.cod_amount),
            "last_updated": iso(sh.last_updated),
        }

    # ---------- endpoint 3: worker's shipments today ----------
    @app.get("/worker/shipments/today")
    @require_role("worker")
    def shipments_today():
        with Session() as s:
            rows = s.scalars(
                select(Shipment).options(selectinload(Shipment.order).selectinload(Order.customer))
                .where(Shipment.assigned_worker_id == g.subject_id,
                       Shipment.scheduled_delivery_date == cairo_today())
                .order_by(Shipment.shipment_id)
            ).all()
            return jsonify(date=cairo_today().isoformat(), shipments=[shipment_view(sh) for sh in rows])

    # ---------- endpoint 4: one shipment ----------
    @app.get("/worker/shipments/<shipment_id>")
    @require_role("worker")
    def shipment_details(shipment_id: str):
        with Session() as s:
            sh = s.scalars(
                select(Shipment).options(selectinload(Shipment.order).selectinload(Order.customer))
                .where(Shipment.shipment_id == shipment_id)
            ).first()
            if sh is None or sh.assigned_worker_id != g.subject_id:  # D4
                return jsonify(error="not_found"), 404
            return jsonify(shipment_view(sh))

    return app
