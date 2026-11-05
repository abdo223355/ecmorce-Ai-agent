"""The numbers of the admin dashboard, from the Gateway's `events` table (one row per request, no text, no person ids).

fetch_events reads the rows; every other function takes a DataFrame and returns numbers, so they are tested without a
database. The dashboard watches the agent: how fast, how often it fails, how often it hands off.
"""
from __future__ import annotations

import pandas as pd
import psycopg

WINDOWS = {"آخر ساعة": 1, "آخر 24 ساعة": 24, "آخر 7 أيام": 168, "الكل": None}
FAILED_TEMPLATES = {15, 18}              # classify failed (15) and "could not finish" (18): what the user feels as a failure
COLUMNS = ["ts", "role", "classify_path", "classify_status", "classify_reason", "classify_latency_s", "reply_status",
           "reply_reason", "reply_latency_s", "total_latency_s", "outcomes", "handoff_reason", "priority", "p1"]


def fetch_events(dsn: str, hours: int | None) -> pd.DataFrame:
    sql = f"SELECT {', '.join(COLUMNS)} FROM events"
    params: tuple = ()
    if hours is not None:
        sql += " WHERE ts > now() - make_interval(hours => %s)"
        params = (hours,)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute(sql + " ORDER BY ts", params).fetchall()
    return pd.DataFrame(rows, columns=COLUMNS)


def _failed(outcomes) -> bool:
    return any(o.get("template_id") in FAILED_TEMPLATES for o in outcomes)


def summary(df: pd.DataFrame) -> dict:
    """The headline numbers. An empty table gives zeros, never an error."""
    if df.empty:
        return {"requests": 0, "p50": 0.0, "p95": 0.0, "max": 0.0, "failure_rate": 0.0, "handoffs": 0, "p1": 0, "code_share": 0.0}
    total = df["total_latency_s"].astype(float)
    classified = df["classify_path"].dropna()
    return {"requests": len(df), "p50": float(total.quantile(0.5)), "p95": float(total.quantile(0.95)), "max": float(total.max()),
            "failure_rate": float(df["outcomes"].map(_failed).mean()),
            "handoffs": int(df["handoff_reason"].notna().sum()), "p1": int(df["p1"].sum()),
            "code_share": float((classified == "code").mean()) if len(classified) else 0.0}


def node_latency(df: pd.DataFrame) -> pd.DataFrame:
    """For the classify (model path only) and the reply: calls, ok calls, and the time of the ok calls."""
    rows = []
    for node, path_filter in (("classify", df["classify_path"] == "llm"), ("reply", df["reply_status"].notna())):
        status, latency = df.loc[path_filter, f"{node}_status"], df.loc[path_filter, f"{node}_latency_s"].astype(float)
        ok = latency[status == "ok"]
        rows.append({"node": node, "calls": int(len(status)), "ok": int((status == "ok").sum()),
                     "p50_s": float(ok.quantile(0.5)) if len(ok) else 0.0, "p95_s": float(ok.quantile(0.95)) if len(ok) else 0.0,
                     "max_s": float(ok.max()) if len(ok) else 0.0})
    return pd.DataFrame(rows).set_index("node")


def status_counts(df: pd.DataFrame, node: str) -> pd.Series:
    """How many calls ended in each status for one node (the code path is not a model call, so it is left out)."""
    mask = df["classify_path"] == "llm" if node == "classify" else df["reply_status"].notna()
    return df.loc[mask, f"{node}_status"].value_counts()


def outcome_counts(df: pd.DataFrame) -> pd.Series:
    """How many answer parts of each kind: 'template 18', 'text', 'clarify'."""
    labels = [f"template {o['template_id']}" if o["kind"] == "template" else o["kind"] for row in df["outcomes"] for o in row]
    return pd.Series(labels, dtype="object").value_counts()


def handoffs_by_reason(df: pd.DataFrame) -> pd.DataFrame:
    handed = df[df["handoff_reason"].notna()]
    if handed.empty:
        return pd.DataFrame(columns=["handoff_reason", "priority", "count"])
    return handed.groupby(["handoff_reason", "priority"], dropna=False).size().reset_index(name="count")
