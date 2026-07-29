"""Auth-gated landing page — design cues from secure product login screens."""

from __future__ import annotations

import streamlit as st

from frontend.state import is_logged_in, login_user, register_user


LANDING_CSS = """
<style>
/* Hide default chrome while on landing */
[data-testid="stSidebar"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
header[data-testid="stHeader"] {
  background: transparent !important;
  border: none !important;
}
.block-container {
  max-width: 1100px !important;
  padding-top: 2rem !important;
  padding-bottom: 2rem !important;
}

.lp-brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 0.35rem;
}
.lp-logo {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: linear-gradient(145deg, #3b82f6 0%, #22c55e 55%, #a78bfa 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
  box-shadow: 0 6px 20px rgba(59, 130, 246, 0.25);
}
.lp-title {
  font-size: 1.75rem;
  font-weight: 700;
  color: #f0f3f6 !important;
  letter-spacing: -0.03em;
  margin: 0;
  line-height: 1.2;
}
.lp-tagline {
  color: #8b9bb4;
  font-size: 0.95rem;
  margin: 0.4rem 0 1.25rem 0;
  line-height: 1.5;
}
.lp-divider {
  border: none;
  border-top: 1px solid #243041;
  margin: 0.5rem 0 1.75rem 0;
}
.lp-section-title {
  font-size: 1.15rem;
  font-weight: 600;
  color: #e8eef7;
  margin: 0 0 0.5rem 0;
}
.lp-section-sub {
  color: #8b9bb4;
  font-size: 0.88rem;
  margin-bottom: 1rem;
  line-height: 1.45;
}
.lp-card {
  background: #12161c;
  border: 1px solid #2a3441;
  border-radius: 12px;
  padding: 1.35rem 1.4rem 1.2rem 1.4rem;
  box-shadow: 0 8px 32px rgba(0,0,0,0.28);
}
.lp-feature {
  background: #151a21;
  border: 1px solid #243041;
  border-radius: 10px;
  padding: 0.75rem 1rem;
  margin-bottom: 0.55rem;
  color: #c9d1d9;
  font-size: 0.92rem;
}
.lp-feature strong { color: #e8eef7; }
.lp-login-head {
  font-size: 1.15rem;
  font-weight: 600;
  color: #e8eef7;
  margin: 0 0 1rem 0;
}
.lp-footer {
  text-align: center;
  color: #6e7a8a;
  font-size: 0.82rem;
  margin-top: 2.5rem;
  padding-top: 1rem;
  border-top: 1px solid #1e2630;
}
.lp-hint {
  color: #8b9bb4;
  font-size: 0.8rem;
  margin-top: 0.75rem;
}
/* Primary green CTA like reference */
div[data-testid="stForm"] .stButton > button[kind="primary"],
div[data-testid="stForm"] button[data-testid="baseButton-primary"],
.stForm button[type="submit"] {
  background: linear-gradient(180deg, #22c55e 0%, #16a34a 100%) !important;
  color: #04140a !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 700 !important;
  width: 100%;
  min-height: 2.6rem;
}
div[data-testid="stForm"] .stButton > button[kind="primary"]:hover {
  filter: brightness(1.06);
  box-shadow: 0 0 0 1px #4ade80 !important;
}
/* Secondary create-account button */
.lp-alt-btn button {
  background: transparent !important;
  border: 1px solid #2a3441 !important;
  color: #c9d1d9 !important;
  width: 100%;
}
</style>
"""


def _brand_header() -> None:
    st.markdown(
        """
        <div class="lp-brand">
          <div class="lp-logo">📈</div>
          <h1 class="lp-title">MF Analysis Tool</h1>
        </div>
        <p class="lp-tagline">
          Portfolio health · CAS import · fund overlap · risk &amp; return ·
          goal planning · ML ranking · AI assistant
        </p>
        <hr class="lp-divider" />
        """,
        unsafe_allow_html=True,
    )


