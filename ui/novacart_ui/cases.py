"""The staff console's cases: what the Gateway handed over to a person (the `handoffs` table).

Reading is plain SQL; changing a case goes ONLY through the two database functions claim_handoff and resolve_handoff (the
screen's database role cannot update the table by itself). Resolving a case erases the verified user id and the verified
order ids in the database. The summary shown here is the one the code built (labels and outcomes, never the user's words).
"""
from __future__ import annotations

import pandas as pd
import psycopg

PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}           # a case with no priority yet goes after P4
STATUSES = ("PENDING", "CLAIMED", "RESOLVED")
STATUS_LABEL = {"PENDING": "مستني استلام", "CLAIMED": "مستلمة", "RESOLVED": "اتقفلت"}
REASON_LABEL = {"BKD": "بيانات الـ backend ناقصة أو فيها مشكلة", "POL": "السياسة مش واضحة", "AUTH": "صلاحية أو هوية",
                "INFO": "معلومة مش متاحة", "SCOPE": "خارج نطاق الـ agent", "SAFE": "أمان", "CMP": "شكوى أو نزاع",
                "PENDING_OWNER": "سبب لسه مش متحدد"}
NOTE_MAX = 1000
LIST_COLUMNS = ["handoff_id", "created_at", "role", "subject_id", "reason", "priority", "status", "claimed_by", "resolved_by",
                "resolved_at", "note", "block_session_data"]


def sort_cases(df: pd.DataFrame) -> pd.DataFrame:
    """Most urgent first (P1 on top), then the oldest first inside a priority."""
    if df.empty:
        return df
    rank = df["priority"].map(PRIORITY_RANK).fillna(len(PRIORITY_RANK) + 1)
    return df.assign(_rank=rank).sort_values(["_rank", "created_at"], ascending=[True, True]).drop(columns="_rank")


def fetch_cases(dsn: str, status: str | None = None, reason: str | None = None, limit: int = 200) -> pd.DataFrame:
    where, params = [], []
    if status:
        where.append("status = %s")
        params.append(status)
    if reason:
        where.append("reason = %s")
        params.append(reason)
    sql = f"SELECT {', '.join(LIST_COLUMNS)} FROM handoffs" + (" WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY created_at DESC LIMIT %s"
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute(sql, (*params, limit)).fetchall()
    df = pd.DataFrame(rows, columns=LIST_COLUMNS)
    df["handoff_id"] = df["handoff_id"].astype(str)
    return sort_cases(df)


def fetch_case(dsn: str, handoff_id: str) -> dict | None:
    cols = LIST_COLUMNS + ["summary", "ack_template", "claimed_at"]
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        row = conn.execute(f"SELECT {', '.join(cols)} FROM handoffs WHERE handoff_id = %s", (handoff_id,)).fetchone()
    return None if row is None else {**dict(zip(cols, row)), "handoff_id": str(row[0])}


def claim(dsn: str, handoff_id: str, staff: str) -> bool:
    with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
        return bool(conn.execute("SELECT claim_handoff(%s, %s)", (handoff_id, staff)).fetchone()[0])


def resolve(dsn: str, handoff_id: str, staff: str, note: str) -> bool:
    with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
        return bool(conn.execute("SELECT resolve_handoff(%s, %s, %s)", (handoff_id, staff, note[:NOTE_MAX])).fetchone()[0])


def summary_lines(summary: dict) -> list[str]:
    """The summary as short readable lines. Pure: it reads the dict the code built and invents nothing."""
    lines = []
    for p in summary.get("parts", []):
        what = f"{p.get('label') or 'بدون intent'}" + (f" ({p['intent']})" if p.get("intent") else "")
        extra = [f"النتيجة: {p.get('outcome')}"]
        if p.get("p1_flag"):
            extra.append(f"علامة أمان: {p['p1_flag']}")
        if p.get("clue"):
            extra.append(f"منتج مذكور: {p['clue']}")
        lines.append(f"الجزء {p.get('part_index')}: {what} · " + " · ".join(extra))
    if summary.get("verified_order_ids"):
        lines.append("طلبات اتأكّدنا إنها بتاعته: " + "، ".join(summary["verified_order_ids"]))
    if summary.get("order_number_mentioned_unverified"):
        lines.append("ذكر رقم طلب لسه ما اتأكّدناش منه")
    if summary.get("error_codes"):
        lines.append("أخطاء في الأدوات: " + "، ".join(summary["error_codes"]))
    if summary.get("policies"):
        lines.append("سياسات اتذكرت: " + "، ".join(summary["policies"]))
    return lines
