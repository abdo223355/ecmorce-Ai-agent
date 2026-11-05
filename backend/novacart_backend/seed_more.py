"""Add MORE test data to an already seeded database, without touching anything that exists (new ids, new people).

    docker compose run --rm --no-deps --entrypoint python -v ./backend:/src -w /src backend -m novacart_backend.seed_more

What it adds (dates are relative to NOW, so "today" really is today):
- 5 new customers c-100201..c-100205 (a name, a phone, an address and a login each, same demo password as the others);
- for the 10 old demo customers and the 5 new ones, 10 orders each in every state: Pending, Confirmed, Processing,
  Packed, Shipped (due tomorrow), Out for Delivery (due today), Delivered twice (3 and 20 days ago, one of them a phone),
  Failed Delivery and Cancelled; and a return on the delivered ones, cycling through all six return states;
- for the 5 demo workers w-2001..w-2005, 12 shipments each: due TODAY (Out for Delivery, Shipped, Delivered, Failed),
  due tomorrow, and delivered 5 hours ago (inside the 24 h access window) and 40 hours ago (outside it).
It refuses to run twice. A description of what was added is written to backend/SEED_MORE.md.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from . import seed as base
from .auth import hash_password
from .db import make_engine, make_session_factory
from .models import RETURN_STATUSES, Base, Customer, Order, OrderItem, Return, Shipment, UserAccount, Worker

NEW_CUSTOMERS = 5
DEMO_WORKERS = 5


def _next(session, model, column, prefix: str) -> int:
    last = session.scalar(select(func.max(column)))
    return int(str(last).removeprefix(prefix)) + 1


def phone_item(seeder: base.Seeder) -> OrderItem:
    """An order line for a phone (the first two electronics of the catalogue are the phones)."""
    name, price = base.CATALOG["electronics"][base.RNG.choice([0, 1])]
    return OrderItem(product_name=name, category="electronics", qty=1, unit_price=Decimal(price), sale_label="none",
                     custom_made=False, pre_order=False)


def counts(session) -> dict:
    return {m.__tablename__: session.scalar(select(func.count()).select_from(m))
            for m in (Customer, Worker, Order, OrderItem, Return, Shipment, UserAccount)}


def extend(session) -> dict:
    if session.get(Customer, "C-100201") is not None:
        raise SystemExit("Already extended (C-100201 exists). Nothing was changed.")
    base.RNG.seed(2026)                                              # other choices than the first seeding
    seeder = base.Seeder(session)
    seeder.order_seq = _next(session, Order, Order.order_id, "NC-")
    seeder.return_seq = _next(session, Return, Return.return_id, "R-")
    seeder.ship_seq = _next(session, Shipment, Shipment.shipment_id, "S-")
    seeder.workers = list(session.scalars(select(Worker).order_by(Worker.worker_id)))
    old_customers = list(session.scalars(select(Customer).order_by(Customer.customer_id)))
    before = counts(session)

    # ---- 5 new customers with a login ----
    password = hash_password(base.DEMO_PASSWORD)
    new_people = []
    for i in range(NEW_CUSTOMERS):
        city = base.RNG.choice(list(base.CITIES))
        c = Customer(customer_id=f"C-{100201 + i}", full_name=f"{base.RNG.choice(base.FIRST)} {base.RNG.choice(base.LAST)}",
                     phone=f"+2010{base.RNG.randint(10_000_000, 99_999_999)}", email=f"customer{100201 + i}@example.com",
                     city=city, address=f"{base.RNG.randint(1, 120)} {base.RNG.choice(base.STREETS)}, "
                                        f"{base.RNG.choice(base.CITIES[city])}, {city}", created_at=base.at(base.RNG.randint(60, 300)))
        new_people.append(c)
        session.add(c)
        session.add(UserAccount(username=c.customer_id.lower(), password_hash=password, role="customer", subject_id=c.customer_id))
    session.flush()

    # ---- 10 orders in every state for the 15 demo customers ----
    demo = old_customers[:base.DEMO_CUSTOMERS] + new_people
    for n, customer in enumerate(demo):
        one = lambda cat=None: [seeder.item(cat)]          # noqa: E731
        seeder.order(customer, order_days_ago=0.1, status="Pending", items=one())
        seeder.order(customer, order_days_ago=0.3, status="Confirmed", items=one())
        seeder.order(customer, order_days_ago=0.5, status="Processing", items=one(), processing_hours_ago=3)
        seeder.order(customer, order_days_ago=1.0, status="Packed", items=one())
        seeder.order(customer, order_days_ago=2.0, status="Shipped", items=one(), scheduled_days_from_now=1)
        seeder.order(customer, order_days_ago=1.5, status="Out for Delivery", items=one(), scheduled_days_from_now=0)
        recent = seeder.order(customer, order_days_ago=6, status="Delivered", items=[phone_item(seeder)], delivered_days_ago=3)
        older = seeder.order(customer, order_days_ago=25, status="Delivered", items=one(), delivered_days_ago=20)
        seeder.order(customer, order_days_ago=4, status="Failed Delivery", items=one(), scheduled_days_from_now=-1)
        seeder.order(customer, order_days_ago=8, status="Cancelled", items=one())
        seeder.add_return(recent, RETURN_STATUSES[n % len(RETURN_STATUSES)], 2)
        if n % 2:
            seeder.add_return(older, RETURN_STATUSES[(n + 3) % len(RETURN_STATUSES)], 12)

    # ---- shipments for the 5 demo workers: today, tomorrow and the access window ----
    now = base.cairo_now()
    hours_today = now.hour + now.minute / 60
    today_delivered = max(0.01, min(0.15, hours_today / 24 * 0.8))      # still today in Cairo, even just after midnight
    everyone = old_customers + new_people
    for worker in seeder.workers[:DEMO_WORKERS]:
        def other():
            return base.RNG.choice(everyone)
        for status in ("Out for Delivery",) * 3 + ("Shipped",):
            seeder.order(other(), order_days_ago=2, status=status, items=[seeder.item()], worker=worker, scheduled_days_from_now=0)
        for _ in range(2):
            seeder.order(other(), order_days_ago=3, status="Delivered", items=[seeder.item()], worker=worker, delivered_days_ago=today_delivered)
        seeder.order(other(), order_days_ago=3, status="Failed Delivery", items=[seeder.item()], worker=worker, scheduled_days_from_now=0)
        for _ in range(2):
            seeder.order(other(), order_days_ago=2, status="Shipped", items=[seeder.item()], worker=worker, scheduled_days_from_now=1)
        seeder.order(other(), order_days_ago=3, status="Delivered", items=[seeder.item()], worker=worker, delivered_days_ago=5 / 24)
        seeder.order(other(), order_days_ago=4, status="Delivered", items=[seeder.item()], worker=worker, delivered_days_ago=40 / 24)
    session.commit()
    after = counts(session)
    return {table: after[table] - before[table] for table in after if after[table] != before[table]}


def report(session, path: Path) -> None:
    rows = lambda sql: session.execute(sql).all()                    # noqa: E731
    lines = ["# More test data (made by novacart_backend.seed_more)", "",
             "Same demo password as the other accounts (see SEED_SCENARIOS.md). Nothing existing was changed.", "",
             "New customers: c-100201 .. c-100205 (each with a name, phone, address and login).",
             "Customers c-100001 .. c-100010 and c-100201 .. c-100205 each got 10 more orders: Pending, Confirmed, Processing,",
             "Packed, Shipped (due tomorrow), Out for Delivery (due today), two Delivered (one is a phone), Failed Delivery, Cancelled,",
             "and returns on the delivered ones cycling through Requested, Approved, Rejected, Picked Up, Received, Refunded.", "",
             "Workers w-2001 .. w-2005 each got 12 shipments: due TODAY (3 Out for Delivery, 1 Shipped, 2 Delivered, 1 Failed),",
             "2 due tomorrow, one delivered 5 hours ago (inside the 24 h access window) and one delivered 40 hours ago (outside it).", ""]
    today = session.scalar(select(func.count()).select_from(Shipment).where(Shipment.scheduled_delivery_date == base.cairo_now().date()))
    lines += [f"Shipments due today in the whole database now: {today}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--report-file", default=str(Path(__file__).resolve().parent.parent / "SEED_MORE.md"))
    args = ap.parse_args()
    engine = make_engine(args.database_url)
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        added = extend(s)
        report(s, Path(args.report_file))
        total = counts(s)
        today = s.scalar(select(func.count()).select_from(Shipment).where(Shipment.scheduled_delivery_date == base.cairo_now().date()))
    print("Added:", added)
    print("Totals now:", total, "| shipments due today:", today)


if __name__ == "__main__":
    main()
