"""The PUBLIC chat screen: the live system (real Gateway, real model) for anyone, on Streamlit Community Cloud.
Run: streamlit run public_app.py

It is the same chat page as the local stack (views/chat.py) and nothing else: no admin pages, no cases console, no
database connection. It only needs two addresses, set in the host's "Secrets" (Streamlit exposes every top-level secret
as an environment variable, which is what the chat page reads):

    BACKEND_URL = "https://<your-backend>.onrender.com"
    GATEWAY_URL = "https://<your-gateway>.onrender.com"

The usage limits (per minute, and a daily cap) are enforced by the Gateway, not by this screen.
"""
import os
import runpy
from pathlib import Path

# Nothing from Streamlit may be called before the chat page runs: its first command must be st.set_page_config.
os.environ.setdefault("LOGIN_HINT", "حسابات تجريبية: c-100005 · c-100001 · c-100006 · w-2001  |  كلمة المرور: NovaCart#2026")
runpy.run_path(str(Path(__file__).resolve().parent / "views" / "chat.py"), run_name="__main__")
