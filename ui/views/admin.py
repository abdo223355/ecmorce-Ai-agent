"""Admin dashboard: watches the agent (latency, failures, handoffs). Reads the Gateway's `events` table only.

It shows numbers about requests, never message text and never a person (the table holds neither, D108).
Access: a signed-in person with the admin role (novacart_ui/gate.py, accounts in the Gateway DB).
"""
from __future__ import annotations

import os

import streamlit as st

from novacart_ui.gate import admin_gate
from novacart_ui.metrics import (WINDOWS, fetch_events, handoffs_by_reason, node_latency, outcome_counts, status_counts,
                                 summary)

st.set_page_config(page_title="NovaCart · Admin", page_icon="📊", layout="wide")
st.markdown("""<style>
[data-testid="stMarkdownContainer"] p { unicode-bidi: plaintext; }
</style>""", unsafe_allow_html=True)

DSN = os.environ["GATEWAY_DATABASE_URL"]            # no fallback: a missing variable must fail, not use another login


def dashboard() -> None:
    top = st.columns([3, 1, 1])
    top[0].title("لوحة مراقبة الـ agent 📊")
    window = top[1].selectbox("الفترة", list(WINDOWS), index=1)
    if top[2].button("تحديث", use_container_width=True):
        st.rerun()
    try:
        df = fetch_events(DSN, WINDOWS[window])
    except Exception:                                             # noqa: BLE001  any database trouble becomes one clear message
        st.error("مش قادر أقرا من قاعدة البيانات. اتأكد إن الـ Gateway DB شغّالة.")
        return
    if df.empty:
        st.info("مفيش طلبات في الفترة دي لسه.")
        return

    s = summary(df)
    first, second = st.columns(3), st.columns(3)
    first[0].metric("الطلبات", s["requests"])
    first[1].metric("الزمن p50", f"{s['p50']:.2f} ث")
    first[2].metric("الزمن p95", f"{s['p95']:.2f} ث", help="الميزانية الكلية للطلب 8 ث")
    second[0].metric("طلبات فشلت (15 أو 18)", f"{s['failure_rate']:.0%}")
    second[1].metric("تحويلات لموظف", f"{s['handoffs']}", help=f"منها P1: {s['p1']}")
    second[2].metric("اتحلّت بالكود", f"{s['code_share']:.0%}", help="رسايل الـ classify فيها اتحلّت من غير موديل")

    st.subheader("زمن كل مكالمة موديل")
    st.dataframe(node_latency(df).round(2), use_container_width=True)
    left, right = st.columns(2)
    left.subheader("حالة الـ classify")
    left.bar_chart(status_counts(df, "classify"))
    right.subheader("حالة الـ reply")
    right.bar_chart(status_counts(df, "reply"))
    left, right = st.columns(2)
    left.subheader("نوع الرد")
    left.bar_chart(outcome_counts(df))
    right.subheader("التحويلات حسب السبب والأولوية")
    right.dataframe(handoffs_by_reason(df), use_container_width=True, hide_index=True)
    st.subheader("الزمن الكلي عبر الوقت")
    st.line_chart(df.set_index("ts")["total_latency_s"])
    st.subheader("آخر 50 طلب")
    st.dataframe(df.drop(columns=["classify_reason"]).tail(50).iloc[::-1], use_container_width=True, hide_index=True)


if admin_gate("لوحة المراقبة 📊"):
    dashboard()
