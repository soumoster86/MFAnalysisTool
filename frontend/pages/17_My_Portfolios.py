"""My Portfolios — portfolio vault (Slice A)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.state import (
    get_active_portfolio_id,
    get_current_user,
    get_vault,
    init_portfolio_holdings,
    is_logged_in,
    load_portfolio_into_session,
    save_session_to_vault,
    set_active_portfolio_id,
    set_portfolio_holdings,
)
from frontend.theme import apply_theme
from utils.helpers import format_inr

apply_theme()

st.title("My Portfolios")
st.caption("Save, load, and manage portfolios — reopen after app restart.")

if not is_logged_in():
    st.warning("Sign in to use the portfolio vault.")
    st.page_link("pages/0_Account.py", label="Go to Account", icon="👤")
    st.stop()

user = get_current_user()
vault = get_vault()
assert user is not None

st.write(f"Signed in as **{user['email']}**")

# ---- Save current session ----
st.subheader("Save current working portfolio")
holdings = init_portfolio_holdings()
n = len([h for h in holdings if h.get("amfi_code")])
st.caption(f"Session currently has **{n}** scheme line(s).")

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    save_name = st.text_input(
        "Portfolio name",
        value=st.session_state.get("vault_save_name")
        or f"My Portfolio",
    )
with c2:
    update_existing = st.checkbox(
        "Update active portfolio",
        value=bool(get_active_portfolio_id()),
        help="If checked and an active portfolio is loaded, overwrite it.",
    )
with c3:
    as_of = st.text_input("As-of date (optional)", value="")

if st.button("Save to vault", type="primary"):
    try:
        pid = get_active_portfolio_id() if update_existing else None
        saved = save_session_to_vault(
            name=save_name,
            portfolio_id=pid,
            source=st.session_state.get("portfolio_source") or "manual",
            as_of_date=as_of or None,
        )
        set_active_portfolio_id(saved["id"])
        st.success(
            f"Saved **{saved['name']}** (#{saved['id']}) · "
            f"{saved.get('holdings_count', 0)} holdings · "
            f"{format_inr(saved.get('total_market_value') or 0)}"
        )
        st.rerun()
    except Exception as exc:
        st.error(str(exc))

st.markdown("---")
st.subheader("Saved portfolios")

try:
    portfolios = vault.list_portfolios(user["id"])
except Exception as exc:
    st.error(f"Could not list portfolios: {exc}")
    st.stop()

if not portfolios:
    st.info("No saved portfolios yet. Import a CAS or build holdings, then save.")
    st.page_link("pages/16_Upload_CAS.py", label="Upload CAS", icon="📤")
    st.stop()

# Summary table
summary_df = pd.DataFrame(
    [
        {
            "ID": p["id"],
            "Name": p["name"],
            "Source": p.get("source"),
            "Holdings": p.get("holdings_count"),
            "Invested": p.get("total_invested"),
            "Market value": p.get("total_market_value"),
            "Default": "★" if p.get("is_default") else "",
            "Updated": (p.get("updated_at") or "")[:16],
        }
        for p in portfolios
    ]
)
st.dataframe(summary_df, use_container_width=True, hide_index=True)

options = {f"#{p['id']} · {p['name']}": p["id"] for p in portfolios}
choice = st.selectbox("Select portfolio", list(options.keys()))
pid = options[choice]

b1, b2, b3, b4 = st.columns(4)
with b1:
    if st.button("Load into app", type="primary", use_container_width=True):
        try:
            detail = load_portfolio_into_session(pid)
            st.success(
                f"Loaded **{detail['name']}** ({detail.get('holdings_count')} funds). "
                "Open Dashboard or Analyzer."
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
with b2:
    if st.button("Set as default", use_container_width=True):
        try:
            vault.update_portfolio(pid, user["id"], set_default=True)
            st.success("Default updated")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
with b3:
    if st.button("Rename…", use_container_width=True):
        st.session_state["rename_pid"] = pid
with b4:
    if st.button("Delete", use_container_width=True):
        st.session_state["delete_pid"] = pid

if st.session_state.get("rename_pid") == pid:
    new_name = st.text_input("New name", value=next(p["name"] for p in portfolios if p["id"] == pid))
    if st.button("Confirm rename"):
        vault.update_portfolio(pid, user["id"], name=new_name)
        st.session_state.pop("rename_pid", None)
        st.success("Renamed")
        st.rerun()

if st.session_state.get("delete_pid") == pid:
    st.warning("Delete this portfolio permanently?")
    if st.button("Confirm delete", type="primary"):
        vault.delete_portfolio(pid, user["id"])
        if get_active_portfolio_id() == pid:
            set_active_portfolio_id(None)
        st.session_state.pop("delete_pid", None)
        st.success("Deleted")
        st.rerun()

# Preview holdings
try:
    detail = vault.get_portfolio(pid, user["id"])
    st.subheader(f"Preview · {detail['name']}")
    hdf = pd.DataFrame(detail.get("holdings") or [])
    if not hdf.empty:
        show = [
            c
            for c in [
                "scheme_name",
                "amfi_code",
                "units",
                "invested_amount",
                "market_value",
                "current_nav",
            ]
            if c in hdf.columns
        ]
        st.dataframe(hdf[show], use_container_width=True, hide_index=True)
    else:
        st.caption("No holdings in this portfolio.")
except Exception as exc:
    st.error(str(exc))
