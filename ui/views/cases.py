"""Cases: what the agent handed over to a person. For the support and admin roles.

The list is ordered by urgency (P1 first). A case is claimed (only from PENDING) and resolved with a note; resolving
erases the verified user id and the verified order ids in the database. Every change carries the staff member's name.
"""
from __future__ import annotations

import os

import streamlit as st

from novacart_ui.cases import (NOTE_MAX, REASON_LABEL, STATUS_LABEL, STATUSES, claim, fetch_case, fetch_cases, resolve,
                               summary_lines)
from novacart_ui.gate import admin_gate

st.set_page_config(page_title="NovaCart · الحالات", page_icon="📥", layout="wide")
st.markdown("""<style>
[data-testid="stMarkdownContainer"] p { unicode-bidi: plaintext; }
</style>""", unsafe_allow_html=True)

DSN = os.environ["GATEWAY_DATABASE_URL"]
ALL = "الكل"


def label(row) -> str:
    return f"{row['priority'] or '—'} · {REASON_LABEL.get(row['reason'], row['reason'])} · {STATUS_LABEL[row['status']]} · {str(row['created_at'])[:16]} · {row['handoff_id'][:8]}"


def flash(kind: str, text: str) -> None:
    """A message that survives the rerun that follows an action (a message drawn just before st.rerun() would vanish)."""
    st.session_state["flash"] = (kind, text)


def board() -> None:
    staff = st.session_state["admin_user"]["username"]
    if "flash" in st.session_state:
        kind, text = st.session_state.pop("flash")
        getattr(st, kind)(text)
    top = st.columns([3, 1, 1, 1])
    top[0].title("الحالات 📥")
    status = top[1].selectbox("الحالة", [ALL, *STATUSES], index=1, format_func=lambda s: s if s == ALL else STATUS_LABEL[s])
    reason = top[2].selectbox("السبب", [ALL, *REASON_LABEL], format_func=lambda r: r if r == ALL else REASON_LABEL[r])
    if top[3].button("تحديث", use_container_width=True):
        st.rerun()
    try:
        everything = fetch_cases(DSN)
        shown = fetch_cases(DSN, None if status == ALL else status, None if reason == ALL else reason)
    except Exception:                                             # noqa: BLE001  any database trouble becomes one clear message
        st.error("مش قادر أقرا الحالات من قاعدة البيانات.")
        return

    counts = everything["status"].value_counts()
    cols = st.columns(4)
    cols[0].metric("مستني استلام", int(counts.get("PENDING", 0)))
    cols[1].metric("مستلمة", int(counts.get("CLAIMED", 0)))
    cols[2].metric("اتقفلت", int(counts.get("RESOLVED", 0)))
    cols[3].metric("P1 مفتوحة", int(((everything["priority"] == "P1") & (everything["status"] != "RESOLVED")).sum()))
    if shown.empty:
        st.info("مفيش حالات بالفلتر ده.")
        return
    table = shown[["priority", "reason", "status", "created_at", "role", "subject_id", "claimed_by"]].copy()
    table["reason"] = table["reason"].map(lambda r: REASON_LABEL.get(r, r))
    table["status"] = table["status"].map(STATUS_LABEL)
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.subheader("تفاصيل حالة")
    rows = shown.to_dict("records")
    chosen = st.selectbox("اختار حالة", rows, format_func=label)
    case = fetch_case(DSN, chosen["handoff_id"])
    if case is None:
        st.warning("الحالة دي اتمسحت.")
        return
    left, right = st.columns([2, 1])
    with left:
        if case["block_session_data"]:
            st.error("حالة أمان: ما تعرضش بيانات الحساب للعميل في الجلسة دي.")
        st.markdown(f"**السبب:** {REASON_LABEL.get(case['reason'], case['reason'])} · **الأولوية:** {case['priority'] or 'لسه'} · "
                    f"**الدور:** {case['role']} · **الحالة:** {STATUS_LABEL[case['status']]}")
        st.markdown(f"**معرّف العميل:** {case['subject_id'] or 'اتمسح عند الإغلاق'}")
        for line in summary_lines(case["summary"]):
            st.markdown(f"- {line}")
        if case["claimed_by"]:
            st.caption(f"استلمها {case['claimed_by']} · {str(case['claimed_at'])[:16]}")
        if case["status"] == "RESOLVED":
            st.caption(f"قفلها {case['resolved_by']} · {str(case['resolved_at'])[:16]}")
            st.info(f"ملاحظة الموظف: {case['note'] or '—'}")
    with right:
        if case["status"] == "PENDING" and st.button("استلام الحالة", use_container_width=True):
            if claim(DSN, case["handoff_id"], staff):
                flash("success", "اتستلمت. لما تخلّص اختار \"مستلمة\" من فلتر الحالة وقفلها بملاحظة.")
            else:
                flash("warning", "حد تاني استلمها قبلك.")
            st.rerun()
        if case["status"] in ("PENDING", "CLAIMED"):
            note = st.text_area("ملاحظة الإغلاق", max_chars=NOTE_MAX, help="من غير بيانات شخصية. المعرّف بيتمسح تلقائي.")
            if st.button("إغلاق الحالة", use_container_width=True, type="primary"):
                if resolve(DSN, case["handoff_id"], staff, note):
                    flash("success", "اتقفلت، والمعرّف اتمسح.")
                else:
                    flash("warning", "الحالة دي اتقفلت قبل كده.")
                st.rerun()


if admin_gate("الحالات 📥", ("admin", "support")):
    board()