def _features_column() -> None:
    st.markdown(
        """
        <p class="lp-section-title">✨ What's inside</p>
        <p class="lp-section-sub">
          Key capabilities in this release. Sign in to open the full workspace —
          Dashboard, CAS vault, analytics, and more.
        </p>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("📊 Portfolio command center", expanded=False):
        st.markdown(
            """
- Live portfolio value, P&L, and health score  
- Asset / sector / market-cap allocation charts  
- Fast analysis mode for large CAS portfolios  
            """
        )
    with st.expander("📤 MFCentral CAS import & vault", expanded=False):
        st.markdown(
            """
- Upload Consolidated Account Summary PDF  
- Map schemes to AMFI codes  
- Save & reopen portfolios after restart (signed-in)  
            """
        )
    with st.expander("🔗 Overlap · X-Ray · comparison", expanded=False):
        st.markdown(
            """
- Pairwise fund overlap heatmaps  
- Risk vs return bubbles with plain-language ranking  
- Fund health score and X-Ray diagnostics  
            """
        )
    with st.expander("🤖 ML · goals · AI assistant", expanded=False):
        st.markdown(
            """
- Goal planner with Monte Carlo paths  
- Model comparison (XGBoost / LightGBM / CatBoost / …)  
- OpenAI-compatible assistant with portfolio context  
            """
        )


def _login_form() -> None:
    st.markdown(
        '<p class="lp-login-head">🔒 Secure login</p>',
        unsafe_allow_html=True,
    )
    with st.form("landing_login", clear_on_submit=False):
        email = st.text_input("Email", placeholder="you@example.com", label_visibility="visible")
        password = st.text_input(
            "Password",
            type="password",
            placeholder="your password",
            label_visibility="visible",
        )
        submitted = st.form_submit_button("Access Dashboard →", type="primary", use_container_width=True)
        if submitted:
            try:
                login_user(email.strip(), password)
                st.success("Signed in — loading workspace…")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.markdown(
        '<p class="lp-hint">Access is restricted to registered users. Create an account below if you are new.</p>',
        unsafe_allow_html=True,
    )


def _register_form() -> None:
    st.markdown(
        '<p class="lp-login-head">✨ Create account</p>',
        unsafe_allow_html=True,
    )
    with st.form("landing_register", clear_on_submit=False):
        full_name = st.text_input("Full name (optional)", placeholder="Your name")
        email = st.text_input("Email", placeholder="you@example.com", key="lp_reg_email")
        password = st.text_input(
            "Password (min 6 characters)",
            type="password",
            key="lp_reg_pw",
        )
        password2 = st.text_input(
            "Confirm password",
            type="password",
            key="lp_reg_pw2",
        )
        submitted = st.form_submit_button("Create account & enter →", type="primary", use_container_width=True)
        if submitted:
            if password != password2:
                st.error("Passwords do not match.")
            else:
                try:
                    register_user(email.strip(), password, full_name.strip() or None)
                    st.success("Account created — loading workspace…")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def render_landing() -> None:
    """Full-screen landing; call only when user is not authenticated."""
    st.markdown(LANDING_CSS, unsafe_allow_html=True)
    _brand_header()

    left, right = st.columns([1.15, 0.95], gap="large")

    with left:
        _features_column()

    with right:
        st.markdown('<div class="lp-card">', unsafe_allow_html=True)
        mode = st.radio(
            "Auth mode",
            ["Sign in", "Create account"],
            horizontal=True,
            label_visibility="collapsed",
            key="lp_auth_mode",
        )
        if mode == "Sign in":
            _login_form()
        else:
            _register_form()
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class="lp-footer">
          ⚠️ Educational purposes only — not financial advice ·
          MF Analysis Tool · Portfolio vault &amp; analytics
        </div>
        """,
        unsafe_allow_html=True,
    )


def require_auth() -> bool:
    """
    Return True if user may enter the app.
    If not logged in, render landing and return False.
    """
    if is_logged_in():
        return True
    render_landing()
    return False
