"""Account — profile & sign-out (landing handles login for guests)."""

from __future__ import annotations

import streamlit as st

from frontend.state import clear_auth, get_current_user, is_logged_in
from frontend.components.page import page_header
from frontend.theme import apply_theme

apply_theme()

page_header(
    "Account",
    "Signed-in profile and session controls.",
    "👤",
)

if not is_logged_in():
    st.warning("You are not signed in. Return to the landing page to authenticate.")
    st.stop()

user = get_current_user() or {}
st.success(f"Signed in as **{user.get('email')}**", icon="✅")
if user.get("full_name"):
    st.write(f"**Name:** {user['full_name']}")
st.write(f"**User ID:** `{user.get('id')}`")

c1, c2 = st.columns(2)
with c1:
    st.page_link("pages/17_My_Portfolios.py", label="Open My Portfolios", icon="💼")
with c2:
    st.page_link("pages/1_Dashboard.py", label="Open Dashboard", icon="📊")

st.markdown("---")
if st.button("Sign out", type="primary"):
    clear_auth()
    st.rerun()

st.caption(
    "Signing out returns you to the secure landing page. "
    "Saved portfolios remain in the vault for your next session."
)
