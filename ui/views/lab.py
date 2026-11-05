"""Lab: the owner's test bench. Try every part of the stack from one screen (not for customers).

Tabs: service health; run the chat as any seed account (with ready scenarios) and see the answer, the raw Gateway
result and the events row it wrote; what the backend itself says about that account; the Gateway DB.
Read-only except for what /chat already writes. Closed unless DEV_LAB=1, and for a signed-in admin only.
"""
from __future__ import annotations

import json
import os
import time

import httpx
import streamlit as st

from novacart_ui.api import LoginFailed, NovaCartApi, ServiceUnavailable, SessionExpired
from novacart_ui.gate import admin_gate
from novacart_ui.lab import (SCENARIOS, SEED_ACCOUNTS, backend_get, check_all, latest_events, policy_overview, role_of,
                             truth_paths)
from novacart_ui.texts import detect_language, render_reply

st.set_page_config(page_title="NovaCart · Lab", page_icon="🧪", layout="wide")
st.markdown("""<style>
[data-testid="stMarkdownContainer"] p { unicode-bidi: plaintext; }
</style>""", unsafe_allow_html=True)

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:8080")
DSN = os.environ["GATEWAY_DATABASE_URL"]            # no fallback: a missing variable must fail, not use another login
REDIS = os.getenv("REDIS_URL", "redis://localhost:6379/0")


@st.cache_resource
def api() -> NovaCartApi:
    return NovaCartApi(BACKEND, GATEWAY)


def services_tab() -> None:
    if st.button("فحص دلوقتي", key="health_button") or "health_results" not in st.session_state:
        st.session_state["health_results"] = check_all(BACKEND, GATEWAY, DSN, REDIS)
    for s in st.session_state["health_results"]:
        st.markdown(f"{'🟢' if s.ok else '🔴'} **{s.name}** · {s.detail} · {s.ms} ms")


def login_box() -> None:
    account = st.selectbox("الحساب", SEED_ACCOUNTS, key="lab_account_pick")
    password = st.text_input("كلمة سر حسابات الـ seed", type="password", help="من backend/SEED_SCENARIOS.md. مش بتتخزّن.")
    if st.button("دخول بالحساب ده"):
        try:
            st.session_state["lab_user"] = api().login(account, password)
            st.session_state["lab_name"] = account
            st.session_state.pop("lab_last", None)
        except LoginFailed:
            st.error("اسم الحساب أو كلمة السر غلط.")
        except ServiceUnavailable:
            st.error("الـ backend مش بيرد.")
    if "lab_user" in st.session_state:
        st.success(f"مسجّل كـ {st.session_state['lab_name']} ({st.session_state['lab_user'].role})")


def run_message(message: str) -> None:
    user = st.session_state["lab_user"]
    try:
        with st.spinner("..."):
            reply = api().chat(user, message)
    except SessionExpired:
        st.session_state.pop("lab_user", None)
        st.error("التوكن انتهى (30 دقيقة). ادخل تاني.")
        return
    except ServiceUnavailable as e:
        st.error(f"الـ Gateway مش بيرد ({e}).")
        return
    st.session_state["lab_last"] = {"message": message, "reply": reply, "text": render_reply(reply, detect_language(message))}
    time.sleep(0.6)                                                # the event row is written after the answer


def chat_tab() -> None:
    login_box()
    if "lab_user" not in st.session_state:
        return
    st.divider()
    left, right = st.columns(2)
    with left:
        scenario = st.selectbox("سيناريو جاهز", SCENARIOS, format_func=lambda s: f"{s.title}  ·  {s.account}")
        if scenario.account != st.session_state["lab_name"]:
            st.caption(f"السيناريو ده مكتوب لحساب {scenario.account}. غيّر الحساب فوق لو عاوزه بالظبط.")
        if st.button("شغّل السيناريو"):
            run_message(scenario.message)
    with right:
        typed = st.text_area("أو اكتب رسالتك", height=80)
        if st.button("ابعت") and typed.strip():
            run_message(typed.strip())

    last = st.session_state.get("lab_last")
    if not last:
        return
    st.subheader("الرد")
    st.markdown(f"**الرسالة:** {last['message']}")
    st.info(last["text"])
    with st.expander("الرد الخام من الـ Gateway", expanded=False):
        st.code(json.dumps(last["reply"].raw, ensure_ascii=False, indent=2), language="json")
    st.caption(f"زمن الطلب كما شافته الواجهة: {last['reply'].elapsed_s:.2f} ث")
    try:
        st.subheader("آخر 3 صفوف في events")
        st.dataframe(latest_events(DSN, 3), use_container_width=True, hide_index=True)
    except Exception:                                             # noqa: BLE001
        st.warning("مش قادر أقرا جدول events.")


def truth_tab() -> None:
    if "lab_user" not in st.session_state:
        st.info("ادخل بحساب من تاب \"شغّل كحساب\" الأول.")
        return
    user, name = st.session_state["lab_user"], st.session_state["lab_name"]
    paths = truth_paths(role_of(name))
    st.markdown(f"الحقيقة من الـ backend نفسه لحساب **{name}** (قراءة بس):")
    client = httpx.Client(timeout=5.0)
    if st.button("القايمة"):
        st.session_state["truth"] = backend_get(client, BACKEND, user.token, paths["list"])
    one = st.text_input("تفاصيل واحد (رقم الطلب أو الشحنة)", placeholder="NC-100007")
    if st.button("التفاصيل") and one.strip():
        st.session_state["truth"] = backend_get(client, BACKEND, user.token, paths["detail"] + one.strip())
    if "truth" in st.session_state:
        status, body = st.session_state["truth"]
        st.caption(f"HTTP {status}")
        st.json(body)


def database_tab() -> None:
    try:
        st.subheader("آخر 20 صف في events")
        st.dataframe(latest_events(DSN, 20), use_container_width=True, hide_index=True)
        st.subheader("أقسام السياسات (RAG)")
        st.dataframe(policy_overview(DSN), use_container_width=True, hide_index=True)
    except Exception:                                             # noqa: BLE001
        st.error("مش قادر أقرا من الـ Gateway DB.")


if not os.getenv("DEV_LAB", "") == "1":
    st.title("المعمل 🧪")
    st.error("الصفحة دي مقفولة: DEV_LAB مش مفعّل.")
elif admin_gate("المعمل 🧪"):
    st.title("المعمل 🧪")
    st.caption("لجربان كل حاجة بنفسك. مش للمستخدمين.")
    tabs = st.tabs(["الخدمات", "شغّل كحساب", "حقيقة الـ backend", "قاعدة البيانات"])
    with tabs[0]:
        services_tab()
    with tabs[1]:
        chat_tab()
    with tabs[2]:
        truth_tab()
    with tabs[3]:
        database_tab()
