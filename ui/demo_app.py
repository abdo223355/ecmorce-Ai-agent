"""NovaCart chat screen in DEMO mode: recorded answers, no backend and no model. Run: streamlit run demo_app.py

This is the entry for a free host (Streamlit Community Cloud: main file `ui/demo_app.py`). It needs no environment variable
and no secret. The live screen with the real system is `app.py` (docker compose).
"""
import json

import streamlit as st

from novacart_ui.demo import DemoStore
from novacart_ui.texts import detect_language, render_reply

ROLE_TITLE = {"customer": "مساعد العملاء", "worker": "مساعد المندوب"}
ACCOUNT_NOTE = {
    "c-100005": "طلبات للإلغاء (Pending وPacked وProcessing)",
    "c-100001": "إلكترونيات: إرجاع واستبدال",
    "c-100003": "منتج Final Sale",
    "c-100006": "مرتجعات بحالات مختلفة",
    "c-100009": "طلبين لنفس المنتج",
    "c-100010": "طلبات في الطريق",
    "w-2001": "مندوب توصيل",
}
PER_ROW = 2

st.set_page_config(page_title="NovaCart demo", page_icon="💬", layout="centered")
st.markdown("""<style>
[data-testid="stChatMessageContent"] p { unicode-bidi: plaintext; text-align: start; }
</style>""", unsafe_allow_html=True)


@st.cache_resource
def get_store() -> DemoStore:
    return DemoStore.load()


store = get_store()
accounts = store.accounts()

with st.sidebar:
    st.markdown("**Demo** · ردود مسجّلة من النظام الحقيقي")
    account = st.selectbox("حساب تجريبي", [a for a, _ in accounts],
                           format_func=lambda a: f"{a} — {ACCOUNT_NOTE.get(a, '')}")
    dev = st.toggle("عرض الرد الخام", value=False, help="الرد كما أرسله الـ Gateway وقت التسجيل")
    st.caption("الكود والتصميم والـ evals: github.com/abdo223355/ecmorce-Ai-agent")

if st.session_state.get("demo_account") != account:           # a new account starts a new conversation
    st.session_state["demo_account"] = account
    st.session_state["demo_messages"] = []

role = dict(accounts)[account]
st.title(ROLE_TITLE.get(role, "NovaCart"))
st.info("Demo: الردود دي اتسجّلت من النظام الحقيقي، ومفيش موديل شغّال هنا، فبتقدر تسأل الأسئلة الجاهزة بس.\n\n"
        f"Recorded answers from the real system ({store.recorded_on}), no live model: pick one of the questions below.")


def show(message: dict) -> None:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if dev and message.get("raw"):
            with st.expander("الرد الخام"):
                st.code(json.dumps(message["raw"], ensure_ascii=False, indent=2), language="json")


def send(prompt: str) -> None:
    st.session_state["demo_messages"].append({"role": "user", "content": prompt})
    reply = store.answer(account, prompt)
    if reply is None:
        content = ("السؤال ده مش من الأسئلة المسجّلة في الـ demo. اختار واحد من الأزرار تحت.\n\n"
                   "This question is not one of the recorded ones: pick a button below.")
        st.session_state["demo_messages"].append({"role": "assistant", "content": content, "raw": None})
    else:
        st.session_state["demo_messages"].append(
            {"role": "assistant", "content": render_reply(reply, detect_language(prompt)), "raw": reply.raw})


for message in st.session_state["demo_messages"]:
    show(message)

st.caption("جرّب سؤال:")
options = store.suggestions(account)
for start in range(0, len(options), PER_ROW):
    for column, text in zip(st.columns(PER_ROW), options[start:start + PER_ROW]):
        if column.button(text, key=f"q-{account}-{text}", use_container_width=True):
            st.session_state["demo_queued"] = text
typed = st.chat_input("اكتب واحد من الأسئلة الجاهزة")
prompt = st.session_state.pop("demo_queued", None) or typed
if prompt:
    send(prompt)
    st.rerun()
