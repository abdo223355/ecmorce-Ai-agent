"""The user chat screen (customer and delivery worker). Run: streamlit run app.py

Login -> the backend gives a token and the role -> the screen shows the buttons of that role and a chat box ->
every message goes to the Gateway /chat with the token. The screen holds no business logic: what the user may see is
decided by the Gateway from the token (D1).
"""
from __future__ import annotations

import json
import os

import streamlit as st

from novacart_ui.api import LoginFailed, NovaCartApi, RateLimited, ServiceUnavailable, SessionExpired
from novacart_ui.options import options_for
from novacart_ui.texts import detect_language, render_reply

ROLE_TITLE = {"customer": "مساعد العملاء", "worker": "مساعد المندوب"}
WELCOME = {"customer": "أهلًا بيك في NovaCart. اختار مشكلتك من الأزرار، أو اكتب سؤالك.",
           "worker": "أهلًا بيك. اختار من الأزرار، أو اكتب سؤالك عن شحناتك."}
PER_ROW = 3
LIMIT_MESSAGE = {
    "minute": "بعتّ رسايل كتير بسرعة. استنى دقيقة وجرّب تاني.\n\nToo many messages too quickly: wait a minute and try again.",
    "day": "وصل الاستخدام المجاني للنهارده للحد اللي اتحدد. جرّب بكرة.\n\nToday's free usage limit was reached: please try again tomorrow.",
}

st.set_page_config(page_title="NovaCart", page_icon="💬", layout="centered")
st.markdown("""<style>
[data-testid="stChatMessageContent"] p { unicode-bidi: plaintext; text-align: start; }
</style>""", unsafe_allow_html=True)          # each paragraph takes the direction of its own language


@st.cache_resource
def get_api() -> NovaCartApi:
    return NovaCartApi(os.getenv("BACKEND_URL", "http://localhost:8000"), os.getenv("GATEWAY_URL", "http://localhost:8080"))


def logout(notice: str | None = None) -> None:
    for key in ("user", "username", "messages", "queued"):
        st.session_state.pop(key, None)
    if notice:
        st.session_state["notice"] = notice


def login_view() -> None:
    st.title("NovaCart 💬")
    if st.session_state.get("notice"):
        st.warning(st.session_state.pop("notice"))
    with st.form("login"):
        username = st.text_input("اسم المستخدم", placeholder="c-100003  أو  w-2001")
        password = st.text_input("كلمة المرور", type="password")
        if st.form_submit_button("دخول", use_container_width=True):
            try:
                st.session_state["user"] = get_api().login(username.strip(), password)
                st.session_state["username"] = username.strip()
                st.session_state["messages"] = []
                st.rerun()
            except LoginFailed:
                st.error("اسم المستخدم أو كلمة المرور غلط.")
            except ServiceUnavailable:
                st.error("الخدمة مش متاحة دلوقتي. جرّب بعد شوية.")
    st.caption(os.getenv("LOGIN_HINT", "حسابات التجربة موجودة في backend/SEED_SCENARIOS.md"))


def show(message: dict, dev: bool) -> None:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if dev and message.get("raw"):
            with st.expander(f"تفاصيل تقنية · {message['elapsed_s']:.2f} ث"):
                st.code(json.dumps(message["raw"], ensure_ascii=False, indent=2), language="json")


def send(prompt: str, dev: bool) -> None:
    user = st.session_state["user"]
    question = {"role": "user", "content": prompt}
    st.session_state["messages"].append(question)
    show(question, dev)
    with st.spinner("لحظة..."):
        try:
            reply = get_api().chat(user, prompt)
        except SessionExpired:
            logout("الجلسة انتهت. سجّل دخول تاني.")
            st.rerun()
        except RateLimited as limited:
            answer = {"role": "assistant", "content": LIMIT_MESSAGE[limited.reason], "raw": None}
        except ServiceUnavailable:
            answer = {"role": "assistant", "content": "الخدمة مش متاحة دلوقتي. جرّب بعد شوية.", "raw": None}
        else:
            answer = {"role": "assistant", "content": render_reply(reply, detect_language(prompt)),
                      "raw": reply.raw, "elapsed_s": reply.elapsed_s}
    st.session_state["messages"].append(answer)
    show(answer, dev)


def chat_view() -> None:
    user = st.session_state["user"]
    with st.sidebar:
        st.markdown(f"**{st.session_state['username']}** · {user.role}")
        dev = st.toggle("عرض تفاصيل تقنية", value=False, help="الرد الخام من الـ Gateway وزمنه (للمطوّر)")
        if st.button("خروج", use_container_width=True):
            logout()
            st.rerun()

    st.title(ROLE_TITLE.get(user.role, "NovaCart"))
    with st.chat_message("assistant"):
        st.markdown(WELCOME.get(user.role, ""))
    for message in st.session_state["messages"]:
        show(message, dev)

    st.caption("اختار مشكلتك:")
    options = options_for(user.role)
    for start in range(0, len(options), PER_ROW):
        for column, option in zip(st.columns(PER_ROW), options[start:start + PER_ROW]):
            if column.button(option.label, key=f"opt-{option.intent}-{option.label}", use_container_width=True):
                st.session_state["queued"] = option.message
    typed = st.chat_input("اكتب رسالتك هنا")
    prompt = st.session_state.pop("queued", None) or typed
    if prompt:
        send(prompt, dev)


if "user" in st.session_state:
    chat_view()
else:
    login_view()
