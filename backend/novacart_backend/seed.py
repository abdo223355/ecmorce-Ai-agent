"""Seed the NovaCart backend with realistic synthetic data.

Run:  python -m novacart_backend.seed            (uses DATABASE_URL)
      python -m novacart_backend.seed --reset    (drop + recreate tables first)

All people are synthetic (D79 / D111: never real customer data). Dates are relative to the
day you run the seed (Cairo time), so "delivered 15 days ago" stays true for testing.

Sizes (design choice): 200 customers, 30 workers, ~1,000 orders.
Customers C-100001 .. C-100010 and workers W-2001 .. W-2005 have demo logins and the
hand-made "scenario" orders listed in SEED_SCENARIOS.md (policy edge cases for the agent).
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from .auth import hash_password
from .db import make_engine, make_session_factory
from .models import Base, Customer, Order, OrderItem, Return, Shipment, UserAccount, Worker

CAIRO = ZoneInfo("Africa/Cairo")
UTC = ZoneInfo("UTC")
RNG = random.Random(42)

N_CUSTOMERS, N_WORKERS, N_RANDOM_ORDERS = 200, 30, 940
DEMO_CUSTOMERS, DEMO_WORKERS = 10, 5
DEMO_PASSWORD = "NovaCart#2026"  # demo only; printed in the README

FIRST = ["Ahmed", "Mohamed", "Mahmoud", "Omar", "Youssef", "Mostafa", "Karim", "Hassan", "Tarek", "Amr",
         "Sara", "Mona", "Nour", "Aya", "Salma", "Yasmin", "Heba", "Dina", "Mariam", "Rana",
         "Abdelrahman", "Khaled", "Hana", "Laila", "Ziad", "Malak", "Fatma", "Ibrahim", "Reem", "Ali"]
LAST = ["Hassan", "Mahmoud", "Ali", "Ibrahim", "Saeed", "Fathy", "Abdelaziz", "Mostafa", "Salem", "Nasser",
        "Kamal", "Farouk", "Gaber", "Hamdy", "Shawky", "Ragab", "Soliman", "Zaki", "Fawzy", "Lotfy"]
CITIES = {
    "Cairo": ["Nasr City", "Maadi", "Heliopolis", "Shubra", "Zamalek", "New Cairo"],
    "Giza": ["Dokki", "Mohandessin", "Haram", "6th of October", "Sheikh Zayed"],
    "Alexandria": ["Smouha", "Sidi Gaber", "Miami", "Stanley"],
    "Beni Suef": ["El Wasta", "Nasser City"],
    "New Valley": ["Kharga", "Dakhla"],
}
STREETS = ["El Tahrir St", "El Nasr Rd", "Abbas El Akkad St", "Gamal Abdel Nasser St", "El Haram St",
           "Port Said St", "El Geish St", "26th of July St", "Makram Ebeid St", "El Merghany St"]
INSTRUCTIONS = [None, None, "Call before arrival", "Leave with the building guard", "2nd floor, flat 5",
                "Do not ring the bell, baby sleeping", "Gate code 1234", "Deliver after 5 pm"]

CATALOG = {
    "electronics": [("Samsung Galaxy A55", 15999), ("Xiaomi Redmi Note 13", 9499), ("Anker Power Bank 20000mAh", 1299),
                    ("JBL Tune 520BT Headphones", 2499), ("Lenovo IdeaPad Slim 3", 27999), ("Apple Watch SE", 13999),
                    ("Logitech MX Master 3S", 4299), ("TP-Link Archer AX55 Router", 3199)],
    "apparel": [("Cotton Polo Shirt", 549), ("Slim Fit Jeans", 899), ("Winter Hoodie", 1199), ("Running Shoes", 2299),
                ("Linen Abaya", 1599), ("Leather Jacket", 3499), ("Kids Pajama Set", 399)],
    "home": [("Tefal Non-stick Pan 28cm", 1199), ("Philips Air Fryer", 5499), ("Cotton Bed Sheet Set", 899),
             ("Desk Lamp LED", 449), ("Kitchen Knife Set", 999)],
    "beauty": [("Argan Oil Shampoo", 249), ("Vitamin C Serum", 399), ("Perfume Oud 100ml", 1499)],
    "books": [("Arabic Novel - Paperback", 180), ("Python Crash Course", 950), ("Kids Story Book", 120)],
    "toys": [("LEGO Classic Box", 1999), ("Remote Control Car", 899), ("Puzzle 1000 pcs", 349)],
    "gift_card": [("NovaCart Gift Card 500 EGP", 500), ("NovaCart Gift Card 1000 EGP", 1000)],
}
RETURN_REASONS = ["Wrong size", "Damaged on arrival", "Not as described", "Changed my mind", "Defective item"]


def cairo_now() -> datetime:
    return datetime.now(CAIRO).replace(microsecond=0)


def at(days_ago: float, hour: int = 12) -> datetime:
    """A Cairo datetime `days_ago` days before now, stored as UTC.

    Under 2 days the exact time is kept (needed for "30 hours ago" window tests);
    otherwise a realistic hour of that day is used. Never in the future.
    """
    now = cairo_now()
    exact = now - timedelta(days=days_ago)
    if days_ago < 2:
        return exact.astimezone(UTC)
    value = datetime.combine(exact.date(), time(hour, RNG.randint(0, 59)), CAIRO)
    return min(value, now - timedelta(minutes=5)).astimezone(UTC)


class Seeder:
    def __init__(self, session):
        self.s = session
        self.order_seq, self.return_seq, self.ship_seq = 100001, 500001, 700001
        self.scenarios: list[str] = []
        self.customers: list[Customer] = []
        self.workers: list[Worker] = []

    # ---------- people ----------
    def people(self):
        for i in range(N_CUSTOMERS):
            city = RNG.choice(list(CITIES))
            c = Customer(
                customer_id=f"C-{100001 + i}",
                full_name=f"{RNG.choice(FIRST)} {RNG.choice(LAST)}",
                phone=f"+2010{RNG.randint(10_000_000, 99_999_999)}",
                email=f"customer{100001 + i}@example.com",
                city=city,
                address=f"{RNG.randint(1, 120)} {RNG.choice(STREETS)}, {RNG.choice(CITIES[city])}, {city}",
                created_at=at(RNG.randint(60, 700)),
            )
            self.customers.append(c)
        for i in range(N_WORKERS):
            self.workers.append(Worker(worker_id=f"W-{2001 + i}", full_name=f"{RNG.choice(FIRST)} {RNG.choice(LAST)}",
                                       phone=f"+2011{RNG.randint(10_000_000, 99_999_999)}",
                                       zone=RNG.choice(list(CITIES))))
        self.s.add_all(self.customers + self.workers)

    def accounts(self):
        pw = hash_password(DEMO_PASSWORD)
        for c in self.customers[:DEMO_CUSTOMERS]:
            self.s.add(UserAccount(username=c.customer_id.lower(), password_hash=pw, role="customer",
                                   subject_id=c.customer_id))
        for w in self.workers[:DEMO_WORKERS]:
            self.s.add(UserAccount(username=w.worker_id.lower(), password_hash=pw, role="worker",
                                   subject_id=w.worker_id))

    # ---------- building blocks ----------
    def item(self, category=None, **flags) -> OrderItem:
        category = category or RNG.choices(list(CATALOG), weights=[25, 25, 15, 10, 8, 8, 4])[0]
        name, price = RNG.choice(CATALOG[category])
        sale = flags.pop("sale_label", None) or RNG.choices(["none", "final_sale", "clearance"], [88, 6, 6])[0]
        return OrderItem(product_name=name, category=category, qty=RNG.choice([1, 1, 1, 2]),
                         unit_price=Decimal(price), sale_label=sale,
                         custom_made=flags.pop("custom_made", RNG.random() < 0.03),
                         pre_order=flags.pop("pre_order", RNG.random() < 0.03))

    def order(self, customer: Customer, *, order_days_ago: float, status: str, items: list[OrderItem],
              delivered_days_ago: float | None = None, processing_hours_ago: float | None = None,
              worker: Worker | None = None, scheduled_days_from_now: int | None = None,
              keep_delivered_at: bool = True, note: str | None = None) -> Order:
        oid = f"NC-{self.order_seq}"
        self.order_seq += 1
        order_date = at(order_days_ago, RNG.randint(9, 22))
        delivered_at = at(delivered_days_ago, RNG.randint(10, 20)) if delivered_days_ago is not None else None
        processing_started = (cairo_now() - timedelta(hours=processing_hours_ago)).astimezone(UTC) \
            if processing_hours_ago is not None else None
        last = max(x for x in [order_date, delivered_at, processing_started] if x is not None)
        o = Order(order_id=oid, customer_id=customer.customer_id, order_date=order_date, status=status,
                  delivered_at=delivered_at if keep_delivered_at else None,
                  processing_started_at=processing_started,
                  payment_method=RNG.choice(["COD", "card", "wallet"]),
                  total_amount=sum((i.unit_price * i.qty for i in items), Decimal(0)),
                  internal_notes=note, last_updated=last, items=items)
        self.s.add(o)
        if status in ("Shipped", "Out for Delivery", "Delivered", "Failed Delivery"):
            worker = worker or RNG.choice(self.workers)
            if delivered_at is not None:
                sched = delivered_at.astimezone(CAIRO).date()
            elif scheduled_days_from_now is not None:
                sched = cairo_now().date() + timedelta(days=scheduled_days_from_now)
            else:
                sched = (order_date + timedelta(days=RNG.randint(2, 4))).astimezone(CAIRO).date()
            ship_status = status if status in ("Shipped", "Out for Delivery", "Delivered", "Failed Delivery") else "Shipped"
            self.s.add(Shipment(
                shipment_id=f"S-{self.ship_seq}", order_id=oid, assigned_worker_id=worker.worker_id,
                status=ship_status, scheduled_delivery_date=sched,
                delivered_at=delivered_at if keep_delivered_at else None,
                address=customer.address, delivery_instructions=RNG.choice(INSTRUCTIONS),
                cod_amount=o.total_amount if o.payment_method == "COD" else Decimal(0), last_updated=last))
            self.ship_seq += 1
        return o

    def add_return(self, o: Order, status: str, created_days_ago: float):
        self.s.flush()  # item ids
        r = Return(return_id=f"R-{self.return_seq}", order_id=o.order_id, item_id=o.items[0].item_id,
                   status=status, reason=RNG.choice(RETURN_REASONS), created_at=at(created_days_ago),
                   last_updated=at(max(created_days_ago - RNG.randint(0, 3), 0)))
        self.return_seq += 1
        self.s.add(r)
        return r

    def note(self, customer: Customer, order: Order, text: str):
        self.scenarios.append(f"- {customer.customer_id} / {order.order_id}: {text}")

    # ---------- hand-made policy edge cases ----------
    def scenarios_for_demo_customers(self):
        c = self.customers
        w = self.workers
        # Return window edges (POL-RET-001 §2 e.g. electronics 15 days, standard goods 30 days)
        for days in (14, 15, 16):
            o = self.order(c[0], order_days_ago=days + 3, status="Delivered", delivered_days_ago=days,
                           items=[self.item("electronics", sale_label="none", custom_made=False, pre_order=False)])
            self.note(c[0], o, f"electronics delivered {days} days ago (window edge)")
        for days in (29, 30, 31):
            o = self.order(c[1], order_days_ago=days + 3, status="Delivered", delivered_days_ago=days,
                           items=[self.item("apparel", sale_label="none", custom_made=False, pre_order=False)])
            self.note(c[1], o, f"apparel delivered {days} days ago (window edge)")
        # Labels and flags (POL-RET-001 §6, D44)
        for label in ("final_sale", "clearance"):
            o = self.order(c[2], order_days_ago=8, status="Delivered", delivered_days_ago=5,
                           items=[self.item("apparel", sale_label=label, custom_made=False, pre_order=False)])
            self.note(c[2], o, f"apparel {label}, delivered 5 days ago")
        o = self.order(c[2], order_days_ago=10, status="Delivered", delivered_days_ago=6,
                       items=[self.item("home", sale_label="none", custom_made=True, pre_order=False)])
        self.note(c[2], o, "custom_made item, delivered 6 days ago")
        o = self.order(c[3], order_days_ago=6, status="Confirmed",
                       items=[self.item("electronics", sale_label="none", custom_made=False, pre_order=True)])
        self.note(c[3], o, "pre_order item, status Confirmed")
        o = self.order(c[3], order_days_ago=4, status="Delivered", delivered_days_ago=2,
                       items=[self.item("gift_card", sale_label="none", custom_made=False, pre_order=False)])
        self.note(c[3], o, "gift card, delivered 2 days ago")
        # Cancellation (POL-CAN-001: Processing window; Packed / Shipped)
        for hours in (2, 6):
            o = self.order(c[4], order_days_ago=0.3, status="Processing", processing_hours_ago=hours,
                           items=[self.item("home", sale_label="none", custom_made=False, pre_order=False)])
            self.note(c[4], o, f"Processing started {hours} hours ago")
        for st in ("Pending", "Packed", "Shipped"):
            o = self.order(c[4], order_days_ago=1, status=st, scheduled_days_from_now=1 if st == "Shipped" else None,
                           items=[self.item("books", sale_label="none", custom_made=False, pre_order=False)])
            self.note(c[4], o, f"status {st}")
        # Returns in different states
        for st, days in (("Requested", 2), ("Approved", 5), ("Refunded", 12), ("Rejected", 9)):
            o = self.order(c[5], order_days_ago=days + 8, status="Delivered", delivered_days_ago=days + 4,
                           items=[self.item("apparel", sale_label="none", custom_made=False, pre_order=False)])
            r = self.add_return(o, st, days)
            self.note(c[5], o, f"return {r.return_id} status {st}")
        # Data-quality cases (POL-AGV-001 §3: Delivered requires delivered_at)
        o = self.order(c[6], order_days_ago=7, status="Delivered", delivered_days_ago=4, keep_delivered_at=False,
                       items=[self.item("electronics", sale_label="none", custom_made=False, pre_order=False)])
        self.note(c[6], o, "INCONSISTENT: Delivered without delivered_at (must escalate, never guess)")
        # Migration note (POL-SPC-001 §8: orders before 2026-06-15)
        old_days = (cairo_now().date() - datetime(2026, 6, 10).date()).days
        o = self.order(c[7], order_days_ago=old_days, status="Delivered", delivered_days_ago=old_days - 3,
                       items=[self.item("home", sale_label="none", custom_made=False, pre_order=False)])
        self.note(c[7], o, "order placed 2026-06-10 (before 2026-06-15 migration date)")
        # Similar products, to test clue matching / "which order?" clarification
        for days in (3, 20):
            o = self.order(c[8], order_days_ago=days + 2, status="Delivered", delivered_days_ago=days,
                           items=[self.item("electronics", sale_label="none", custom_made=False, pre_order=False)])
            o.items[0].product_name = "Samsung Galaxy A55"
            self.note(c[8], o, f"Samsung Galaxy A55 delivered {days} days ago (two similar orders)")
        o = self.order(c[9], order_days_ago=3, status="Out for Delivery", worker=w[0], scheduled_days_from_now=0,
                       items=[self.item("apparel", sale_label="none", custom_made=False, pre_order=False)])
        self.note(c[9], o, f"Out for Delivery today, worker {w[0].worker_id}")

        # Worker scenarios: today's list for demo workers + window cases (POL-DWA-001 §4, 24 h)
        for wk in w[:DEMO_WORKERS]:
            for st in ("Out for Delivery", "Out for Delivery", "Delivered", "Failed Delivery", "Shipped"):
                cust = RNG.choice(c[DEMO_CUSTOMERS:])
                kwargs = {"delivered_days_ago": 0} if st == "Delivered" else {"scheduled_days_from_now": 0}
                self.order(cust, order_days_ago=3, status=st, worker=wk,
                           items=[self.item(sale_label="none", custom_made=False, pre_order=False)], **kwargs)
            self.scenarios.append(f"- {wk.worker_id}: 5 shipments today (2 Out for Delivery, 1 Delivered, "
                                  f"1 Failed Delivery, 1 Shipped)")
        for days, label in ((1.2, "delivered ~30 hours ago (outside a 24 h window)"),
                            (0.3, "delivered ~7 hours ago (inside a 24 h window)")):
            cust = RNG.choice(c[DEMO_CUSTOMERS:])
            o = self.order(cust, order_days_ago=4, status="Delivered", delivered_days_ago=days, worker=w[0],
                           items=[self.item(sale_label="none", custom_made=False, pre_order=False)])
            self.scenarios.append(f"- {w[0].worker_id} / {o.order_id}: {label}")
        cust = RNG.choice(c[DEMO_CUSTOMERS:])
        o = self.order(cust, order_days_ago=2, status="Out for Delivery", worker=w[1], scheduled_days_from_now=0,
                       items=[self.item(sale_label="none", custom_made=False, pre_order=False)])
        self.scenarios.append(f"- {o.order_id}: assigned to {w[1].worker_id}; {w[0].worker_id} asking for it must get 404")

    # ---------- bulk random history ----------
    def random_orders(self):
        for _ in range(N_RANDOM_ORDERS):
            cust = RNG.choice(self.customers)
            age = RNG.choices([RNG.uniform(0, 1), RNG.uniform(1, 4), RNG.uniform(4, 120)], [5, 10, 85])[0]
            items = [self.item() for _ in range(RNG.choices([1, 2, 3], [70, 22, 8])[0])]
            if age < 1:
                st = RNG.choice(["Pending", "Confirmed", "Processing"])
                self.order(cust, order_days_ago=age, status=st, items=items,
                           processing_hours_ago=RNG.uniform(0.1, max(age * 24, 0.2)) if st == "Processing" else None)
            elif age < 4:
                st = RNG.choice(["Packed", "Shipped", "Out for Delivery"])
                self.order(cust, order_days_ago=age, status=st, items=items,
                           scheduled_days_from_now=RNG.choice([0, 1]) if st != "Packed" else None)
            else:
                st = RNG.choices(["Delivered", "Cancelled", "Failed Delivery"], [88, 8, 4])[0]
                if st == "Delivered":
                    o = self.order(cust, order_days_ago=age, status=st, items=items,
                                   delivered_days_ago=max(age - RNG.uniform(1.5, 5), 0.1))
                    if RNG.random() < 0.12:
                        self.add_return(o, RNG.choice(["Requested", "Approved", "Picked Up", "Received",
                                                       "Refunded", "Rejected"]), max(age - 6, 0.5))
                elif st == "Failed Delivery":
                    self.order(cust, order_days_ago=age, status=st, items=items)
                else:
                    self.order(cust, order_days_ago=age, status=st, items=items)

    def write_scenarios(self, path: Path):
        lines = ["# Seed scenarios (generated by novacart_backend.seed)", "",
                 f"Generated: {cairo_now().isoformat()} (Cairo). Dates are relative to this day — re-run the "
                 "seed if you test on a later day.", "",
                 f"Demo password for all demo accounts: `{DEMO_PASSWORD}`",
                 f"Customer logins: c-100001 .. c-1000{DEMO_CUSTOMERS:02d} · Worker logins: w-2001 .. w-200{DEMO_WORKERS}",
                 "", "## Hand-made policy edge cases", *self.scenarios, ""]
        path.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop and recreate all tables")
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--scenarios-file", default=str(Path(__file__).resolve().parent.parent / "SEED_SCENARIOS.md"))
    args = ap.parse_args()
    engine = make_engine(args.database_url)
    if args.reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        if s.scalar(select(func.count()).select_from(Customer)):
            print("Database already seeded. Use --reset to rebuild.")
            return
        seeder = Seeder(s)
        seeder.people()
        seeder.accounts()
        s.flush()
        seeder.scenarios_for_demo_customers()
        seeder.random_orders()
        s.commit()
        counts = {m.__tablename__: s.scalar(select(func.count()).select_from(m))
                  for m in (Customer, Worker, Order, OrderItem, Return, Shipment, UserAccount)}
    seeder.write_scenarios(Path(args.scenarios_file))
    print("Seeded:", counts)
    print("Scenarios written to", args.scenarios_file)


if __name__ == "__main__":
    main()
