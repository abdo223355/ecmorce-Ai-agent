"""Backend contract tests (SQLite). Run: pytest backend/tests"""
import pytest

from novacart_backend.app import create_app
from novacart_backend.seed import DEMO_PASSWORD, Seeder
from novacart_backend.db import make_engine, make_session_factory
from novacart_backend.models import Base


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("nc")
    url = f"sqlite:///{tmp / 'nc.db'}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        seeder = Seeder(s)
        seeder.people(); seeder.accounts(); s.flush()
        seeder.scenarios_for_demo_customers(); seeder.random_orders(); s.commit()
    app = create_app(database_url=url, key_dir=str(tmp / "keys"))
    return app.test_client()


def login(client, username):
    r = client.post("/auth/login", json={"username": username, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.json
    return {"Authorization": f"Bearer {r.json['access_token']}"}


def test_login_rejects_bad_password(client):
    assert client.post("/auth/login", json={"username": "c-100001", "password": "x"}).status_code == 401


def test_jwks_published(client):
    keys = client.get("/.well-known/jwks.json").json["keys"]
    assert keys and keys[0]["alg"] == "RS256"


def test_recent_orders_only_own(client):
    h = login(client, "c-100001")
    orders = client.get("/customer/orders/recent?limit=20", headers=h).json["orders"]
    assert orders and all(o["customer_id"] == "C-100001" for o in orders)
    assert "email" not in str(orders) and "payment" not in str(orders)


def test_order_details_fields_and_flags(client):
    h = login(client, "c-100003")
    body = client.get("/customer/orders/NC-100007", headers=h).json
    assert body["items"][0]["sale_label"] == "final_sale"
    for forbidden in ("payment_method", "internal_notes", "email", "total_amount"):
        assert forbidden not in body


def test_other_customers_order_is_404(client):
    h = login(client, "c-100002")
    assert client.get("/customer/orders/NC-100001", headers=h).status_code == 404  # belongs to C-100001
    assert client.get("/customer/orders/NC-999999", headers=h).status_code == 404  # does not exist


def test_role_separation(client):
    h = login(client, "c-100001")
    assert client.get("/worker/shipments/today", headers=h).status_code == 403
    assert client.get("/customer/orders/recent").status_code == 401


def test_worker_today_and_assignment(client):
    h = login(client, "w-2001")
    body = client.get("/worker/shipments/today", headers=h).json
    assert len(body["shipments"]) >= 5
    assert all(s["assigned_worker_id"] == "W-2001" for s in body["shipments"])
    other = login(client, "w-2002")
    sid = body["shipments"][0]["shipment_id"]
    assert client.get(f"/worker/shipments/{sid}", headers=other).status_code == 404
    assert client.get(f"/worker/shipments/{sid}", headers=h).status_code == 200


def test_inconsistent_delivered_without_date_exists(client):
    h = login(client, "c-100007")
    body = client.get("/customer/orders/NC-100021", headers=h).json
    assert body["status"] == "Delivered" and body["delivered_at"] is None


def test_my_returns_lists_only_own_returns_newest_first_without_internal_fields(client):
    h = login(client, "c-100001")
    body = client.get("/customer/returns", headers=h).json
    rows = body["returns"]
    assert rows and len(rows) <= 20
    own = {o["order_id"] for o in client.get("/customer/orders/recent?limit=20", headers=h).json["orders"]}
    assert all(set(r) == {"return_id", "order_id", "status", "created_at", "last_updated", "item"} for r in rows)
    created = [r["created_at"] for r in rows]
    assert created == sorted(created, reverse=True)
    for r in rows:                                                    # each return belongs to an order of this customer
        assert client.get(f"/customer/orders/{r['order_id']}", headers=h).status_code == 200
    assert "reason" not in str(rows) and "customer_id" not in str(rows)


def test_my_returns_never_shows_another_customers_return(client):
    mine = {r["return_id"] for r in client.get("/customer/returns", headers=login(client, "c-100001")).json["returns"]}
    other = {r["return_id"] for r in client.get("/customer/returns", headers=login(client, "c-100002")).json["returns"]}
    assert not (mine & other)


def test_my_returns_needs_a_customer_token(client):
    assert client.get("/customer/returns").status_code == 401
    assert client.get("/customer/returns", headers=login(client, "w-2001")).status_code == 403


def test_a_host_database_url_gets_the_psycopg_driver():
    from novacart_backend.db import sqlalchemy_url
    assert sqlalchemy_url("postgres://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert sqlalchemy_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert sqlalchemy_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert sqlalchemy_url("sqlite://") == "sqlite://"
