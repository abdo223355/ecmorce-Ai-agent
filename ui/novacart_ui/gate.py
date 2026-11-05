"""The sign-in gate of the owner's pages (Admin and Lab): a username and password per person, checked in the database.

The rules live in novacart_ui/auth.py (hashes, lock after 5 wrong passwords, a login log). This file only draws the form
and keeps the session: it ends after IDLE_MINUTES without a click, a page checks the ROLE of the person (admin pages
refuse the support role), and one sign-in serves every owner page. Unsure or broken means closed.
"""
from __future__ import annotations

import os
import time

import streamlit as st

from .auth import IDLE_MINUTES, AdminStore, AuthUnavailable, idle_expired

REASON_SAME_FOR_ALL = "اسم المستخدم أو كلمة السر غلط، أو الحساب مقفول مؤقتًا."      # never says which one


@st.cache_resource
def get_store() -> AdminStore:
    return AdminStore(os.environ["GATEWAY_DATABASE_URL"])


def sign_out(notice: str | None = None) -> None:
    st.session_state.pop("admin_user", None)
    if notice:
        st.session_state["gate_notice"] = notice


def check_idle() -> None:
    """Ends the session of a person who has been idle too long; otherwise marks them as just seen."""
    user = st.session_state.get("admin_user")
    if user and idle_expired(user["seen"], time.time()):
        sign_out(f"الجلسة انتهت بعد {IDLE_MINUTES} دقيقة من غير نشاط. ادخل تاني.")
    elif user:
        user["seen"] = time.time()


def _login_form(title: str) -> None:
    st.title(title)
    if st.session_state.get("gate_notice"):
        st.warning(st.session_state.pop("gate_notice"))
    with st.form("owner-login"):
        username = st.text_input("اسم المستخدم")
        password = st.text_input("كلمة السر", type="password")
        if st.form_submit_button("دخول", use_container_width=True):
            try:
                outcome = get_store().login(username, password)
            except AuthUnavailable:
                st.error("نظام الدخول مش متاح دلوقتي.")
                return
            if outcome.ok:
                st.session_state["admin_user"] = {"username": outcome.user.username, "role": outcome.user.role,
                                                  "seen": time.time()}
                st.rerun()
            st.error(REASON_SAME_FOR_ALL)


def admin_gate(title: str, allowed_roles: tuple[str, ...] = ("admin",)) -> bool:
    """True only for a signed-in person whose role is in `allowed_roles`. Draws the form (or the refusal) otherwise."""
    check_idle()
    user = st.session_state.get("admin_user")
    if not user:
        _login_form(title)
        return False
    with st.sidebar:
        st.markdown(f"**{user['username']}** · {user['role']}")
        if st.button("خروج", use_container_width=True, key=f"signout-{title}"):
            sign_out()
            st.rerun()
    if user["role"] not in allowed_roles:
        st.title(title)
        st.error("دورك مش مسموح له بالصفحة دي.")
        if not st.session_state.get(f"denied-{title}"):               # one log line per person per page, not one per click
            st.session_state[f"denied-{title}"] = True
            try:
                get_store().log_event(user["username"], False, "role_denied")
            except Exception:                                          # noqa: BLE001  the refusal stands even if the log fails
                pass
        return False
    return True


def staff_page() -> None:
    """The page every visitor can open: sign in as staff, or see who you are and sign out. After signing in, the side menu
    (app.py) shows the pages of the person's role."""
    check_idle()
    user = st.session_state.get("admin_user")
    if not user:
        _login_form("دخول الفريق 🔐")
        return
    st.title("حسابي 🔐")
    st.success(f"مسجّل كـ {user['username']} ({user['role']})")
    if user["role"] == "support":
        st.info("دور support: صفحتك هي \"الحالات\".")
    if st.button("خروج", key="staff-signout"):
        sign_out()
        st.rerun()
