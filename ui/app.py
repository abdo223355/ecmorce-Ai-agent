"""Entry of the screens. It only builds the side menu from WHO is signed in, then runs the chosen page.

Everyone sees the chat and the staff sign-in. The cases console appears for a signed-in admin or support person; the Admin
dashboard and the Lab only for an admin; for anyone else those pages are not registered at all, so their addresses do not open (the pages still check the role themselves).
Run: streamlit run app.py
"""
import streamlit as st

from novacart_ui.gate import check_idle

check_idle()
user = st.session_state.get("admin_user")
pages = [st.Page("views/chat.py", title="الشات", icon="💬", default=True)]
if user and user["role"] in ("admin", "support"):
    pages.append(st.Page("views/cases.py", title="الحالات", icon="📥", url_path="cases"))
if user and user["role"] == "admin":
    pages += [st.Page("views/admin.py", title="لوحة المراقبة", icon="📊", url_path="admin"),
              st.Page("views/lab.py", title="المعمل", icon="🧪", url_path="lab")]
pages.append(st.Page("views/staff.py", title="حسابي" if user else "دخول الفريق", icon="🔐", url_path="staff"))
st.navigation(pages).run()
