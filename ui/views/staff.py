"""The staff sign-in page (open to every visitor): see novacart_ui/gate.py."""
import streamlit as st

from novacart_ui.gate import staff_page

st.set_page_config(page_title="NovaCart · الفريق", page_icon="🔐")
staff_page()
