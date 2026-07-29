"""
MF Analysis Tool — Streamlit UI
Auth-gated landing page → full multipage workspace when signed in.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

# Streamlit Cloud: map secrets → env, rebuild settings + DB engine
try:
    from config.cloud_bootstrap import inject_streamlit_secrets
    import config.settings as settings_mod

    inject_streamlit_secrets()
    settings_mod.get_settings.cache_clear()
    settings_mod.settings = settings_mod.get_settings()
    # Rebuild SQLAlchemy engine if DATABASE_URL came from st.secrets
    try:
        from database import session as db_session

        db_session.rebind_engine_from_settings()
    except Exception:
        pass
except Exception:
    pass

from config.settings import settings
from frontend.theme import apply_theme
from utils.logging_config import setup_logging

setup_logging(settings.log_level)

# Ensure vault/auth tables exist (Supabase Postgres or SQLite)
try:
    from database.session import init_db

    init_db()
except Exception as _db_exc:
    # Surface clearly on landing if DB is misconfigured
    import streamlit as _st

    _st.error(
        f"Database connection failed. Check DATABASE_URL in Streamlit Secrets "
        f"(Supabase Postgres URI). Details: {_db_exc}"
    )


st.set_page_config(
    page_title="MF Analysis Tool",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()

from frontend.landing import require_auth
from frontend.state import (
    clear_auth,
    get_active_portfolio_id,
    get_current_user,
    is_logged_in,
)

# ---------------------------------------------------------------------------
# Auth gate — landing page until signed in
# ---------------------------------------------------------------------------
if not require_auth():
    st.stop()

# ---------------------------------------------------------------------------
# Authenticated workspace
# ---------------------------------------------------------------------------
dashboard = st.Page("pages/1_Dashboard.py", title="Dashboard", icon="📊", default=True)
fund_db = st.Page("pages/2_Fund_Database.py", title="Fund Database", icon="🗄️")
health = st.Page("pages/3_Fund_Health.py", title="Fund Health Score", icon="💚")
analyzer = st.Page("pages/4_Portfolio_Analyzer.py", title="Portfolio Analyzer", icon="🧭")
overlap = st.Page("pages/5_Overlap_Detector.py", title="Overlap Detector", icon="🔗")
compare = st.Page("pages/6_Fund_Comparison.py", title="Fund Comparison", icon="⚖️")
goals = st.Page("pages/7_Goal_Planner.py", title="Goal Planner", icon="🎯")
ml_engine = st.Page("pages/8_ML_Engine.py", title="ML Engine", icon="🤖")
recommend = st.Page("pages/9_Recommendations.py", title="Recommendations", icon="✨")
optimizer = st.Page("pages/10_Portfolio_Optimizer.py", title="Optimizer", icon="📐")
xray = st.Page("pages/11_Fund_XRay.py", title="Fund X-Ray", icon="🔬")
assistant = st.Page("pages/12_AI_Assistant.py", title="AI Assistant", icon="💬")
alerts = st.Page("pages/13_Alerts.py", title="Alerts", icon="🔔")
viz = st.Page("pages/14_Visualizations.py", title="Visualizations", icon="📉")
reports = st.Page("pages/15_Reports.py", title="Reports", icon="📄")
upload_cas = st.Page("pages/16_Upload_CAS.py", title="Upload CAS", icon="📤")
account = st.Page("pages/0_Account.py", title="Account", icon="👤")
my_portfolios = st.Page("pages/17_My_Portfolios.py", title="My Portfolios", icon="💼")

nav = st.navigation(
    {
        "Overview": [dashboard, fund_db, upload_cas, my_portfolios, account],
        "Analysis": [health, analyzer, overlap, compare, xray],
        "Planning": [goals, recommend, optimizer],
        "Intelligence": [ml_engine, assistant, alerts],
        "Output": [viz, reports],
    }
)

with st.sidebar:
    st.markdown("### 📈 MF Analysis Tool")
    st.caption("AI · ML · Quant Analytics")
    st.markdown("---")
    if is_logged_in():
        u = get_current_user() or {}
        st.success(f"{u.get('email', '')}", icon="👤")
        pid = get_active_portfolio_id()
        if pid:
            st.caption(f"Active vault portfolio #{pid}")
        if st.button("Sign out", use_container_width=True):
            clear_auth()
            st.rerun()
    st.caption(f"Env: `{settings.app_env}`")
    if settings.openai_api_key:
        st.caption("LLM configured")
    st.markdown(
        '<p class="muted">Not investment advice. Educational use only.</p>',
        unsafe_allow_html=True,
    )

nav.run()
