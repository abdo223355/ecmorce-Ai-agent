"""The staff console's logic: the order of the cases, the readable summary, and the rules kept in the database.

The database tests need the Gateway PostgreSQL with the `handoffs` table (made by the gateway at startup), the OWNER login in
GATEWAY_DATABASE_URL (to put test cases in) and UI_DB_PASSWORD (the screens' own limited login, the one that must be enough).
They skip if any of that is missing, and they remove their rows.
"""
import os

import pandas as pd
import psycopg
import pytest

from novacart_ui.cases import REASON_LABEL, claim, fetch_case, fetch_cases, resolve, sort_cases, summary_lines

SUMMARY = {"parts": [{"part_index": 0, "intent": "C10", "label": "Complaint or dispute", "outcome": "handed_over",
                      "clue": "Samsung Galaxy A55", "p1_flag": None},
                     {"part_index": 1, "intent": None, "label": None, "outcome": "answered", "p1_flag": "takeover"}],
           "error_codes": ["order_details:unavailable:backend_down"], "policies": ["POL-RET-001 §2@2.1"],
           "verified_order_ids": ["NC-100007"], "order_number_mentioned_unverified": True}


# ---------- pure ----------
def test_cases_are_sorted_p1_first_then_oldest_first_and_no_priority_goes_last():
    df = pd.DataFrame({"handoff_id": list("abcd"), "priority": ["P3", None, "P1", "P1"],
                       "created_at": pd.to_datetime(["2026-11-02 10:00", "2026-11-02 09:00", "2026-11-02 11:00", "2026-11-02 08:00"])})
    assert list(sort_cases(df)["handoff_id"]) == ["d", "c", "a", "b"]
    assert sort_cases(df.iloc[0:0]).empty


def test_every_reason_code_of_the_agent_has_a_label():
    assert set(REASON_LABEL) == {"BKD", "POL", "AUTH", "INFO", "SCOPE", "SAFE", "CMP", "PENDING_OWNER"}


def test_the_summary_is_shown_as_lines_and_invents_nothing():
    text = "\n".join(summary_lines(SUMMARY))
    for fact in ("Complaint or dispute (C10)", "handed_over", "Samsung Galaxy A55", "takeover", "NC-100007",
                 "order_details:unavailable:backend_down", "POL-RET-001 §2@2.1", "ما اتأكّدناش"):
        assert fact in text
    assert summary_lines({}) == []
    assert "NC-100007" not in "\n".join(summary_lines({**SUMMARY, "verified_order_ids": []}))     # a resolved case shows none


# ---------- the database ----------
@pytest.fixture
def db():
    owner = os.getenv("GATEWAY_DATABASE_URL")
    password = os.getenv("UI_DB_PASSWORD")
    if not owner or not password:
        pytest.skip("needs GATEWAY_DATABASE_URL (owner) and UI_DB_PASSWORD")
    ui_dsn = "postgresql://ui_app:%s@%s" % (password, owner.split("@", 1)[1])
    try:
        conn = psycopg.connect(owner, connect_timeout=3, autocommit=True)
        conn.execute("SELECT 1 FROM handoffs LIMIT 1")
    except psycopg.Error:
        pytest.skip("gateway database or the handoffs table not reachable")
    conn.execute("DELETE FROM handoffs WHERE role = 'pytest'")
    yield conn, ui_dsn
    conn.execute("DELETE FROM handoffs WHERE role = 'pytest'")
    conn.close()


def add(conn, **kw) -> str:
    row = {"role": "pytest", "subject_id": "C-100003", "reason": "CMP", "priority": "P2", **kw}
    return str(conn.execute("INSERT INTO handoffs (role, subject_id, reason, priority, ack_template, summary) "
                            "VALUES (%s, %s, %s, %s, 5, %s::jsonb) RETURNING handoff_id",
                            (row["role"], row["subject_id"], row["reason"], row["priority"],
                             '{"parts": [], "verified_order_ids": ["NC-100007"]}')).fetchone()[0])


def test_the_screens_login_lists_and_filters_cases(db):
    conn, ui = db
    pending, other = add(conn), add(conn, reason="POL", priority="P1")
    df = fetch_cases(ui, status="PENDING", reason="CMP", limit=500)
    assert pending in set(df["handoff_id"]) and other not in set(df["handoff_id"])
    assert fetch_case(ui, pending)["subject_id"] == "C-100003" and fetch_case(ui, "00000000-0000-0000-0000-000000000000") is None


def test_the_screens_login_can_claim_once_and_resolve_and_the_id_is_erased(db):
    conn, ui = db
    hid = add(conn)
    assert claim(ui, hid, "support-1") is True and claim(ui, hid, "support-2") is False
    assert resolve(ui, hid, "support-1", "called the customer") is True and resolve(ui, hid, "support-2", "again") is False
    case = fetch_case(ui, hid)
    assert (case["status"], case["subject_id"], case["claimed_by"], case["resolved_by"], case["note"]) == \
           ("RESOLVED", None, "support-1", "support-1", "called the customer")
    assert case["summary"]["verified_order_ids"] == []


def test_the_screens_login_cannot_change_a_case_by_itself(db):
    conn, ui = db
    hid = add(conn)
    with psycopg.connect(ui, autocommit=True) as c:
        for sql in ("UPDATE handoffs SET status = 'RESOLVED' WHERE handoff_id = %s",
                    "UPDATE handoffs SET subject_id = 'C-999' WHERE handoff_id = %s",
                    "UPDATE handoffs SET reason = 'POL' WHERE handoff_id = %s",
                    "DELETE FROM handoffs WHERE handoff_id = %s"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql, (hid,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO handoffs (role, reason, ack_template, summary) VALUES ('pytest', 'POL', 5, '{}')")
    assert fetch_case(ui, hid)["status"] == "PENDING"
